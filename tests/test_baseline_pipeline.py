"""Real CPU commands and native offline conversion; never hardware proof."""
import json
from pathlib import Path
import sys

import pytest

from hcu_trainflow.capabilities import default_registry
from hcu_trainflow.core import FlowError, Store, digest
from hcu_trainflow.kernel import CapabilityContext, CapabilityRequest
from hcu_trainflow.modular_cli import pipeline_run
from hcu_trainflow.services import RuntimeService, baseline_pipeline


@pytest.fixture
def native_tracelens():
    from hcu_trainflow.dependencies import require_checkout
    try:
        require_checkout(Path(__file__).resolve().parents[1], "tracelens")
    except FlowError as exc:
        pytest.skip("Native offline integration requires the pinned optional TraceLens checkout: " + str(exc))
    pytest.importorskip("pandas", reason="Native TraceLens integration requires its optional dependencies")


def trace_fixture():
    api = {"ph": "X", "cat": "HIP", "name": "hipLaunchKernel", "args": {
        "BeginNs": "1000000000", "EndNs": "1000001000", "DurationNs": 1000,
        "pid": 42, "tid": 42, "index": 1}}
    kernel = {"ph": "X", "cat": "HIPOPS", "name": "synthetic_kernel", "args": {
        "BeginNs": "1000001000", "EndNs": "1000005000", "DurationNs": 4000,
        "pid": 42, "tid": 42, "index": 1, "devId": 0, "queueId": 1,
        "args": "Grid={x=1,y=1,z=1} Block={x=64,y=1,z=1}"}}
    return json.dumps({"traceEvents": [api, kernel]}).encode()


def training_log():
    lines = ["  load ........... None", "  load_weights ........... False", "  profile ........... False"]
    for step in range(1, 13):
        lines.append(f"iteration {step}/12 | elapsed time per iteration (ms): 10 | lm loss: 2 | "
                     "number of skipped iterations: 0 | number of nan iterations: 0 |")
    for split in ("validation", "test"):
        lines.append(f"validation loss at iteration 12 on {split} set | lm loss value: 2.0 |")
    return "\n".join(lines) + "\n"


def contract(context):
    return {"context": context, "expected_steps": 12, "steady_start": 3, "world_size": 1,
            "global_batch_size": 1, "seq_length": 16, "timing_groups": 3, "min_samples_per_group": 3}


def make_run(tmp_path, *, missing_trace=False):
    store = Store(tmp_path / "store")
    task = store.create({"schema_version": 1, "task_id": "cpu-closure", "mode": "analyze",
                         "objective": "Synthetic CPU integration only", "context": {"source": "fixture"},
                         "permissions": ["execute"], "budget": {"max_operations": 3, "max_seconds": 90}})
    ctx = CapabilityContext.from_task(task, store.root)
    lease = store.lease("cpu-fixture", "controller", ttl=120)
    trace = tmp_path / "generated-trace.json"
    marker = tmp_path / "launch-count.txt"
    collector = tmp_path / "fixture.py"
    observations = {"measurements": [{"context": ctx.context, "node": "cpu", "device": 0,
                                      "check": "ready", "conditions": {}, "executed": 1, "status": "pass"}]}
    receipt = {"files": {"trace": {"path": str(trace), "sha256": digest(trace_fixture())}}}
    collector.write_text("import json,sys\nfrom pathlib import Path\n"
                         f"trace=Path({str(trace)!r})\nmarker=Path({str(marker)!r})\n"
                         "if sys.argv[1]=='environment':\n"
                         f" print(json.dumps({observations!r}))\n"
                         "elif sys.argv[1]=='train':\n"
                         " marker.write_text(marker.read_text()+'launch\\n' if marker.exists() else 'launch\\n')\n"
                         f" print({training_log()!r})\n"
                         "else:\n"
                         + (" pass\n" if missing_trace else f" trace.write_bytes({trace_fixture()!r})\n")
                         + f" print(json.dumps({receipt!r}))\n")
    def execution(mode):
        return {"operation": "fixture-" + mode, "lease": lease,
                "card": {"schema_version": 1, "backend": "local", "cwd": str(tmp_path),
                         "argv": [sys.executable, str(collector), mode], "basis": "Synthetic CPU test",
                         "timeout_seconds": 20}}
    plan = baseline_pipeline(environment={"contract": {"context": ctx.context, "required": [
        {"node": "cpu", "device": 0, "check": "ready", "conditions": {}}]}, "execution": execution("environment")},
        training=execution("train"), training_contract=contract(ctx.context), profiling=execution("profile"),
        project=Path(__file__).resolve().parents[1])
    return store, ctx, plan, trace, marker


