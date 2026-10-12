"""Behavior tests: fixtures exercise control boundaries, not model effectiveness."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "smoke_test.py"
spec = importlib.util.spec_from_file_location("smoke_test", SCRIPT)
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class SmokeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.logs = self.root / "logs"
        self.logs.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def case(self, code, **updates):
        if os.name != "posix":
            self.skipTest("bounded model-case cleanup currently supports POSIX only")
        data = {"command": [sys.executable, "-c", code], "cwd": str(self.root),
                "timeout_seconds": 5, "outputs": [{"path": "result.bin", "type": "file", "min_bytes": 3}]}
        data.update(updates)
        path = self.root / "case.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return smoke.case_check(path, None, None, self.logs, "cpu")

    def test_success_creates_new_artifact_and_keeps_raw_log_out_of_report(self):
        result = self.case("from pathlib import Path; print('SECRET_FIXTURE'); Path('result.bin').write_bytes(b'new')")
        self.assertEqual(result["status"], "passed")
        self.assertFalse(result["details"]["effect_acceptance"])
        self.assertNotIn("SECRET_FIXTURE", json.dumps(result))
        self.assertIn("SECRET_FIXTURE", (self.logs / "case.stdout.log").read_text())

    def test_existing_artifact_blocks_command_before_execution(self):
        (self.root / "result.bin").write_bytes(b"old")
        result = self.case("from pathlib import Path; Path('marker').touch(); Path('result.bin').write_bytes(b'new')")
        self.assertEqual(result["details"]["reason"], "output_already_exists")
        self.assertFalse((self.root / "marker").exists())
        self.assertEqual((self.root / "result.bin").read_bytes(), b"old")

    def test_nonzero_exit_fails_even_with_output(self):
        result = self.case("from pathlib import Path; Path('result.bin').write_bytes(b'new'); raise SystemExit(7)")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["details"]["execution"]["returncode"], 7)

    def test_timeout_is_bounded(self):
        result = self.case("import time; time.sleep(60)", timeout_seconds=0.1)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["details"]["execution"]["timed_out"])
        self.assertLess(result["details"]["execution"]["elapsed_seconds"], 5)

    @unittest.skipUnless(os.name == "posix", "POSIX process-group cleanup")
    def test_timeout_also_terminates_child(self):
        result = self.case("import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', \"import time; from pathlib import Path; time.sleep(0.7); Path('escaped').touch()\"]); time.sleep(60)", timeout_seconds=0.1)
        self.assertTrue(result["details"]["execution"]["timed_out"])
        # A separate bounded wait is only test evidence; tool itself has no polling daemon.
        subprocess.run([sys.executable, "-c", "import time; time.sleep(1)"], check=True, timeout=3)
        self.assertFalse((self.root / "escaped").exists())

    def test_missing_output_is_failure(self):
        result = self.case("pass")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["details"]["outputs"][0]["reason"], "output_missing_or_not_regular_file")

    def test_missing_media_tools_is_unknown_not_passed(self):
        result = self.case("from pathlib import Path; Path('result.bin').write_bytes(b'new')", outputs=[{"path": "result.bin", "type": "video"}])
        self.assertEqual(result["status"], "unknown")

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "existing FFmpeg tools unavailable")
    def test_corrupt_new_video_cannot_pass_decode_gate(self):
        if os.name != "posix":
            self.skipTest("POSIX case execution")
        data = {"command": [sys.executable, "-c", "from pathlib import Path; Path('bad.mp4').write_bytes(b'not video')"],
                "cwd": str(self.root), "outputs": [{"path": "bad.mp4", "type": "video"}]}
        path = self.root / "case.json"
        path.write_text(json.dumps(data))
        result = smoke.case_check(path, shutil.which("ffmpeg"), shutil.which("ffprobe"), self.logs, "cpu")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["details"]["outputs"][0]["reason"], "probe_failed")

    def test_missing_dependencies_are_not_passed(self):
        self.assertEqual(smoke.ffmpeg_check(None, None, self.root, self.logs)["status"], "missing")
        self.assertEqual(smoke.torch_check(None, "cpu", self.root, self.logs)["status"], "missing")

    def test_invalid_case_does_not_execute(self):
        for invalid in ({"command": "echo x"}, {"timeout_seconds": 301}, {"timeout_seconds": float("nan")}):
            result = self.case("from pathlib import Path; Path('marker').touch()", **invalid)
            self.assertEqual(result["details"]["reason"], "invalid_case")
            self.assertFalse((self.root / "marker").exists())

    def test_cli_emits_shared_schema_and_nonzero_for_missing(self):
        out = self.root / "report.json"
        process = subprocess.run([sys.executable, str(SCRIPT), "--out", str(out), "--checks", "ffmpeg",
                                  "--ffmpeg", str(self.root / "absent"), "--ffprobe", str(self.root / "absent")],
                                 capture_output=True, text=True, timeout=10)
        self.assertEqual(process.returncode, 1)
        report = json.loads(out.read_text())
        self.assertEqual(report["overall"], "missing")
        self.assertEqual(set(("schema_version", "generated_at", "checks", "overall")) - set(report), set())
        self.assertEqual(report["checks"][0]["scope"], "synthetic_media_smoke")

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "existing FFmpeg tools unavailable")
    def test_real_ffmpeg_synthetic_encode_and_decode(self):
        result = smoke.ffmpeg_check(shutil.which("ffmpeg"), shutil.which("ffprobe"), self.root, self.logs)
        self.assertEqual(result["status"], "passed", json.dumps(result))
        self.assertEqual(result["details"]["outputs"][0]["media"]["codec"], "ffv1")
        self.assertEqual(result["details"]["outputs"][1]["media"]["codec"], "pcm_s16le")


if __name__ == "__main__":
    unittest.main()
