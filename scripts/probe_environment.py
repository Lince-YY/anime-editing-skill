#!/usr/bin/env python3
"""Bounded, read-only host inventory. Python 3.9+, standard library only."""
import argparse
import csv
import datetime
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile

SCHEMA_VERSION = "1.0"
MODEL_MARKERS = {"anime2sketch": "test.py", "tooncomposer": "tooncomposer.py", "gpt_sovits": "GPT_SoVITS", "real_esrgan": "inference_realesrgan.py"}


def atomic_json(path, value):
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=str(target.parent), delete=False) as stream:
            temp = stream.name
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
        os.replace(temp, target)
    finally:
        if temp and os.path.exists(temp):
            os.unlink(temp)


def run_command(argv, timeout=8):
    """Never uses a shell; failure is unknown, absent executable is missing."""
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
        if result.returncode:
            return {"status": "unknown", "reason": "exit_code_%s" % result.returncode}
        return {"status": "found", "output": result.stdout[:262144]}
    except FileNotFoundError:
        return {"status": "missing", "reason": "executable_not_found"}
    except subprocess.TimeoutExpired:
        return {"status": "unknown", "reason": "timeout"}
    except (OSError, UnicodeError) as exc:
        return {"status": "unknown", "reason": type(exc).__name__}


def number(value):
    try:
        result = float(value)
        return result if result >= 0 and result < 1e18 else None
    except (ValueError, TypeError):
        return None


def parse_nvidia(output):
    gpus = []
    for row in csv.reader(output.splitlines()):
        if len(row) != 2:
            raise ValueError("unexpected NVIDIA query format")
        memory = number(row[1].strip())
        gpus.append({"vendor": "NVIDIA", "model": row[0].strip(), "memory_gb": round(memory / 1024, 2) if memory is not None else None,
                     "memory_kind": "dedicated", "kind": "discrete", "source": "nvidia-smi"})
    return gpus


def vendor_for(model):
    text = model.lower()
    for word, vendor in [("apple", "Apple"), ("nvidia", "NVIDIA"), ("amd", "AMD"), ("radeon", "AMD"), ("intel", "Intel")]:
        if word in text:
            return vendor
    return "unknown"


def parse_mac_displays(output, ram_gb):
    items = json.loads(output).get("SPDisplaysDataType", [])
    result = []
    for item in items:
        model = item.get("sppci_model", item.get("_name", "unknown"))
        vendor = vendor_for(model + " " + str(item.get("spdisplays_vendor", "")))
        unified = vendor == "Apple"
        text = str(item.get("spdisplays_vram", item.get("spdisplays_vram_shared", "")))
        match = re.search(r"([\d.]+)\s*(GB|MB)", text, re.I)
        mem = float(match.group(1)) / (1024 if match.group(2).upper() == "MB" else 1) if match else None
        result.append({"vendor": vendor, "model": model, "memory_gb": ram_gb if unified else mem,
                       "memory_kind": "unified" if unified else ("shared" if "spdisplays_vram_shared" in item else "dedicated" if mem is not None else "unknown"),
                       "kind": "integrated" if unified or vendor == "Intel" else "unknown", "source": "system_profiler"})
    return result


def parse_windows_host(output):
    obj = json.loads(output)
    return obj[0] if isinstance(obj, list) else obj