def test_whole_pipeline_native_conversion_artifacts_reports_and_cli_resume(tmp_path, native_tracelens):
    store, ctx, plan, trace, marker = make_run(tmp_path)
    result = RuntimeService(store).run_pipeline(plan, ctx)
    assert result["status"] == "complete", result
    assert set(result["steps"]) == {s.id for s in plan.steps}
    quality = result["steps"]["qualification"]["outputs"]
    assert quality["baseline_qualified"] and not quality["optimization_validated"]
    assert not quality["stage_eligible"] and quality["model_diagnosis"] == "incomplete"
    assert quality["performance"]["tokens_per_second_per_gpu"] == pytest.approx(1600)
    analysis = result["steps"]["analysis"]["outputs"]
    assert analysis["top_kernels"][0]["total_seconds"] == pytest.approx(4e-6)
    for envelope in result["steps"].values():
        for sha in envelope["evidence"]:
            store.artifact(sha)
    assert set(result["reports"]) == {"environment", "analysis", "qualification"}
    path = tmp_path / "pipeline.json"
    path.write_text(json.dumps({"pipeline": plan.to_dict()}))
    again = pipeline_run(store, str(path), task_id=ctx.task_id, resume_run_id=result["run_id"])
    assert again["status"] == "complete" and again["run_id"] == result["run_id"]
    assert marker.read_text() == "launch\n"
    with store.db() as db:
        assert db.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == 3
        assert db.execute("SELECT state FROM tasks").fetchone()[0] == "draft"


def test_downstream_failure_resumes_same_run_without_relaunching_training(tmp_path, native_tracelens):
    store, ctx, plan, trace, marker = make_run(tmp_path, missing_trace=True)
    first = RuntimeService(store).run_pipeline(plan, ctx)
    assert first["steps"]["profile-files"]["status"] == "incomplete"
    assert first["steps"]["qualification"]["status"] == "blocked"
    trace.write_bytes(trace_fixture())
    resumed = RuntimeService(store).run_pipeline(plan, ctx, resume_run_id=first["run_id"])
    assert resumed["status"] == "complete", resumed
    assert marker.read_text() == "launch\n"
    with store.db() as db:
        assert db.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == 3
    # Immutable inputs cannot be silently replaced on resume.
    source = Path(plan.steps[1].inputs["card"]["argv"][1])
    source.write_text(source.read_text() + "\n# changed source\n")
    with pytest.raises(FlowError, match="identity changed"):
        RuntimeService(store).run_pipeline(plan, ctx, resume_run_id=first["run_id"])


@pytest.mark.parametrize("replacement,status", [
    (("number of skipped iterations: 0", "number of skipped iterations: 1"), "fail"),
    (("lm loss: 2", "lm loss: nan"), "fail"),
    (("load ........... None", "load ........... /checkpoint"), "incomplete"),
    (("profile ........... False", "profile ........... True"), "incomplete"),
    (("iteration 12/12", "iteration 11/12"), "incomplete"),
    (("on test set", "on unknown set"), "incomplete"),
])
def test_summary_independently_rejects_bad_or_missing_baseline_evidence(tmp_path, replacement, status):
    store = Store(tmp_path)
    sha = store.put(training_log().replace(*replacement).encode())
    ctx = CapabilityContext("independent", "ctx", store.root)
    result = RuntimeService(store).run_capability(CapabilityRequest("training.summarize", "parse", {
        "log_artifact": sha, "contract": contract(ctx.context)}), ctx)
    assert result["status"] == status


def test_output_receipt_hash_is_checked_before_consumption(tmp_path):
    store = Store(tmp_path / "store")
    output = tmp_path / "output.json"
    output.write_bytes(b"changed")
    result = RuntimeService(store).run_capability(CapabilityRequest("artifact.collect", "retain", {
        "files": {"trace": {"path": str(output), "sha256": digest(b"original")}}}),
        CapabilityContext("independent", "ctx", store.root))
    assert result["status"] == "incomplete" and not result["evidence"]


@pytest.mark.parametrize("source,status", [("environment", "fail"), ("analysis", "incomplete"),
                                         ("training", "incomplete")])
def test_baseline_qualification_cannot_hide_failed_provenance(tmp_path, source, status):
    store = Store(tmp_path)
    evidence = store.put(b"synthetic retained provenance")
    training = {"context": "ctx", "status": "pass", "scope": "fresh-short-baseline", "executed": 12,
                "fresh_initialization": True, "profiler_off": True, "evidence": [evidence]}
    inputs = {"training": training, "environment": {"context": "ctx", "status": "pass", "evidence": [evidence]},
              "analysis": {"context": "ctx", "status": "complete", "scope": "hipprof-summary", "evidence": [evidence]}}
    inputs[source]["status"] = status
    result = RuntimeService(store).run_capability(CapabilityRequest("quality.accept", "qualify", inputs),
                                                 CapabilityContext("independent", "ctx", store.root))
    assert result["status"] == ("fail" if status == "fail" else "incomplete")
    assert not result["outputs"]["baseline_qualified"]
