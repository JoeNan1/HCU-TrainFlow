"""Scenario boundaries use synthetic inputs; these are not hardware evidence."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from hcu_trainflow.capabilities import default_registry
from hcu_trainflow.core import FlowError, Store, write_json
from hcu_trainflow.kernel import CapabilityContext, CapabilityRequest


def invoke(name, context, inputs, action="run"):
    return default_registry().resolve(name).run(context, CapabilityRequest(name, action, inputs))


def quality_inputs(context="ctx"):
    contract = {"context": context, "sample_fingerprint": "frozen-sample", "aggregation": "mean",
                "initial_state_fingerprint": "state", "training_recipe_fingerprint": "recipe",
                "min_steps": 3, "atol": 0.01, "rtol": 0.0, "tolerance_basis": "synthetic test contract"}
    record = {key: contract[key] for key in ("context", "sample_fingerprint", "aggregation",
                                            "initial_state_fingerprint", "training_recipe_fingerprint")}
    record.update(steps=[1, 2, 3], loss=[2.0, 1.9, 1.8], executed=3,
                  evidence=["synthetic-raw-evidence"], candidate_path_exercised=True)
    correctness = dict(record, profiler_off=True, measurement_protocol={"max_relative_mad": 0.1})
    return {"contract": contract, "baseline": dict(record), "candidate": dict(record),
            "correctness": correctness, "baseline_times": [10, 10, 10], "candidate_times": [9, 9, 9]}


def test_quality_accept_keeps_quality_and_performance_findings_separate(tmp_path):
    context = CapabilityContext("standalone", "ctx", tmp_path)
    inputs = quality_inputs()
    result = invoke("quality.accept", context, inputs)
    assert result.status == "pass" and result.outputs["stage_eligible"]
    assert result.outputs["quality"]["status"] == "pass"
    assert result.outputs["performance"]["time_ratio"] == 0.9
    assert result.outputs["production_default"] is False
    assert result.evidence == ("synthetic-raw-evidence",)
    inputs["candidate"]["loss"] = [3, 3, 3]
    result = invoke("quality.accept", context, inputs)
    assert result.status == "fail" and not result.outputs["stage_eligible"]
    assert result.outputs["performance"]["status"] == "iteration-kept"


@pytest.mark.parametrize("change", ["missing-evidence", "too-few-repetitions", "unstable", "wrong-context"])
def test_quality_accept_does_not_accept_missing_or_incompatible_measurements(tmp_path, change):
    inputs = quality_inputs()
    if change == "missing-evidence":
        inputs["correctness"]["evidence"] = []
    elif change == "too-few-repetitions":
        inputs["baseline_times"] = inputs["candidate_times"] = [10]
    elif change == "unstable":
        inputs["candidate_times"] = [1, 10, 100]
    else:
        inputs["contract"]["context"] = "different-task"
    result = invoke("quality.accept", CapabilityContext("standalone", "ctx", tmp_path), inputs)
    assert result.status == "incomplete"


def test_quality_accept_records_bound_provenance_without_changing_thresholds(tmp_path):
    inputs = quality_inputs()
    inputs["analysis"] = {"context": "ctx", "status": "complete", "evidence": ["trace-artifact"]}
    inputs["environment"] = {"context": "ctx", "status": "pass", "evidence": ["environment-artifact"]}
    context = CapabilityContext("standalone", "ctx", tmp_path)
    result = invoke("quality.accept", context, inputs)
    assert result.status == "pass"
    assert result.outputs["quality"]["max_abs_error"] == 0
    assert result.outputs["performance"]["time_ratio"] == 0.9
    assert result.outputs["provenance"]["analysis"]["fingerprint"]
    assert "trace-artifact" in result.evidence
    inputs["analysis"]["context"] = "foreign"
    result = invoke("quality.accept", context, inputs)
    assert result.status == "incomplete"
    assert "analysis-provenance-context-mismatch" in result.outputs["reasons"]


def test_environment_check_rejects_foreign_contract_and_exposes_observations(tmp_path):
    context = CapabilityContext("standalone", "ctx", tmp_path)
    contract = {"context": "ctx", "required": [{"node": "n", "device": 0, "check": "driver", "conditions": {}}]}
    row = {"node": "n", "device": 0, "check": "driver", "conditions": {},
           "context": "ctx", "status": "pass", "executed": 1, "evidence": ["synthetic-evidence"]}
    result = invoke("environment.check", context, {"contract": contract, "observations": [row]})
    assert result.status == "pass" and result.outputs["observations"] == [row]
    result = invoke("environment.check", context,
                    {"contract": dict(contract, context="foreign"), "observations": [row]})
    assert result.status == "incomplete"


def collector_fixture(tmp_path, payload, *, permission=True, exit_code=0):
    store = Store(tmp_path / "store")
    task = store.create({"schema_version": 1, "task_id": "collector", "mode": "environment",
                         "objective": "CPU-only collector test", "context": {"source": "synthetic"},
                         "permissions": ["execute"] if permission else [],
                         "budget": {"max_operations": 3, "max_seconds": 30}})
    context = CapabilityContext.from_task(task, store.root)
    contract = {"context": context.context,
                "required": [{"node": "n", "device": 0, "check": "tool", "conditions": {}}]}
    if payload == "valid":
        payload = json.dumps({"measurements": [{"node": "n", "device": 0, "check": "tool", "conditions": {},
                                              "context": context.context, "status": "pass", "executed": 1}]})
    lease = store.lease("cpu-collector-test", "controller", ttl=30)
    card = {"schema_version": 1, "backend": "local", "cwd": str(tmp_path),
            "argv": [sys.executable, "-c", f"print({payload!r}); raise SystemExit({exit_code})"],
            "basis": "CPU-only synthetic collector", "timeout_seconds": 10}
    return store, context, {"contract": contract,
                            "execution": {"operation": "collect", "card": card, "lease": lease}}


def test_environment_collect_executes_and_retains_raw_stdout(tmp_path):
    store, context, inputs = collector_fixture(tmp_path, "valid")
    result = invoke("environment.check", context, inputs, "collect")
    assert result.status == "pass"
    assert result.outputs["observations"][0]["evidence"]
    stdout = json.loads(store.artifact(result.outputs["execution"]["evidence"][0]))
    assert stdout["measurements"][0]["executed"] == 1
    assert len(result.evidence) >= 2


@pytest.mark.parametrize("payload,exit_code,status", [("not json", 0, "incomplete"), ("valid", 2, "fail")])
def test_environment_collect_requires_successful_parseable_execution(tmp_path, payload, exit_code, status):
    store, context, inputs = collector_fixture(tmp_path, payload, exit_code=exit_code)
    # User-supplied observations cannot stand in for collector output.
    inputs["observations"] = [{"status": "pass"}]
    result = invoke("environment.check", context, inputs, "collect")
    assert result.status == status
    assert result.evidence


def test_environment_collect_honors_existing_execution_permission(tmp_path):
    _, context, inputs = collector_fixture(tmp_path, "valid", permission=False)
    with pytest.raises(FlowError, match="no execute permission"):
        invoke("environment.check", context, inputs, "collect")
    context = CapabilityContext("unbound", context.context, context.workspace)
    with pytest.raises(FlowError, match="task-bound"):
        invoke("environment.check", context, inputs, "collect")


@pytest.mark.parametrize("payload,expected", [("measurement", "complete"), ("not-json", "incomplete")])
def test_execution_json_bridge_retains_measurement_evidence(tmp_path, payload, expected):
    if payload == "measurement":
        payload = json.dumps({"correctness": {"executed": 3, "candidate_path_exercised": True},
                              "baseline_times": [1, 1, 1], "candidate_times": [1, 1, 1]})
    store, context, inputs = collector_fixture(tmp_path, payload)
    request = CapabilityRequest("execution.command", "run", inputs["execution"], {"stdout_json": True})
    result = default_registry().resolve("execution.command").run(context, request)
    assert result.status == expected
    if expected == "complete":
        correctness = result.outputs["document"]["correctness"]
        assert correctness["executed"] == 3 and correctness["evidence"]
        assert "context" not in correctness and "profiler_off" not in correctness
        for sha in correctness["evidence"]:
            store.artifact(sha)
    else:
        assert result.outputs["execution_status"] == "complete"
        assert result.evidence


@pytest.mark.parametrize("native_outcome,expected", [("success", "complete"), ("timeout", "fail"), ("empty", "incomplete")])
def test_tracelens_scenario_retains_inputs_logs_and_tables(tmp_path, monkeypatch, native_outcome, expected):
    from hcu_trainflow import tracelens
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    monkeypatch.setattr(tracelens, "require_checkout", lambda *a: (checkout, {"commit": "a" * 40}))
    trace = tmp_path / "trace.json"
    write_json(trace, {"traceEvents": [
        {"ph": "X", "cat": "cpu_op", "name": "aten::mm", "ts": 0, "dur": 10, "args": {}},
        {"ph": "X", "cat": "kernel", "name": "synthetic_mm", "ts": 2, "dur": 5, "args": {}}]})

    def worker(argv, **kwargs):
        if native_outcome == "timeout":
            raise subprocess.TimeoutExpired(argv, 1)
        if native_outcome == "success":
            folder = Path(json.loads(Path(argv[-1]).read_text())["output_csvs_dir"])
            folder.mkdir()
            (folder / "kernel.csv").write_text("name,duration\nmm,5\n")
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(tracelens.subprocess, "run", worker)
    context = CapabilityContext("trace-only", "ctx", tmp_path / "store")
    result = invoke("profiling.tracelens", context, {"project": ".", "trace": str(trace)})
    assert result.status == expected
    retained = result.outputs["retained_files"]
    names = {Path(row["path"]).name for row in retained}
    assert {"trace.json", "stdout.log", "stderr.log", "report.json"} <= names
    assert result.outputs["training_assessment"].startswith("unassessed")
    store = Store(context.workspace)
    for sha in result.evidence:
        store.artifact(sha)
    if native_outcome == "success":
        assert "kernel.csv" in names

