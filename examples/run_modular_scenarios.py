#!/usr/bin/env python3
"""Run three standalone scenarios and a composed Pipeline without GPU work.

Environment checks cover this CPU Python process only. Losses and timings are
synthetic fixtures. TraceLens genuinely analyzes the pinned project's synthetic
trace. No result establishes HCU health, model accuracy, or training performance.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import sys

from hcu_trainflow.core import Store, fingerprint, write_json
from hcu_trainflow.kernel import CapabilityContext, CapabilityRequest, PipelinePlan
from hcu_trainflow.services import RuntimeService


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True, help="TrainFlow checkout with reviewed TraceLens binding")
    parser.add_argument("--workspace", type=Path, required=True, help="Private output directory, separate from source inputs")
    args = parser.parse_args()
    project, workspace = args.project.resolve(), args.workspace.resolve()
    trace = project / "examples" / "tracelens-trace.json"
    if not trace.is_file():
        parser.error("--project must contain examples/tracelens-trace.json")
    if workspace == project or workspace in project.parents:
        parser.error("--workspace must be a dedicated task directory, not the checkout or its parent")
    store = Store(workspace)
    service = RuntimeService(store)
    context_id = fingerprint({"example": "software-scenarios", "kind": "synthetic-not-hardware"})
    context = CapabilityContext("software-demo", context_id, workspace)
    raw_dir = workspace / "demo-inputs"
    raw_dir.mkdir(exist_ok=True)

    def retain(name, record):
        path = raw_dir / name
        write_json(path, record)
        return store.put(path.read_bytes())

    conditions = {"scope": "local-cpu-python-only", "python": platform.python_version()}
    observation = {"node": "local-controller", "device": "cpu", "check": "python-process",
                   "conditions": conditions, "context": context_id,
                   "status": "pass" if sys.version_info >= (3, 10) else "fail", "executed": 1,
                   "runtime_executable": sys.executable,
                   "limits": "CPU interpreter check only; no HCU health or execution was assessed"}
    observation["evidence"] = [retain("cpu-observation.json", observation)]
    environment_inputs = {"contract": {"context": context_id,
        "required": [{"node": "local-controller", "device": "cpu", "check": "python-process", "conditions": conditions}]},
        "observations": [observation]}
    trace_inputs = {"project": str(project), "trace": str(trace), "rank": 0, "timeout": 120}
    contract = {"context": context_id, "sample_fingerprint": "synthetic-fixed-sample", "aggregation": "synthetic-mean",
                "initial_state_fingerprint": "synthetic-initial-state", "training_recipe_fingerprint": "synthetic-recipe",
                "min_steps": 3, "atol": 0.01, "rtol": 0,
                "tolerance_basis": "Synthetic demonstration only; no measured model or operator error"}
    baseline = {key: contract[key] for key in ("context", "sample_fingerprint", "aggregation",
                                              "initial_state_fingerprint", "training_recipe_fingerprint")}
    baseline.update(kind="synthetic-software-fixture", steps=[1, 2, 3], loss=[2.0, 1.9, 1.8], executed=3)
    candidate = dict(baseline, candidate_path_exercised=True)
    baseline["evidence"] = [retain("synthetic-baseline.json", baseline)]
    candidate["evidence"] = [retain("synthetic-candidate.json", candidate)]
    baseline_times, candidate_times = [10.0, 10.1, 9.9], [9.0, 9.1, 8.9]
    correctness = {"kind": "synthetic-software-fixture", "context": context_id, "executed": 3, "failures": 0,
                   "candidate_path_exercised": True, "profiler_off": True,
                   "measurement_protocol": {"kind": "synthetic-no-device-timings", "max_relative_mad": 0.05}}
    correctness["evidence"] = [retain("synthetic-correctness-and-timings.json", {
        "correctness": correctness, "baseline_times": baseline_times, "candidate_times": candidate_times})]
    quality_inputs = {"contract": contract, "baseline": baseline, "candidate": candidate, "correctness": correctness,
                      "baseline_times": baseline_times, "candidate_times": candidate_times, "max_regression": 0}
    requests = {
        "environment": CapabilityRequest("environment.check", "check", environment_inputs),
        "analysis": CapabilityRequest("profiling.tracelens", "analyze", trace_inputs),
        "acceptance": CapabilityRequest("quality.accept", "assess", quality_inputs),
    }
    standalone = {}
    for name, request in requests.items():
        write_json(raw_dir / (name + "-request.json"), {"context": context_id, "capability": request.capability,
                                                      "action": request.action, "inputs": dict(request.inputs)})
        standalone[name] = service.run_capability(request, context)
    plan = PipelinePlan.from_dict({"name": "software-scenarios", "steps": [
        {"id": "environment", "capability": "environment.check", "action": "check", "inputs": environment_inputs},
        {"id": "analysis", "capability": "profiling.tracelens", "action": "analyze",
         "depends_on": ["environment"], "inputs": trace_inputs},
        {"id": "acceptance", "capability": "quality.accept", "action": "assess",
         "depends_on": ["environment", "analysis"], "inputs": quality_inputs,
         "bindings": {"environment": {"step": "environment", "path": []},
                      "analysis": {"step": "analysis", "path": []}}},
    ]})
    write_json(raw_dir / "pipeline.json", {"pipeline": plan.to_dict(), "context": {"context": context_id}})
    composed = service.run_pipeline(plan, context)
    receipt = {"kind": "software-demonstration-not-hardware-validation", "context": context_id,
               "limits": "CPU environment check; synthetic losses/timings/Trace; actual pinned TraceLens worker. No HCU load or training.",
               "standalone": standalone, "composed": composed}
    receipts = workspace / "receipts"
    receipts.mkdir(exist_ok=True)
    write_json(receipts / "software-scenarios.json", receipt)
    passed = all(result["status"] in {"pass", "complete"} for result in standalone.values()) and composed["status"] == "complete"
    print(json.dumps({"status": "pass" if passed else "incomplete", "kind": receipt["kind"],
                      "receipt": str(receipts / "software-scenarios.json"),
                      "standalone": {key: result["status"] for key, result in standalone.items()},
                      "composed": composed["status"]}, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
