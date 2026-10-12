#!/usr/bin/env python3
"""Bounded local smoke checks; does not install software or load model weights."""
import argparse
import datetime as dt
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time

SCHEMA_VERSION = "1.0"
MAX_TIMEOUT = 300


def executable(value):
    found = shutil.which(value)
    return str(Path(found).resolve()) if found else None


def run(argv, cwd, timeout, logs, label):
    """Keep raw output on disk, terminate the owned process group on timeout."""
    stdout = logs / (label + ".stdout.log")
    stderr = logs / (label + ".stderr.log")
    started = time.monotonic()
    timed_out = False
    with stdout.open("wb") as out, stderr.open("wb") as err:
        try:
            process = subprocess.Popen(argv, cwd=str(cwd), stdout=out, stderr=err,
                                       shell=False, start_new_session=(os.name == "posix"))
        except OSError:
            return {"returncode": None, "timed_out": False, "launch_error": True,
                    "stdout_log": str(stdout), "stderr_log": str(stderr)}
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
        finally:
            # Also remove descendants left behind by a command that already exited.
            if os.name == "posix":
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                if timed_out:
                    try:
                        process.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        pass
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            elif process.poll() is None:
                process.kill()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                return {"returncode": None, "timed_out": timed_out, "cleanup_failed": True,
                        "stdout_log": str(stdout), "stderr_log": str(stderr)}
    return {"returncode": process.returncode, "timed_out": timed_out,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "stdout_log": str(stdout), "stderr_log": str(stderr)}


def ok_run(result):
    return result.get("returncode") == 0 and not result.get("timed_out") and not result.get("cleanup_failed")


def tail_json(path):
    with Path(path).open("rb") as handle:
        handle.seek(0, 2)
        handle.seek(max(0, handle.tell() - 65536))
        raw = handle.read().decode("utf-8", "replace")
    return json.loads(raw)


def check(name, status, scope, backend=None, **details):
    return {"name": name, "status": status, "scope": scope, "backend": backend,
            "details": details}


