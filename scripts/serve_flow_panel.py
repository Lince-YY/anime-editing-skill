#!/usr/bin/env python3
"""Serve one explicit flow on loopback; push validated changes with SSE. No execution API."""
import argparse
import copy
import hashlib
import json
import mimetypes
import os
import re
import secrets
import signal
import threading
from collections import OrderedDict
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from build_flow_panel import validate

TEMPLATES = Path(__file__).resolve().parents[1] / 'assets' / 'flow-panel'
MAX_JSON_BYTES = 8 * 1024 * 1024


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


class FlowState:
    def __init__(self, path, interval=1.0):
        self.path = Path(path).resolve()
        self.interval = interval
        self.condition = threading.Condition()
        self.stop = threading.Event()
        self.revision = 0
        self.payload = None
        self.error = None
        self.media = OrderedDict()
        self.signature = None
        self.updated_at = None
        self.instance_id = secrets.token_hex(12)
        self.refresh(strict=True)
        self.watcher = threading.Thread(target=self.watch, daemon=True)
        self.watcher.start()

    def refresh(self, strict=False):
        try:
            if self.path.stat().st_size > MAX_JSON_BYTES:
                raise ValueError('flow.json exceeds size limit')
            raw = self.path.read_bytes()
            data = json.loads(raw)
            refs = validate(data, self.path.parent)
            fingerprints = [(key, field, source, source.stat()) for key, field, source in refs]
            signature = hashlib.sha256(raw + repr([(str(p), s.st_mtime_ns, s.st_size)
                for _, _, p, s in fingerprints]).encode()).hexdigest()
            with self.condition:
                if signature == self.signature and not self.error:
                    return
            payload = copy.deepcopy(data)
            media = OrderedDict()
            for key, field, source, stat in fingerprints:
                fingerprint = (stat.st_mtime_ns, stat.st_size)
                ident = hashlib.sha256((str(source) + repr(fingerprint)).encode()).hexdigest()
                url = 'media/' + ident + source.suffix.lower()
                payload['assets'][key][field] = url
                media[url] = (source, fingerprint)
            with self.condition:
                self.payload = payload
                self.signature = signature
                self.error = None
                self.media.update(media)
                for url in media:
                    self.media.move_to_end(url)
                # Retain a bounded number of recently referenced files for open players.
                while len(self.media) > max(256, len(media)):
                    self.media.popitem(last=False)
                self.revision += 1
                self.updated_at = utc_now()
                self.condition.notify_all()
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            if strict:
                raise ValueError('Cannot load initial flow: check JSON and referenced media') from exc
            # Keep the previous snapshot and never transmit exception paths or raw logs.
            error = '进度文件或引用素材暂不可用；保留上一次有效记录，修复后自动恢复。'
            with self.condition:
                if error != self.error:
                    self.error = error
                    self.revision += 1
                    self.condition.notify_all()

    def watch(self):
        while not self.stop.wait(self.interval):
            self.refresh()

    def snapshot(self):
        with self.condition:
            return {'revision': self.revision, 'instance_id': self.instance_id, 'updated_at': self.updated_at,
                    'error': self.error, 'data': self.payload}

    def close(self):
        self.stop.set()
        with self.condition:
            self.condition.notify_all()
        self.watcher.join(timeout=3)


class PanelServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, state, port=0, token=None):
        self.state = state
        self.token = token or secrets.token_urlsafe(24)
        super().__init__(('127.0.0.1', port), PanelHandler)
        self.origin = 'http://127.0.0.1:%s' % self.server_address[1]
        self.url = self.origin + '/' + self.token + '/'


