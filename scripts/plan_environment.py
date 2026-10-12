#!/usr/bin/env python3
"""Suggest task-scoped routes and installation steps; never install or execute models."""
import argparse
import datetime
import json
from pathlib import Path
from probe_environment import atomic_json

TASKS = ("editing", "lineart", "animation", "voice", "upscale", "panel")
DEFAULT_PROFILES = Path(__file__).resolve().parents[1] / "assets" / "tool-profiles.json"


def status(environment, name):
    return environment.get("tools", {}).get(name, {}).get("status", "unknown")


def backend_status(environment, name):
    return environment.get("backends", {}).get(name, {}).get("status", "unknown")


def matching_check(pilot, task, backend):
    """Keep task claims separate from the bundled smoke's limited technical checks."""
    checks = pilot.get("checks", []) if isinstance(pilot, dict) else []
    if not isinstance(checks, list):
        checks = []
    checks = [c for c in checks if isinstance(c, dict)]
    partial = []
    model_tasks = ("lineart", "animation", "voice", "upscale")
    for check in checks:
        name, scope = check.get("name"), check.get("scope")
        kind = None
        if task == "editing" and name == "ffmpeg" and scope == "synthetic_media_smoke" and check.get("backend") in (None, "cpu"):
            kind = "synthetic_media_technical_only"
        elif task in model_tasks and name == "torch" and scope == "tensor_smoke" and check.get("backend") == backend:
            kind = "backend_tensor_only"
        elif task in model_tasks and name == "case" and scope == "user_model_case" and check.get("backend") == backend:
            kind = "user_case_outputs_only_model_identity_unverified"
        if kind:
            partial.append({"name": name, "status": check.get("status", "unknown"), "scope": scope,
                            "backend": check.get("backend"), "evidence_level": kind, "details": check.get("details"),
                            "task_attribution": "unknown" if name == "case" else task,
                            "task_verified": False, "model_verified": False, "effect_acceptance": False})
    matches = [c for c in checks if c.get("name") == task and c.get("backend") == backend and c.get("scope")]
    result = {"status": "unknown", "reason": "no_matching_task_backend_scope", "partial_checks": partial,
              "task_verified": False, "model_verified": False, "effect_acceptance": False}
    if matches:
        check = matches[-1]
        result.update({"status": check.get("status", "unknown"), "scope": check["scope"], "backend": backend,
                       "details": check.get("details"), "evidence_level": "supplied_task_scoped_claim",
                       "reason": "supplied_evidence_only; freshness_and_target_configuration_require_review"})
    elif partial:
        result.update({"evidence_level": "partial_technical_checks", "reason": "technical_parts_observed; full_task_model_and_effect_not_verified"})
    return result


def make_install_step(tool_id, profile, observed_status, os_name):
    return {"tool": tool_id, "observed_status": observed_status, "action": "inspect_existing_installation" if observed_status == "unknown" else "install_if_this_route_is_selected",
            "official_source": profile["official_source"], "verified_on": profile["verified_on"], "license_url": profile["license_url"],
            "version_strategy": profile["version_strategy"], "isolation": profile["isolation"], "download_size_gb": None,
            "size_note": "unknown; inspect package and model sizes before downloading", "os": os_name,
            "instructions": profile["installation_advice"], "rollback": profile["rollback"], "verify_commands": profile["verify_commands"],
            "requires_user_authorization": True, "executed": False}