def verify_output(spec, path, ffmpeg, ffprobe, logs, label):
    if not path.is_file() or path.is_symlink():
        return False, {"reason": "output_missing_or_not_regular_file", "path": str(path)}
    size = path.stat().st_size
    if size < spec.get("min_bytes", 1):
        return False, {"reason": "output_too_small", "path": str(path), "bytes": size}
    kind = spec["type"]
    details = {"path": str(path), "type": kind, "bytes": size}
    if kind == "file":
        details["validation"] = "existence_and_size_only"
        return True, details
    if not ffmpeg or not ffprobe:
        details["reason"] = "media_validation_tools_missing"
        return None, details
    probe = run([ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                path.parent, 20, logs, label + "-probe")
    details["probe"] = probe
    if not ok_run(probe):
        details["reason"] = "probe_failed"
        return False, details
    try:
        data = tail_json(probe["stdout_log"])
        streams = data.get("streams", [])
        if kind == "image":
            formats = set(data.get("format", {}).get("format_name", "").split(","))
            if not formats.intersection({"image2", "image2pipe", "gif", "ico"}) and not any(f.endswith("_pipe") for f in formats):
                raise ValueError("expected image container")
        expected = "audio" if kind == "audio" else "video"
        stream = next(s for s in streams if s.get("codec_type") == expected)
        duration = float(data.get("format", {}).get("duration", stream.get("duration", 0)))
        if not stream.get("codec_name") or (kind != "image" and (not math.isfinite(duration) or duration <= 0)):
            raise ValueError("invalid codec or duration")
        if kind in ("video", "image") and (int(stream.get("width", 0)) <= 0 or int(stream.get("height", 0)) <= 0):
            raise ValueError("invalid image geometry")
        if kind == "audio" and (int(stream.get("sample_rate", 0)) <= 0 or int(stream.get("channels", 0)) <= 0):
            raise ValueError("invalid audio geometry")
        actual = {"codec": stream["codec_name"], "duration_seconds": duration}
        for key in ("width", "height", "sample_rate", "channels"):
            if key in stream:
                actual[key] = int(stream[key])
        details["media"] = actual
        for key in ("width", "height", "sample_rate", "channels"):
            if key in spec and actual.get(key) != spec[key]:
                raise ValueError("media constraint mismatch")
        if "codec" in spec and spec["codec"] != actual["codec"]:
            raise ValueError("codec mismatch")
        if duration < spec.get("min_duration_seconds", 0) or duration > spec.get("max_duration_seconds", float("inf")):
            raise ValueError("duration mismatch")
    except (ValueError, TypeError, KeyError, StopIteration, json.JSONDecodeError):
        details["reason"] = "invalid_media_or_constraint_mismatch"
        return False, details
    decode = run([ffmpeg, "-nostdin", "-v", "error", "-xerror", "-i", str(path),
                  "-map", "0:" + expected[0], "-f", "null", "-"], path.parent, 20, logs, label + "-decode")
    details["decode"] = decode
    if not ok_run(decode):
        details["reason"] = "decode_failed"
        return False, details
    details["validation"] = "probe_and_full_decode"
    return True, details


def ffmpeg_check(ffmpeg, ffprobe, work, logs):
    if not ffmpeg or not ffprobe:
        return check("ffmpeg", "missing", "synthetic_media_smoke", missing_tools=[n for n, v in (("ffmpeg", ffmpeg), ("ffprobe", ffprobe)) if not v])
    path = work / "synthetic-smoke.mkv"
    result = run([ffmpeg, "-nostdin", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=64x64:r=10:d=0.4",
                  "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000:duration=0.4", "-t", "0.4",
                  "-c:v", "ffv1", "-c:a", "pcm_s16le", "-n", str(path)], work, 20, logs, "ffmpeg-encode")
    if not ok_run(result):
        return check("ffmpeg", "failed", "synthetic_media_smoke", reason="synthetic_encode_failed", execution=result)
    video_ok, video = verify_output({"type": "video", "codec": "ffv1", "width": 64, "height": 64,
                                   "min_duration_seconds": 0.3, "max_duration_seconds": 0.8}, path, ffmpeg, ffprobe, logs, "ffmpeg-video")
    audio_ok, audio = verify_output({"type": "audio", "codec": "pcm_s16le", "sample_rate": 16000,
                                   "min_duration_seconds": 0.3, "max_duration_seconds": 0.8}, path, ffmpeg, ffprobe, logs, "ffmpeg-audio")
    return check("ffmpeg", "passed" if video_ok and audio_ok else "failed", "synthetic_media_smoke",
                 execution=result, outputs=[video, audio], effect_acceptance=False)


TORCH_PROBE = r'''
import json, sys
try:
    import torch
except ModuleNotFoundError as e:
    if e.name == "torch":
        print(json.dumps({"status":"missing", "reason":"torch_not_installed"})); sys.exit(0)
    raise
requested = sys.argv[1]
available = {"cpu": True, "cuda": bool(torch.cuda.is_available()),
             "mps": bool(hasattr(torch.backends, "mps") and torch.backends.mps.is_available())}
backend = next((b for b in ("cuda", "mps", "cpu") if available[b]), "cpu") if requested == "auto" else requested
if not available[backend]:
    print(json.dumps({"status":"failed", "reason":"selected_backend_unavailable", "backend":backend, "available":available})); sys.exit(0)
x = torch.tensor([1., 2., 3.], device=backend)
value = float((x * x).sum().cpu().item())
print(json.dumps({"status":"passed" if value == 14.0 else "failed", "backend":backend,
                  "available":available, "torch_version":str(torch.__version__), "result":value}))
'''


def torch_check(python, backend, work, logs):
    if not python:
        return check("torch", "missing", "tensor_smoke", backend, reason="python_executable_missing")
    result = run([python, "-c", TORCH_PROBE, backend], work, 30, logs, "torch")
    if not ok_run(result):
        return check("torch", "failed", "tensor_smoke", backend, reason="import_or_tensor_execution_failed", execution=result, model_verified=False)
    try:
        data = tail_json(result["stdout_log"])
        status = data.pop("status")
        chosen = data.pop("backend", backend)
        if status not in ("passed", "missing", "failed"):
            raise ValueError("invalid status")
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return check("torch", "unknown", "tensor_smoke", backend, reason="probe_result_unreadable", execution=result, model_verified=False)
    return check("torch", status, "tensor_smoke", chosen, execution=result, model_verified=False, **data)


def read_case(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("case must be an object")
    command = data.get("command")
    if not isinstance(command, list) or not command or not all(isinstance(a, str) and a and "\x00" not in a for a in command):
        raise ValueError("command must be a nonempty argv array of strings")
    cwd_value = data.get("cwd", ".")
    if not isinstance(cwd_value, str):
        raise ValueError("cwd must be a string")
    cwd = (path.parent / cwd_value).resolve()
    if not cwd.is_dir():
        raise ValueError("cwd must exist")
    timeout = data.get("timeout_seconds", 60)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= MAX_TIMEOUT:
        raise ValueError("timeout_seconds must be in (0, 300]")
    outputs = data.get("outputs")
    if not isinstance(outputs, list) or not 1 <= len(outputs) <= 16:
        raise ValueError("outputs must contain 1 to 16 entries")
    seen = set()
    for spec in outputs:
        if not isinstance(spec, dict) or not isinstance(spec.get("path"), str) or not spec["path"] or spec.get("type") not in ("video", "audio", "image", "file"):
            raise ValueError("each output needs path and type video/audio/image/file")
        resolved = (cwd / spec["path"]).resolve()
        if resolved in seen:
            raise ValueError("duplicate output path")
        seen.add(resolved)
        for key in ("min_bytes", "width", "height", "sample_rate", "channels"):
            if key in spec and (isinstance(spec[key], bool) or not isinstance(spec[key], int) or spec[key] <= 0):
                raise ValueError(key + " must be a positive integer")
        for key in ("min_duration_seconds", "max_duration_seconds"):
            if key in spec and (isinstance(spec[key], bool) or not isinstance(spec[key], (int, float)) or not math.isfinite(spec[key]) or spec[key] < 0):
                raise ValueError(key + " must be finite and nonnegative")
        if "codec" in spec and not isinstance(spec["codec"], str):
            raise ValueError("codec must be a string")
    return data, cwd, timeout


def case_check(case_path, ffmpeg, ffprobe, logs, backend):
    if os.name != "posix":
        return check("case", "unknown", "user_model_case", backend,
                     reason="bounded_process_tree_cleanup_not_supported", effect_acceptance=False)
    try:
        data, cwd, timeout = read_case(case_path)
    except (OSError, ValueError, TypeError):
        return check("case", "failed", "user_model_case", backend, reason="invalid_case", effect_acceptance=False)
    paths = [(cwd / spec["path"]).absolute() for spec in data["outputs"]]
    # Never replace or accept a previous artifact, even if the command would overwrite it.
    if any(p.exists() or p.is_symlink() for p in paths):
        return check("case", "failed", "user_model_case", backend, reason="output_already_exists", effect_acceptance=False)
    result = run(data["command"], cwd, timeout, logs, "case")
    if not ok_run(result):
        return check("case", "failed", "user_model_case", backend, reason="case_execution_failed", execution=result, effect_acceptance=False)
    outputs = []
    status = "passed"
    for index, (spec, path) in enumerate(zip(data["outputs"], paths)):
        valid, detail = verify_output(spec, path, ffmpeg, ffprobe, logs, "case-output-%d" % index)
        outputs.append(detail)
        if valid is False:
            status = "failed"
        elif valid is None and status != "failed":
            status = "unknown"
    return check("case", status, "user_model_case", backend, execution=result, outputs=outputs,
                 model_identity="user_declared_unverified", backend_verified=False, effect_acceptance=False)


def overall(checks):
    statuses = {c["status"] for c in checks}
    for status in ("failed", "unknown", "missing"):
        if status in statuses:
            return status
    return "passed" if "passed" in statuses else "skipped"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--checks", help="comma-separated ffmpeg,torch,case; defaults to ffmpeg,torch plus supplied case")
    parser.add_argument("--python", default=sys.executable, help="existing Python interpreter")
    parser.add_argument("--backend", choices=("auto", "cpu", "cuda", "mps"), default="auto")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument("--case", type=Path, help="explicit user-provided executable case JSON")
    args = parser.parse_args(argv)
    names = args.checks.split(",") if args.checks is not None else ["ffmpeg", "torch"] + (["case"] if args.case else [])
    names = [n.strip() for n in names]
    if not names or any(n not in ("ffmpeg", "torch", "case") for n in names) or len(set(names)) != len(names):
        parser.error("--checks must list unique names from ffmpeg,torch,case")
    out = args.out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    # Preserve unique evidence directories across repeated reports.
    work = Path(tempfile.mkdtemp(prefix=out.stem + "-evidence-", dir=str(out.parent)))
    logs = work / "logs"
    logs.mkdir()
    ffmpeg, ffprobe = executable(args.ffmpeg), executable(args.ffprobe)
    results = []
    for name in names:
        if name == "ffmpeg":
            result = ffmpeg_check(ffmpeg, ffprobe, work, logs)
        elif name == "torch":
            result = torch_check(executable(args.python), args.backend, work, logs)
        elif args.case is None:
            result = check("case", "skipped", "user_model_case", args.backend, reason="no_user_case_supplied", effect_acceptance=False)
        else:
            result = case_check(args.case.resolve(), ffmpeg, ffprobe, logs, args.backend)
        results.append(result)
    report = {"schema_version": SCHEMA_VERSION, "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
              "checks": results, "overall": overall(results), "evidence_dir": str(work)}
    temp = out.with_name(out.name + ".tmp")
    temp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(out)
    print(json.dumps({"report": str(out), "overall": report["overall"]}, ensure_ascii=False))
    return 0 if report["overall"] in ("passed", "skipped") else 1


if __name__ == "__main__":
    sys.exit(main())