def probe_host(system, disk_path):
    host = {"os": system, "arch": platform.machine(), "cpu": platform.processor() or None, "ram_gb": None, "disk_free_gb": None}
    warnings = []
    try:
        host["disk_free_gb"] = round(shutil.disk_usage(disk_path).free / (1024 ** 3), 2)
    except OSError:
        warnings.append("disk_free_gb unknown: selected path unavailable")
    if system == "Darwin":
        for field, name in [("cpu", "machdep.cpu.brand_string"), ("ram_gb", "hw.memsize")]:
            r = run_command(["sysctl", "-n", name])
            if r["status"] == "found":
                if field == "cpu":
                    host[field] = r["output"].strip() or None
                else:
                    value = number(r["output"].strip())
                    host[field] = round(value / 1024 ** 3, 2) if value is not None else None
                    if value is None:
                        warnings.append("RAM response could not be parsed")
            else:
                warnings.append("%s unknown: %s" % (field, r.get("reason")))
        if host["ram_gb"] is None or host["cpu"] in (None, "arm", "i386"):
            r = run_command(["system_profiler", "SPHardwareDataType", "-json"], timeout=12)
            if r["status"] == "found":
                try:
                    # Retain only CPU and RAM, never host identifiers from this response.
                    item = json.loads(r["output"])["SPHardwareDataType"][0]
                    host["cpu"] = item.get("chip_type", item.get("cpu_type", host["cpu"]))
                    match = re.search(r"([\d.]+)\s*(GB|MB)", str(item.get("physical_memory", "")), re.I)
                    if match:
                        host["ram_gb"] = round(float(match.group(1)) / (1024 if match.group(2).upper() == "MB" else 1), 2)
                        warnings = [w for w in warnings if not w.startswith(("cpu unknown:", "ram_gb unknown:"))]
                        warnings.append("sysctl unavailable; CPU/RAM recovered through bounded system_profiler fallback")
                except (ValueError, KeyError, IndexError, TypeError):
                    warnings.append("macOS hardware fallback response could not be parsed")
    elif system == "Linux":
        try:
            text = Path("/proc/meminfo").read_text()
            match = re.search(r"^MemTotal:\s+(\d+) kB", text, re.M)
            host["ram_gb"] = round(int(match.group(1)) / 1024 ** 2, 2) if match else None
            cpu = Path("/proc/cpuinfo").read_text()
            match = re.search(r"^(?:model name|Hardware)\s*:\s*(.+)", cpu, re.M)
            if match:
                host["cpu"] = match.group(1).strip()
        except OSError:
            warnings.append("CPU/RAM details unknown: /proc unavailable")
    elif system == "Windows":
        r = run_command(["powershell", "-NoProfile", "-NonInteractive", "-Command", "$c=Get-CimInstance Win32_ComputerSystem; $p=Get-CimInstance Win32_Processor | Select-Object -First 1; @{cpu=$p.Name;ram_bytes=$c.TotalPhysicalMemory} | ConvertTo-Json -Compress"])
        if r["status"] == "found":
            try:
                obj = parse_windows_host(r["output"])
                host["cpu"] = obj.get("cpu")
                host["ram_gb"] = round(float(obj["ram_bytes"]) / 1024 ** 3, 2)
            except (ValueError, KeyError, TypeError):
                warnings.append("Windows CPU/RAM response could not be parsed")
        else:
            warnings.append("Windows CPU/RAM unknown: " + r.get("reason", "unknown"))
    else:
        warnings.append("Host OS has no specialized CPU/RAM probe")
    return host, warnings


def discover_editors(system):
    candidates = {"blender": ["blender"], "resolve": ["resolve"], "shotcut": ["shotcut"], "kdenlive": ["kdenlive"]}
    known = {
        "Darwin": {"blender": ["/Applications/Blender.app"], "resolve": ["/Applications/DaVinci Resolve/DaVinci Resolve.app"], "premiere": ["/Applications/Adobe Premiere Pro 2026/Adobe Premiere Pro 2026.app"], "shotcut": ["/Applications/Shotcut.app"], "kdenlive": ["/Applications/kdenlive.app"]},
        "Windows": {"blender": ["Blender Foundation/Blender 4.5/blender.exe"], "resolve": ["Blackmagic Design/DaVinci Resolve/Resolve.exe"], "shotcut": ["Shotcut/shotcut.exe"], "kdenlive": ["kdenlive/bin/kdenlive.exe"]},
        "Linux": {"resolve": ["/opt/resolve/bin/resolve"]}}
    results = {}
    for key in sorted(set(candidates) | set(known.get(system, {}))):
        path = next((shutil.which(cmd) for cmd in candidates.get(key, []) if shutil.which(cmd)), None)
        for candidate in known.get(system, {}).get(key, []):
            p = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / candidate if system == "Windows" else Path(candidate)
            if not path and p.exists():
                path = str(p)
        results[key] = {"status": "found" if path else "unknown", "path": path, "reason": "discovery_only_not_launched" if path else "not_found_in_PATH_or_known_locations; not_exhaustive"}
    return results


def probe_gpus(system, ram_gb, nvidia_tool):
    gpus, warnings = [], []
    detection = "unknown"
    if nvidia_tool["status"] == "found":
        r = run_command([nvidia_tool["path"], "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"])
        if r["status"] == "found":
            try:
                gpus = parse_nvidia(r["output"])
                detection = "partial"  # NVIDIA cannot enumerate other vendors.
            except ValueError:
                warnings.append("NVIDIA GPU query parse failure")
        else:
            warnings.append("NVIDIA GPU query unknown: " + r.get("reason", "unknown"))
    if system == "Darwin":
        r = run_command(["system_profiler", "SPDisplaysDataType", "-json"], timeout=12)
        if r["status"] == "found":
            try:
                gpus = parse_mac_displays(r["output"], ram_gb)
                detection = "reported"
            except (ValueError, TypeError):
                warnings.append("macOS GPU response parse failure")
        else:
            warnings.append("macOS GPU query unknown: " + r.get("reason", "unknown"))
    elif system == "Windows":
        r = run_command(["powershell", "-NoProfile", "-NonInteractive", "-Command", "@(Get-CimInstance Win32_VideoController | Select-Object Name,AdapterRAM) | ConvertTo-Json -Compress"])
        if r["status"] == "found":
            try:
                items = json.loads(r["output"])
                items = items if isinstance(items, list) else [items]
                for item in items:
                    model = item.get("Name", "unknown")
                    if any(model == gpu["model"] for gpu in gpus):
                        continue
                    gpus.append({"vendor": vendor_for(model), "model": model, "memory_gb": None, "memory_kind": "unknown", "kind": "unknown", "source": "Win32_VideoController"})
                detection = "reported"
                warnings.append("Windows AdapterRAM is not trusted for VRAM capacity; use vendor tooling")
            except (ValueError, AttributeError):
                warnings.append("Windows GPU response parse failure")
    elif system == "Linux":
        r = run_command(["lspci", "-mm"])
        if r["status"] == "found":
            for line in r["output"].splitlines():
                if not any(word in line for word in ("VGA compatible controller", "3D controller", "Display controller")):
                    continue
                model = line.strip()
                vendor = vendor_for(model)
                if vendor == "NVIDIA" and any(g["vendor"] == "NVIDIA" for g in gpus):
                    continue
                gpus.append({"vendor": vendor, "model": model, "memory_gb": None, "memory_kind": "unknown", "kind": "unknown", "source": "lspci"})
            detection = "reported"
    if detection == "unknown":
        warnings.append("GPU inventory unknown; missing GPU tools does not mean no GPU")
    return gpus, detection, warnings


