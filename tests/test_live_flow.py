import http.client
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
from report_progress import initialize, update
from serve_flow_panel import FlowState, PanelServer, session_options, save_session


class LiveFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.flow = self.root / 'flow.json'
        initialize(self.flow, 'Synthetic project', ['Probe', 'Sample'])
        self.state = FlowState(self.flow, interval=0.05)
        self.server = PanelServer(self.state)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]
        self.prefix = '/' + self.server.token + '/'

    def tearDown(self):
        self.state.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def get(self, path, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=3)
        conn.request('GET', self.prefix + path, headers=headers or {})
        response = conn.getresponse()
        status, body = response.status, response.read()
        conn.close()
        return status, body

    def event(self, response):
        while True:
            line = response.readline().decode()
            if not line:
                raise AssertionError('SSE closed before update')
            if line.startswith('data: '):
                data = json.loads(line[6:])
                if 'revision' in data:
                    return data

    def test_stream_update_error_and_recovery_without_reconnect(self):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=3)
        conn.request('GET', self.prefix + 'events')
        response = conn.getresponse()
        self.assertEqual(response.status, 200)
        initial = self.event(response)
        update(self.flow, 1, 'running', 25, 'Working')
        changed = self.event(response)
        self.assertGreater(changed['revision'], initial['revision'])
        self.assertEqual(changed['data']['steps'][0]['progress'], 25)
        valid = self.flow.read_bytes()
        self.flow.write_text('{broken', encoding='utf-8')
        error = self.event(response)
        self.assertTrue(error['error'])
        self.assertEqual(error['data'], changed['data'])
        self.flow.write_bytes(valid)
        recovered = self.event(response)
        self.assertIsNone(recovered['error'])
        self.assertEqual(recovered['data']['steps'][0]['status'], 'running')
        conn.close()

    def test_host_origin_and_unlisted_paths_are_rejected(self):
        self.assertEqual(self.get('snapshot', {'Host': 'evil.example'})[0], 403)
        self.assertEqual(self.get('snapshot', {'Origin': 'https://evil.example'})[0], 403)
        self.assertEqual(self.get('../flow.json')[0], 404)
        self.assertEqual(self.get('media/not-registered.mp4')[0], 404)
        self.assertEqual(self.get('snapshot')[0], 200)

    def test_explicit_media_range_and_no_filesystem_path_in_payload(self):
        media = self.root / 'synthetic.mp4'
        media.write_bytes(b'0123456789')
        update(self.flow, 2, 'ready', artifact=media, asset_type='video')
        self.state.refresh()
        payload = self.state.snapshot()['data']
        self.assertNotIn(str(self.root), json.dumps(payload))
        route = payload['assets']['step_2_output']['src']
        self.assertEqual(self.get(route, {'Range': 'bytes=2-5'}), (206, b'2345'))
        self.assertEqual(self.get(route, {'Range': 'bytes=200-300'})[0], 416)

    def test_concurrent_updates_and_revision_conflict(self):
        failures = []
        def writer(index):
            try:
                update(self.flow, index, 'running', index * 20)
            except Exception as exc:
                failures.append(str(exc))
        threads = [threading.Thread(target=writer, args=(i,)) for i in (1, 2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(failures, [])
        data = json.loads(self.flow.read_text())
        self.assertEqual(data['meta']['revision'], 3)
        self.assertEqual([s['status'] for s in data['steps']], ['running', 'running'])
        with self.assertRaisesRegex(ValueError, 'Revision conflict'):
            update(self.flow, 1, 'accepted', expected_revision=1)

    def test_wrapper_propagates_exit_and_never_auto_accepts(self):
        base = [sys.executable, str(SCRIPTS / 'report_progress.py'), 'run', '--data', str(self.flow),
                '--step', '1', '--log']
        failed = subprocess.run(base + [str(self.root / 'failed.log'), '--', sys.executable, '-c', 'raise SystemExit(7)'], capture_output=True)
        self.assertEqual(failed.returncode, 7)
        self.assertEqual(json.loads(self.flow.read_text())['steps'][0]['status'], 'failed')
        passed = subprocess.run(base + [str(self.root / 'passed.log'), '--', sys.executable, '-c', 'print("ok")'], capture_output=True)
        self.assertEqual(passed.returncode, 0, passed.stderr)
        self.assertEqual(json.loads(self.flow.read_text())['steps'][0]['status'], 'ready')

    def test_resume_session_keeps_url_and_rejects_wrong_project(self):
        session = self.root / '.flow-panel-session.json'
        save_session(session, self.server)
        port, token = session_options(session, self.flow, 0)
        self.assertEqual((port, token), (self.port, self.server.token))
        with self.assertRaises(ValueError):
            session_options(session, self.root / 'other.json', 0)
        with self.assertRaises(ValueError):
            session_options(session, self.flow, self.port + 1)

    def test_bad_progress_is_rejected_and_output_replaces_placeholder(self):
        before = self.flow.read_bytes()
        for value in (float('nan'), float('inf'), True, -1, 101):
            with self.assertRaises(ValueError):
                update(self.flow, 1, progress=value)
            self.assertEqual(self.flow.read_bytes(), before)
        update(self.flow, 1, 'ready', 100, output='Environment report produced')
        data = json.loads(self.flow.read_text())
        self.assertEqual(data['chart']['nodes'][0]['text'], 'Environment report produced')

    def test_media_retention_never_evicts_current_references(self):
        fixed = self.root / 'fixed.mp4'
        fixed.write_bytes(b'reference')
        update(self.flow, 1, artifact=fixed, asset_type='video')
        self.state.refresh()
        url = self.state.snapshot()['data']['assets']['step_1_output']['src']
        for i in range(256):
            self.state.media['media/previous_%s.mp4' % i] = (fixed, (0, 0))
        update(self.flow, 2, message='New step')
        self.state.refresh()
        self.assertEqual(len(self.state.media), 256)
        self.assertEqual(self.get(url), (200, b'reference'))

    @unittest.skipUnless(os.name == 'posix', 'POSIX signal cancellation')
    def test_term_cancels_wrapper_child_and_records_failure(self):
        marker = self.root / 'started.txt'
        code = 'from pathlib import Path; import time; Path(%r).write_text("started"); time.sleep(30)' % str(marker)
        proc = subprocess.Popen([sys.executable, str(SCRIPTS / 'report_progress.py'), 'run',
            '--data', str(self.flow), '--step', '1', '--log', str(self.root / 'cancel.log'),
            '--', sys.executable, '-c', code], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = time.monotonic() + 3
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(marker.exists())
            proc.send_signal(signal.SIGTERM)
            self.assertEqual(proc.wait(timeout=5), 130)
            self.assertEqual(json.loads(self.flow.read_text())['steps'][0]['status'], 'failed')
        finally:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=5)


if __name__ == '__main__':
    unittest.main()
