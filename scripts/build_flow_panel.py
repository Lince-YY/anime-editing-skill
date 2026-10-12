#!/usr/bin/env python3
"""Build an offline case panel from explicit local JSON/media, without running models."""
import argparse
import copy
import hashlib
import json
import math
import re
import shutil
import tempfile
from pathlib import Path

PLACES = {"local", "cloud", "service", "hybrid"}
STATES = {"planned", "running", "ready", "accepted", "missing", "failed"}
TYPES = {"image", "video", "audio"}
ID = re.compile(r"^[A-Za-z0-9_-]+$")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate(data, base):
    require(isinstance(data, dict), 'flow must be an object')
    steps = data.get("steps", [])
    require(isinstance(steps, list) and steps, "steps must be a non-empty list")
    require(all(isinstance(s, dict) for s in steps), 'steps must contain objects')
    require([s.get("id") for s in steps] == list(range(1, len(steps) + 1)),
            "step IDs must be consecutive integers starting at 1")
    assets = data.get("assets", {})
    require(isinstance(assets, dict), "assets must be an object")
    refs = []
    for key, asset in assets.items():
        require(bool(ID.fullmatch(key)), f"Invalid asset ID: {key}")
        require(asset.get("id") == key, f"Asset ID/key mismatch: {key}")
        require(asset.get("type") in TYPES, f"Unsupported media type: {key}")
        if not asset.get("src"):
            require(asset.get("status") in {"planned", "running", "missing", "failed"},
                    f"Missing media must have an explicit incomplete status: {key}")
        for field in ("src", "original_src"):
            if not asset.get(field):
                continue
            value = asset[field]
            require(isinstance(value, str) and "://" not in value and not value.startswith("data:"),
                    f"Use an explicit local file, not a remote/data URL: {key}.{field}")
            source = Path(value).expanduser()
            source = (source if source.is_absolute() else base / source).resolve()
            require(source.is_file(), f"Missing file: {source}")
            require(bool(re.fullmatch(r"\.[A-Za-z0-9]{1,10}", source.suffix)),
                    f"Media file needs a conventional extension: {source}")
            refs.append((key, field, source))
    for step in steps:
        require(step.get("status") in STATES, f"Explicit status required for step {step['id']}")
        if 'progress' in step:
            value = step['progress']
            require(type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 100,
                    'progress must be a finite number in 0..100')
        if 'message' in step:
            require(isinstance(step['message'], str), 'message must be text')
        for field in ("title", "environment", "input", "action", "output"):
            require(isinstance(step.get(field), str) and step[field].strip(),
                    f"Step {step['id']} needs {field}")
        require(isinstance(step.get("tools", []), list), "tools must be a list")
        for key in step.get("media", []):
            require(key in assets, f"Unknown step media: {key}")
    chart = data.get("chart", {})
    lanes, nodes = chart.get("lanes", []), chart.get("nodes", [])
    require(lanes and nodes, "chart needs lanes and nodes")
    for lane in lanes:
        require(lane.get("place") in PLACES and lane.get("name"), "Invalid tool lane")
    ids, cells = set(), set()
    for node in nodes:
        nid = node.get("id", "")
        require(bool(ID.fullmatch(nid)) and nid not in ids, f"Invalid/duplicate node ID: {nid}")
        ids.add(nid)
        require(type(node.get("row")) is int and 0 <= node["row"] < len(lanes), f"Invalid row: {nid}")
        require(type(node.get("step")) is int and 1 <= node["step"] <= len(steps), f"Invalid step: {nid}")
        require(node.get("place") in PLACES, f"Invalid execution place: {nid}")
        cell = (node["row"], node["step"])
        require(cell not in cells, f"Duplicate grid cell {cell}; combine the node or add a tool row")
        cells.add(cell)
        for field in ("asset", "poster"):
            if node.get(field):
                require(node[field] in assets, f"Unknown node {field}: {nid}")
        if node.get("poster"):
            require(assets[node["poster"]]["type"] == "image", f"Poster must be an image: {nid}")
        require(not node.get("customImage") and not node.get("customPoster"),
                "Use asset/poster IDs so all media is packaged")
    for link in chart.get("links", []):
        require(len(link) == 2 and all(n in ids for n in link), f"Broken link: {link}")
    step_ids = set(range(1, len(steps) + 1))
    final = data.get("meta", {}).get("final_step")
    revision = data.get('meta', {}).get('revision', 0)
    require(type(revision) is int and revision >= 0, 'revision must be a nonnegative integer')
    require(final is None or final in step_ids, "Unknown final_step")
    for row in data.get("runtime", []):
        require(row.get("id") in step_ids, "Runtime references an unknown step")
    for group in data.get("runtime_groups", []):
        require(group.get("place") in PLACES and set(group.get("ids", [])).issubset(step_ids),
                "Invalid runtime group")
    for item in data.get("handoff", {}).get("items", []):
        require(item.get("step") in step_ids and item.get("place") in PLACES, "Invalid handoff")
    return refs


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--check", action="store_true", help="Validate and report media size without writing")
    args = parser.parse_args()
    try:
        data_path = args.data.resolve()
        data = json.loads(data_path.read_text(encoding="utf-8"))
        refs = validate(data, data_path.parent)
        unique = {source for _, _, source in refs}
        report = {"steps": len(data["steps"]), "tool_rows": len(data["chart"]["lanes"]),
                  "source_files": len(unique), "media_bytes": sum(p.stat().st_size for p in unique)}
        if args.check:
            print(json.dumps(report, ensure_ascii=False))
            return
        require(args.out is not None, "--out is required unless --check is used")
        out = args.out.resolve()
        require(not out.exists(), "Output already exists; use a new version directory")
        out.parent.mkdir(parents=True, exist_ok=True)
        template = Path(__file__).resolve().parents[1] / "assets" / "flow-panel"
        payload = copy.deepcopy(data)
        temporary = Path(tempfile.mkdtemp(prefix=".flow-build-", dir=out.parent))
        try:
            (temporary / "media").mkdir()
            copied, hashes = {}, {}
            for key, field, source in refs:
                if source not in copied:
                    digest = sha256(source)
                    destination = "media/" + digest + source.suffix.lower()
                    target = temporary / destination
                    if not target.exists():
                        shutil.copy2(source, target)
                    require(sha256(target) == digest, f"Media copy verification failed: {source.name}")
                    copied[source] = destination
                    hashes[destination] = {"sha256": digest, "bytes": target.stat().st_size}
                payload["assets"][key][field] = copied[source]
            for filename in ("index.html", "styles.css", "app.js"):
                shutil.copy2(template / filename, temporary / filename)
            # A JS data file avoids fetch restrictions when opened with file://.
            serialized = json.dumps(payload, ensure_ascii=False, indent=2).replace("<", "\\u003c")
            (temporary / "data.js").write_text("window.FLOW_DATA = " + serialized + ";\n", encoding="utf-8")
            (temporary / "manifest.json").write_text(json.dumps({**report, "media": hashes,
                "verification": "local copies hash-verified; browser playback requires separate QA"},
                ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            require(not out.exists(), "Output appeared during build; refusing to overwrite")
            temporary.rename(out)
        except Exception:
            shutil.rmtree(temporary)
            raise
        print(json.dumps({**report, "html": str(out / "index.html")}, ensure_ascii=False))
    except (ValueError, OSError, KeyError, TypeError, AttributeError) as error:
        parser.exit(2, f"flow panel: {error}\n")


if __name__ == "__main__":
    main()