def probe_backends(enabled):
    result = {"cpu": {"status": "available", "scope": "Python interpreter only; model performance untested"},
              "cuda": {"status": "not_checked"}, "mps": {"status": "not_checked"}, "torch": {"status": "not_checked"}}
    if not enabled:
        return result
    code = "import importlib.util,json; s=importlib.util.find_spec('torch'); print(json.dumps({'installed':False})) if s is None else None\nif s is not None:\n import torch\n print(json.dumps({'installed':True,'version':torch.__version__,'cuda':torch.cuda.is_available(),'mps':bool(hasattr(torch.backends,'mps') and torch.backends.mps.is_available())}))"
    r = run_command([sys.executable, "-c", code], timeout=15)
    if r["status"] != "found":
        for key in ("cuda", "mps", "torch"):
            result[key] = {"status": "unknown", "reason": r.get("reason", "unknown")}
        return result
    try:
        obj = json.loads(r["output"])
        result["torch"] = {"status": "available" if obj["installed"] else "unavailable", "version": obj.get("version")}
        for key in ("cuda", "mps"):
            result[key] = {"status": "available" if obj.get(key) else "unavailable", "scope": "torch availability; no model smoke test"}
    except (ValueError, KeyError):
        for key in ("cuda", "mps", "torch"):
            result[key] = {"status": "unknown", "reason": "parse_failure"}
    return result


def probe(disk_path=".", check_torch=False, tool_roots=None):
    system = platform.system()
    host, warnings = probe_host(system, disk_path)
    tools = {}
    for name, argv in {"python": [sys.executable, "--version"], "git": ["git", "--version"], "ffmpeg": ["ffmpeg", "-version"], "ffprobe": ["ffprobe", "-version"], "nvidia-smi": ["nvidia-smi", "--version"]}.items():
        path = sys.executable if name == "python" else shutil.which(name)
        r = run_command(argv) if path else {"status": "missing", "reason": "not_in_PATH"}
        tools[name] = {"status": r["status"], "path": path, "version": r.get("output", "").splitlines()[0] if r.get("output") else None, "reason": r.get("reason")}
    tools["video_editors"] = discover_editors(system)
    for name, marker in MODEL_MARKERS.items():
        root = (tool_roots or {}).get(name)
        tools[name] = {"status": "found" if root and (Path(root) / marker).exists() else "missing" if root else "unknown", "path": str(Path(root).resolve()) if root else None, "reason": "marker_only_not_imported_or_launched" if root else "no_explicit_tool_root"}
    gpus, detection, gpu_warnings = probe_gpus(system, host["ram_gb"], tools["nvidia-smi"])
    return {"schema_version": SCHEMA_VERSION, "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "host": host, "gpus": gpus, "gpu_detection": detection, "tools": tools, "backends": probe_backends(check_torch), "warnings": warnings + gpu_warnings}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    parser.add_argument("--disk-path", default=".", help="Measure free space on this path's filesystem")
    parser.add_argument("--check-torch", action="store_true", help="Import existing torch in a bounded subprocess; no installation")
    parser.add_argument("--tool-root", action="append", default=[], metavar="ID=PATH", help="Explicit existing model repository path; marker check only")
    args = parser.parse_args()
    roots = {}
    for item in args.tool_root:
        key, sep, value = item.partition("=")
        if not sep or key not in MODEL_MARKERS or not value:
            parser.error("--tool-root must be one of %s=PATH" % ",".join(MODEL_MARKERS))
        roots[key] = value
    report = probe(args.disk_path, args.check_torch, roots)
    atomic_json(args.out, report)
    print("Environment: %s %s; RAM=%s GiB; GPU records=%s (%s); warnings=%s. Saved: %s" % (report["host"]["os"], report["host"]["arch"], report["host"]["ram_gb"], len(report["gpus"]), report["gpu_detection"], len(report["warnings"]), args.out))


if __name__ == "__main__":
    main()