class PanelHandler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *_args):
        pass

    def route(self):
        expected_host = '127.0.0.1:%s' % self.server.server_address[1]
        if self.headers.get('Host') != expected_host:
            self.send_error(403)
            return None
        origin = self.headers.get('Origin')
        if origin and origin != self.server.origin:
            self.send_error(403)
            return None
        if self.headers.get('Sec-Fetch-Site') == 'cross-site':
            self.send_error(403)
            return None
        path = urlsplit(self.path).path
        prefix = '/' + self.server.token + '/'
        if not path.startswith(prefix):
            self.send_error(404)
            return None
        return path[len(prefix):]

    def common_headers(self):
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self'; media-src 'self'; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'")

    def send_bytes(self, content, mime, head=False):
        self.send_response(200)
        self.common_headers()
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(content)))
        self.end_headers()
        if not head:
            self.wfile.write(content)

    def do_HEAD(self):
        self.handle_get(head=True)

    def do_GET(self):
        self.handle_get()

    def handle_get(self, head=False):
        route = self.route()
        if route is None:
            return
        try:
            if route in ('', 'index.html', 'app.js', 'styles.css'):
                name = route or 'index.html'
                mime = {'index.html': 'text/html', 'app.js': 'application/javascript', 'styles.css': 'text/css'}[name]
                self.send_bytes((TEMPLATES / name).read_bytes(), mime + '; charset=utf-8', head)
            elif route == 'data.js':
                snapshot = self.server.state.snapshot()
                payload = json.dumps(snapshot['data'], ensure_ascii=False).replace('<', '\\u003c')
                config = json.dumps({'events': './events', 'snapshot': './snapshot',
                                     'revision': snapshot['revision'], 'updated_at': snapshot['updated_at']})
                self.send_bytes(('window.FLOW_DATA=' + payload + ';\nwindow.FLOW_LIVE=' + config + ';\n').encode(), 'application/javascript; charset=utf-8', head)
            elif route == 'snapshot':
                self.send_bytes(json.dumps(self.server.state.snapshot(), ensure_ascii=False).encode(), 'application/json; charset=utf-8', head)
            elif route == 'events' and not head:
                self.events()
            elif route.startswith('media/'):
                self.send_media(route, head)
            else:
                self.send_error(404)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            self.close_connection = True

    def events(self):
        self.connection.settimeout(20)
        self.send_response(200)
        self.common_headers()
        self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(b'retry: 1500\n\n')
        self.wfile.flush()
        version = -1
        state = self.server.state
        while not state.stop.is_set():
            snapshot = state.snapshot()
            if snapshot['revision'] != version:
                version = snapshot['revision']
                message = 'id: %s\nevent: snapshot\ndata: %s\n\n' % (version, json.dumps(snapshot, ensure_ascii=False))
            else:
                message = 'event: heartbeat\ndata: {}\n\n'
            self.wfile.write(message.encode())
            self.wfile.flush()
            with state.condition:
                if state.revision == version:
                    state.condition.wait(timeout=5)
        self.close_connection = True

    def send_media(self, route, head=False):
        with self.server.state.condition:
            record = self.server.state.media.get(route)
        if record is None:
            self.send_error(404)
            return
        path, fingerprint = record
        try:
            # Open the resolved allowlisted path, then check this exact file descriptor.
            with path.open('rb') as stream:
                import os
                stat = os.fstat(stream.fileno())
                if (stat.st_mtime_ns, stat.st_size) != fingerprint:
                    self.send_error(409, 'Media changed; waiting for updated record')
                    return
                size = stat.st_size
                start, end, status = 0, size - 1, 200
                value = self.headers.get('Range')
                if value:
                    match = re.fullmatch(r'bytes=(\d*)-(\d*)', value)
                    if not match or not any(match.groups()) or not size:
                        self.send_error(416)
                        return
                    left, right = match.groups()
                    if left:
                        start = int(left)
                        end = min(int(right), size - 1) if right else size - 1
                    else:
                        start = max(0, size - int(right))
                    if start > end or start >= size:
                        self.send_error(416)
                        return
                    status = 206
                self.send_response(status)
                self.common_headers()
                self.send_header('Content-Type', mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
                self.send_header('Accept-Ranges', 'bytes')
                self.send_header('Content-Length', str(max(0, end - start + 1)))
                if status == 206:
                    self.send_header('Content-Range', 'bytes %s-%s/%s' % (start, end, size))
                self.end_headers()
                if not head:
                    stream.seek(start)
                    remaining = end - start + 1
                    while remaining > 0:
                        block = stream.read(min(65536, remaining))
                        if not block:
                            break
                        self.wfile.write(block)
                        remaining -= len(block)
        except OSError:
            self.close_connection = True


def session_options(path, data, port):
    if path is None or not path.exists():
        return port, None
    if path.stat().st_size > 4096:
        raise ValueError('Invalid local session file')
    session = json.loads(path.read_text(encoding='utf-8'))
    token, saved_port = session.get('token'), session.get('port')
    if (session.get('data') != str(data.resolve()) or not isinstance(token, str)
            or not re.fullmatch(r'[A-Za-z0-9_-]{32,64}', token)
            or type(saved_port) is not int or not 1 <= saved_port <= 65535):
        raise ValueError('Session belongs to another flow or has invalid fields')
    if port not in (0, saved_port):
        raise ValueError('Requested port differs from the saved session')
    return saved_port, token


def save_session(path, server):
    if path is None or path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation protects another service's resume record.
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
        json.dump({'data': str(server.state.path), 'port': server.server_address[1],
                   'token': server.token}, stream)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--port', type=int, default=0, help='0 chooses a free loopback port')
    parser.add_argument('--interval', type=float, default=1.0)
    parser.add_argument('--session-file', type=Path, help='Private local resume record; reuse it to preserve the URL after restart')
    args = parser.parse_args()
    if not 0 <= args.port <= 65535 or not 0.2 <= args.interval <= 30:
        parser.error('port must be 0..65535; interval must be 0.2..30 seconds')
    state = None
    server = None
    try:
        port, token = session_options(args.session_file, args.data, args.port)
        state = FlowState(args.data, args.interval)
        server = PanelServer(state, port, token)
        save_session(args.session_file, server)
        print(json.dumps({'url': server.url, 'pid': __import__('os').getpid(),
                          'mode': 'live', 'stop': 'Ctrl+C; snapshots and media remain on disk'}), flush=True)
        signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    except (OSError, ValueError) as exc:
        parser.exit(2, 'panel server: %s\n' % exc)
    finally:
        if state:
            state.close()
        if server:
            server.server_close()


if __name__ == '__main__':
    main()