def plan(environment, tasks, profiles, pilot=None, cloud_authorized=False, upload_authorized=False):
    if environment.get("schema_version") != "1.0":
        raise ValueError("unsupported environment schema_version")
    if any(task not in TASKS for task in tasks):
        raise ValueError("unknown task; choose: " + ",".join(TASKS))
    reports = []
    for task in tasks:
        config = profiles["tasks"][task]
        reasons, unknowns = [], ["Task input, target resolution/duration and resource headroom still require review"]
        selected_backend, route = "cpu", "local"
        if task == "animation":
            selected_backend = "cuda"
            nvidia = [g for g in environment.get("gpus", []) if g.get("vendor") == "NVIDIA" and g.get("memory_kind") == "dedicated"]
            capacities = [g.get("memory_gb") for g in nvidia if isinstance(g.get("memory_gb"), (int, float))]
            largest = max(capacities) if capacities else None
            reference = profiles["tools"]["tooncomposer"]["resource_reference"]["vram_gb_approx"]
            if largest is not None and largest >= reference:
                route = "local_gpu"
                reasons.append("One NVIDIA GPU has %s GiB reported dedicated memory; eligible for the upstream ~57 GB reference workload comparison" % largest)
            elif largest is not None:
                route = "cloud"
                reasons.append("Largest individual NVIDIA GPU (%s GiB) is below the upstream ~57 GB reference workload; capacities are never added" % largest)
            elif environment.get("gpus") and not any(g.get("vendor") in ("NVIDIA", "unknown") for g in environment["gpus"]):
                route = "cloud"
                reasons.append("Detected GPU vendor is outside the default CUDA route; unified/shared memory is not dedicated NVIDIA VRAM")
            else:
                route = "manual_check"
                unknowns.append("NVIDIA GPU or its dedicated memory is unknown")
            reasons.append("~57 GB is an upstream 480p/61-frame workload observation, not a measured minimum or a universal hard limit; other configurations need their own pilot")
            unknowns.extend(["Model weights, driver/PyTorch CUDA compatibility and usable free VRAM are not proved by inventory", "CPU option exists upstream; acceptable performance for this target has not been established"])
        elif task in ("lineart", "voice", "upscale"):
            if backend_status(environment, "cuda") == "available" and any(g.get("vendor") == "NVIDIA" for g in environment.get("gpus", [])):
                route, selected_backend = "local_gpu", "cuda"
                reasons.append("Existing torch reports CUDA availability; selected model and workload still need a smoke test")
            else:
                reasons.append("CPU is a candidate according to this tool profile; speed and target compatibility are untested")
                if backend_status(environment, "mps") == "available":
                    unknowns.append("MPS availability does not establish this tool's MPS compatibility; retain CPU candidate")
                if backend_status(environment, "cuda") in ("unknown", "not_checked"):
                    unknowns.append("CUDA backend was not established")
            if task == "voice":
                unknowns.append("CPU recommendation covers inference candidate only; voice rights, language/model quality and training need separate review")
        else:
            reasons.append("This task can use local CPU tooling; no GPU is required by the provided utility route")
        missing = [name for name in config["required_tools"] if status(environment, name) == "missing"]
        unknown_tools = [name for name in config["required_tools"] if status(environment, name) not in ("found", "missing")]
        unknowns.extend("Installation status unknown: " + name for name in unknown_tools)
        if task in ("lineart", "animation", "voice", "upscale"):
            if backend_status(environment, "torch") == "unavailable":
                missing.append("torch")
            elif backend_status(environment, "torch") != "available":
                unknown_tools.append("torch")
                unknowns.append("Existing torch installation/backend is not established")
            if selected_backend == "cuda" and backend_status(environment, "cuda") != "available":
                unknowns.append("CUDA is not yet available in the probed Python environment")
        if task in ("editing", "panel") and missing:
            route = "manual_check"
            reasons.append("Install or select an existing suitable utility before execution")
        check = matching_check(pilot or {}, task, selected_backend)
        unknowns.append("Inventory and route selection do not prove model or content acceptance")
        install = []
        for name in dict.fromkeys(missing + unknown_tools):
            if name in profiles["tools"]:
                install.append(make_install_step(name, profiles["tools"][name], status(environment, name) if name != "torch" else backend_status(environment, "torch"), environment.get("host", {}).get("os")))
        if route == "cloud":
            unknowns.extend(["Cloud provider, exact image/GPU, estimated cost and upload rights need approval", "Cloud recommendation has not provisioned an instance or sent any data"])
        reports.append({"task": task, "route": route, "backend_candidate": selected_backend, "reasons": reasons, "unknowns": list(dict.fromkeys(unknowns)),
                        "missing_tools": list(dict.fromkeys(missing)), "install_plan": install, "pilot_evidence": check,
                        "execution_ready": False, "execution_gate": "requires_task_specific_review_and_authorization", "cloud_authorized": cloud_authorized,
                        "upload_authorized": upload_authorized, "conditional_recommendation": True})
    return {"schema_version": "1.0", "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "environment_generated_at": environment.get("generated_at"),
            "profile_verified_on": profiles["verified_on"], "tasks": reports, "warnings": ["Read-only planning; no installation, upload, account access, instance rental or generation performed", "Provided pilot results are claims with explicit scopes; this utility does not authenticate them"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--tasks", required=True, help=",".join(TASKS))
    parser.add_argument("--out", required=True)
    parser.add_argument("--profiles", default=str(DEFAULT_PROFILES))
    parser.add_argument("--pilot-results")
    parser.add_argument("--cloud-authorized", action="store_true", help="Record existing authorization; never provisions resources")
    parser.add_argument("--upload-authorized", action="store_true", help="Record existing authorization; never uploads")
    args = parser.parse_args()
    try:
        environment = json.loads(Path(args.environment).read_text(encoding="utf-8"))
        profiles = json.loads(Path(args.profiles).read_text(encoding="utf-8"))
        pilot = json.loads(Path(args.pilot_results).read_text(encoding="utf-8")) if args.pilot_results else None
        tasks = list(dict.fromkeys(t.strip() for t in args.tasks.split(",") if t.strip()))
        if not tasks:
            raise ValueError("--tasks must contain at least one task")
        result = plan(environment, tasks, profiles, pilot, args.cloud_authorized, args.upload_authorized)
        atomic_json(args.out, result)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    print("Routes: %s. Conditional plan saved: %s" % (", ".join(t["task"] + "=" + t["route"] for t in result["tasks"]), args.out))


if __name__ == "__main__":
    main()
