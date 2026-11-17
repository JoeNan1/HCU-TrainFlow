"""Application-level tests: persistence, actual data flow and failure boundaries."""
import json

import pytest

from hcu_trainflow import flow
from hcu_trainflow.capabilities.registry import CapabilityRegistry
from hcu_trainflow.core import FlowError, PipelineContextConflict, Store
from hcu_trainflow.kernel import CapabilityContext, CapabilityRequest, CapabilityResult, PipelinePlan
from hcu_trainflow.modular_cli import capability_run, pipeline_run
from hcu_trainflow.services import RuntimeService


class FixtureCapability:
    name = "fixture.echo"
    version = "test-1"

    def __init__(self, callback=None):
        self.calls = []
        self.callback = callback

    def actions(self):
        return ("run",)

    def run(self, context, request):
        self.calls.append(dict(request.inputs))
        if self.callback:
            return self.callback(context, request)
        return CapabilityResult(self.name, request.action, "pass", outputs={"value": request.inputs.get("value", 1)})


def setup(tmp_path, capability=None):
    store = Store(tmp_path / "store")
    cap = capability or FixtureCapability()
    service = RuntimeService(store, CapabilityRegistry([cap]))
    return store, cap, service, CapabilityContext("independent", "ctx", store.root)


def plan(steps=None):
    return PipelinePlan.from_dict({"name": "fixture", "steps": steps or [{"id": "a", "capability": "fixture.echo"}]})


def test_standalone_persists_without_creating_task_and_reuses_verified_results(tmp_path):
    store, cap, service, ctx = setup(tmp_path)
    first = service.run_pipeline(plan(), ctx, {"value": 3})
    second = service.run_pipeline(plan(), ctx, {"value": 3}, resume_run_id=first["run_id"])
    assert first["status"] == "complete"
    assert second["resumed"] and len(cap.calls) == 1
    assert store.artifact(first["artifacts"]["a"])
    retained_request = json.loads(store.artifact(first["request_artifact"]))
    assert retained_request["inputs"] == {"value": 3}
    with store.db() as db:
        assert db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0
    assert store.pipeline_state(first["run_id"])["input_identity"]


def test_changed_values_or_same_path_file_contents_require_new_run(tmp_path):
    store, cap, service, ctx = setup(tmp_path)
    source = tmp_path / "input.json"
    source.write_text('{"a":1}')
    first = service.run_pipeline(plan(), ctx, {"source": str(source), "value": 3})
    second = service.run_pipeline(plan(), ctx, {"source": str(source), "value": 4})
    assert second["run_id"] != first["run_id"]
    source.write_text('{"a":2}')
    with pytest.raises(FlowError, match="identity changed"):
        service.run_pipeline(plan(), ctx, {"source": str(source), "value": 3}, first["run_id"])
    third = service.run_pipeline(plan(), ctx, {"source": str(source), "value": 3})
    assert third["run_id"] != first["run_id"]
    assert len(cap.calls) == 3


def test_cached_artifact_corruption_is_not_a_cached_pass(tmp_path):
    store, cap, service, ctx = setup(tmp_path)
    first = service.run_pipeline(plan(), ctx)
    sha = first["artifacts"]["a"]
    (store.root / "objects" / sha[:2] / sha).write_bytes(b"damaged")
    with pytest.raises(FlowError, match="hash mismatch"):
        service.run_pipeline(plan(), ctx)
    assert len(cap.calls) == 1


def test_explicit_bindings_feed_predecessor_output_and_reject_bad_paths(tmp_path):
    store, cap, service, ctx = setup(tmp_path)
    steps = [{"id": "a", "capability": cap.name, "inputs": {"value": 42}},
             {"id": "b", "capability": cap.name, "depends_on": ["a"],
              "inputs": {"value": 0}, "bindings": {"value": {"step": "a", "path": ["value"]}}}]
    result = service.run_pipeline(plan(steps), ctx)
    assert result["steps"]["b"]["outputs"]["value"] == 42
    steps[1]["bindings"]["value"]["path"] = ["missing"]
    bad = service.run_pipeline(plan(steps), ctx)
    assert bad["steps"]["b"]["status"] == "fail"
    assert "Missing dependency output" in bad["steps"]["b"]["message"]


def test_bindings_cannot_read_unlisted_dependencies():
    with pytest.raises(ValueError, match="direct dependency"):
        plan([{"id": "a", "capability": "fixture.echo",
               "bindings": {"x": {"step": "other", "path": []}}}])


def test_failed_and_blocked_steps_are_retained_then_resumed(tmp_path):
    broken = [True]
    def run(context, request):
        return CapabilityResult("fixture.echo", request.action,
                                "fail" if broken[0] and request.inputs.get("break") else "pass",
                                outputs={"value": 7})
    store, cap, service, ctx = setup(tmp_path, FixtureCapability(run))
    document = plan([{"id": "ok", "capability": cap.name},
                     {"id": "bad", "capability": cap.name, "inputs": {"break": True}},
                     {"id": "blocked", "capability": cap.name, "depends_on": ["bad"]}])
    first = service.run_pipeline(document, ctx)
    state = store.pipeline_state(first["run_id"])
    assert {r["step"]: r["status"] for r in state["steps"]} == {"ok": "pass", "bad": "fail", "blocked": "blocked"}
    broken[0] = False
    second = service.run_pipeline(document, ctx, resume_run_id=first["run_id"])
    assert second["status"] == "complete"
    assert len(cap.calls) == 4  # two initial calls, then bad and blocked; ok reused


def test_controller_interruption_retains_pending_step_and_completed_dependencies(tmp_path):
    stop = [True]
    def run(context, request):
        if request.inputs.get("interrupt") and stop[0]:
            raise KeyboardInterrupt("controller stopped")
        return CapabilityResult("fixture.echo", request.action, "pass")
    store, cap, service, ctx = setup(tmp_path, FixtureCapability(run))
    document = plan([{"id": "a", "capability": cap.name},
                     {"id": "b", "capability": cap.name, "depends_on": ["a"], "inputs": {"interrupt": True}}])
    with pytest.raises(KeyboardInterrupt):
        service.run_pipeline(document, ctx)
    with store.db() as db:
        run_id = db.execute("SELECT id FROM pipeline_runs").fetchone()[0]
    state = store.pipeline_state(run_id)
    assert state["status"] == "interrupted"
    assert state["steps"][1]["result"]["metadata"]["pending"]
    stop[0] = False
    assert service.run_pipeline(document, ctx, resume_run_id=run_id)["status"] == "complete"
    assert len(cap.calls) == 3


def test_file_mutation_during_execution_cannot_complete(tmp_path):
    source = tmp_path / "source.txt"
    source.write_text("initial")
    def run(context, request):
        source.write_text("changed")
        return CapabilityResult("fixture.echo", request.action, "pass")
    store, cap, service, ctx = setup(tmp_path, FixtureCapability(run))
    with pytest.raises(PipelineContextConflict, match="input files changed"):
        service.run_pipeline(plan(), ctx, {"input_file": str(source)})
    with store.db() as db:
        assert db.execute("SELECT status FROM pipeline_runs").fetchone()[0] == "conflicted"


def test_context_change_during_task_execution_is_explicit_conflict(tmp_path):
    store, cap, service, ctx = setup(tmp_path)
    task = store.create({"schema_version": 1, "task_id": "real-task", "objective": "fixture",
                         "context": {"model": "toy"}, "mode": "full"})
    flow.start(store, task["id"], {"acceptance": {"result": "pass"}})
    def run(context, request):
        store.change_context(task["id"], {"model": "changed"})
        return CapabilityResult("fixture.echo", request.action, "pass")
    cap.callback = run
    bound = CapabilityContext.from_task(store.task(task["id"]), store.root)
    with pytest.raises(PipelineContextConflict):
        service.run_pipeline(plan(), bound)
    with store.db() as db:
        assert db.execute("SELECT status FROM pipeline_runs").fetchone()[0] == "conflicted"


def test_legacy_run_is_readable_but_not_resumable(tmp_path):
    store, cap, service, ctx = setup(tmp_path)
    store.pipeline_start(None, "old", "fixture", plan().to_dict(), "ctx", 0)
    assert store.pipeline_state("old")["input_identity"] is None
    with pytest.raises(FlowError, match="legacy"):
        service.run_pipeline(plan(), ctx, resume_run_id="old")


def test_single_capability_cli_and_python_share_result_and_artifacts(tmp_path):
    store = Store(tmp_path / "store")
    sha = store.put(b"actual local fixture observations")
    inputs = {"contract": {"context": "ctx", "required": [{"node": "n", "device": 0, "check": "ready", "conditions": {}}]},
              "observations": [{"context": "ctx", "node": "n", "device": 0, "check": "ready", "conditions": {},
                                "executed": 1, "status": "pass", "evidence": [sha]}]}
    request = CapabilityRequest("environment.check", "check", inputs)
    context = CapabilityContext("standalone", "ctx", store.root)
    python_result = RuntimeService(store).run_capability(request, context)
    file = tmp_path / "request.json"
    file.write_text(json.dumps({"context": "ctx", "action": "check", "inputs": inputs}))
    cli_result = capability_run(store, "environment.check", str(file))
    assert python_result["status"] == cli_result["status"] == "pass"
    assert python_result["artifacts"] == cli_result["artifacts"]
    assert python_result["outputs"] == cli_result["outputs"]


def test_unregistered_raw_evidence_is_incomplete_not_pass(tmp_path):
    store = Store(tmp_path / "store")
    inputs = {"contract": {"context": "ctx", "required": [{"node": "n", "device": 0, "check": "ready", "conditions": {}}]},
              "observations": [{"context": "ctx", "node": "n", "device": 0, "check": "ready", "conditions": {},
                                "executed": 1, "status": "pass", "evidence": ["invented"]}]}
    result = RuntimeService(store).run_capability(CapabilityRequest("environment.check", "check", inputs),
                                                 CapabilityContext("standalone", "ctx", store.root))
    assert result["status"] == "incomplete"
    assert "evidence_gaps" in result["outputs"]


def test_volatile_capabilities_and_dependents_are_not_reused(tmp_path):
    store, cap, service, ctx = setup(tmp_path)
    cap.name = "observation.collect"
    service = RuntimeService(store, CapabilityRegistry([cap]))
    document = plan([{"id": "a", "capability": cap.name},
                     {"id": "b", "capability": cap.name, "depends_on": ["a"]}])
    first = service.run_pipeline(document, ctx)
    service.run_pipeline(document, ctx, resume_run_id=first["run_id"])
    assert len(cap.calls) == 4


def test_full_context_cannot_drop_task_binding(tmp_path):
    store, cap, service, ctx = setup(tmp_path)
    from dataclasses import replace
    with pytest.raises(FlowError, match="task-bound"):
        service.run_pipeline(plan(), replace(ctx, mode="full"))


def test_optional_success_is_invalidated_when_incomplete_dependency_reruns(tmp_path):
    pending = [True]
    def run(context, request):
        status = "incomplete" if pending[0] and request.inputs.get("producer") else "pass"
        return CapabilityResult("fixture.echo", request.action, status, outputs={"value": len(cap.calls)})
    store, cap, service, ctx = setup(tmp_path, FixtureCapability(run))
    document = plan([{"id": "a", "capability": cap.name, "inputs": {"producer": True}},
                     {"id": "b", "capability": cap.name, "depends_on": ["a"], "required": False,
                      "bindings": {"value": {"step": "a", "path": ["value"]}}}])
    first = service.run_pipeline(document, ctx)
    assert first["status"] == "incomplete" and first["steps"]["b"]["status"] == "pass"
    pending[0] = False
    second = service.run_pipeline(document, ctx, resume_run_id=first["run_id"])
    assert second["status"] == "complete" and len(cap.calls) == 4
    assert cap.calls[-1]["value"] == 3


def test_report_registration_rejects_changed_revision_atomically(tmp_path):
    store, cap, service, ctx = setup(tmp_path)
    task = store.create({"schema_version": 1, "task_id": "report-task", "objective": "fixture",
                         "context": {"model": "toy"}, "mode": "environment"})
    sha = store.put(b"raw")
    report = {"context": task["context"], "status": "incomplete", "evidence": [sha]}
    with store.db() as db:
        db.execute("UPDATE tasks SET revision=revision+1 WHERE id=?", (task["id"],))
    with pytest.raises(PipelineContextConflict):
        store.report(task["id"], "environment", report, expected_revision=task["revision"])
    with store.db() as db:
        assert db.execute("SELECT COUNT(*) FROM reports").fetchone()[0] == 0


def test_source_change_in_later_step_does_not_publish_earlier_pass_report(tmp_path):
    store, cap, service, ctx = setup(tmp_path)
    source = tmp_path / "input.txt"
    source.write_text("frozen")
    task = store.create({"schema_version": 1, "task_id": "deferred", "objective": "fixture",
                         "context": {"model": "toy"}, "mode": "environment"})
    sha = store.put(b"raw")
    def run(context, request):
        if request.inputs.get("mutate"):
            source.write_text("changed")
        return CapabilityResult("fixture.echo", request.action, "pass",
                                outputs={"status": "pass", "context": context.context, "executed": 1,
                                         "failures": 0, "evidence": [sha]}, evidence=(sha,))
    cap.callback = run
    document = plan([{"id": "a", "capability": cap.name, "config": {"report_kind": "environment"}},
                     {"id": "b", "capability": cap.name, "depends_on": ["a"], "inputs": {"mutate": True}}])
    with pytest.raises(PipelineContextConflict):
        service.run_pipeline(document, CapabilityContext.from_task(task, store.root), {"input_file": str(source)})
    with store.db() as db:
        assert db.execute("SELECT COUNT(*) FROM reports").fetchone()[0] == 0


def test_standalone_environment_collection_via_service_needs_no_full_flow(tmp_path):
    import sys
    store = Store(tmp_path / "store")
    task = store.create({"schema_version": 1, "task_id": "cpu-check", "mode": "environment",
                         "objective": "actual CPU JSON collector", "context": {"fixture": "cpu"},
                         "permissions": ["execute"], "budget": {"max_operations": 2, "max_seconds": 20}})
    row = {"node": "n", "device": "cpu", "check": "process", "conditions": {},
           "context": task["context"], "status": "pass", "executed": 1}
    lease = store.lease("cpu-fixture", "controller", 30)
    request = CapabilityRequest("environment.check", "collect", {
        "contract": {"context": task["context"], "required": [
            {"node": "n", "device": "cpu", "check": "process", "conditions": {}}]},
        "execution": {"operation": "collect", "lease": lease, "card": {
            "schema_version": 1, "backend": "local", "cwd": str(tmp_path),
            "argv": [sys.executable, "-c", "print(" + repr(json.dumps([row])) + ")"],
            "basis": "bounded CPU fixture", "timeout_seconds": 5}}})
    try:
        result = RuntimeService(store).run_capability(request, CapabilityContext.from_task(task, store.root))
        assert result["status"] == "pass" and result["evidence"]
        assert result["outputs"]["execution"]["status"] == "complete"
    finally:
        store.release(lease)


def test_real_command_json_flows_into_quality_acceptance_via_bindings(tmp_path):
    """The process executes on CPU; measurements are explicitly synthetic."""
    import sys
    store = Store(tmp_path / "store")
    task = store.create({"schema_version": 1, "task_id": "comparison", "mode": "analyze",
                         "objective": "software execution bridge fixture", "context": {"fixture": "synthetic"},
                         "permissions": ["execute"], "budget": {"max_operations": 2, "max_seconds": 20}})
    identity = {"context": task["context"], "sample_fingerprint": "synthetic",
                "aggregation": "fixture-mean", "initial_state_fingerprint": "initial",
                "training_recipe_fingerprint": "fixture-recipe"}
    record = dict(identity, executed=3, steps=[1, 2, 3], loss=[2.0, 1.9, 1.8], candidate_path_exercised=True)
    correctness = {"context": task["context"], "executed": 3, "failures": 0,
                   "candidate_path_exercised": True, "profiler_off": True,
                   "measurement_protocol": {"scope": "synthetic", "max_relative_mad": 0.05}}
    document = {"baseline": record, "candidate": record, "correctness": correctness,
                "baseline_times": [10, 10, 10], "candidate_times": [9, 9, 9]}
    lease = store.lease("cpu-fixture", "controller", 30)
    steps = [{"id": "measure", "capability": "execution.command", "action": "run",
              "config": {"stdout_json": True}, "inputs": {"operation": "cpu-measure", "lease": lease,
              "card": {"schema_version": 1, "backend": "local", "cwd": str(tmp_path),
                       "argv": [sys.executable, "-c", "print(" + repr(json.dumps(document)) + ")"],
                       "basis": "synthetic CPU measurement document", "timeout_seconds": 5}}},
             {"id": "accept", "capability": "quality.accept", "action": "assess", "depends_on": ["measure"],
              "inputs": {"contract": dict(identity, min_steps=3, atol=0, rtol=0,
                                              tolerance_basis="exact synthetic fixture")},
              "bindings": {key: {"step": "measure", "path": ["document", key]} for key in document}}]
    try:
        result = RuntimeService(store).run_pipeline(plan(steps), CapabilityContext.from_task(task, store.root))
        assert result["status"] == "complete"
        accepted = result["steps"]["accept"]
        assert accepted["status"] == "pass" and accepted["outputs"]["stage_eligible"]
        raw_stdout = result["steps"]["measure"]["outputs"]["evidence"][0]
        assert raw_stdout in accepted["evidence"]
        assert json.loads(store.artifact(raw_stdout))["baseline_times"] == [10, 10, 10]
    finally:
        store.release(lease)


def test_same_run_cannot_be_dispatched_by_a_second_controller(tmp_path):
    store, cap, service, ctx = setup(tmp_path)
    def run(context, request):
        with pytest.raises(FlowError, match="controller is active"):
            service.run_pipeline(plan(), context)
        return CapabilityResult(cap.name, request.action, "pass")
    cap.callback = run
    assert service.run_pipeline(plan(), ctx)["status"] == "complete"
    assert len(cap.calls) == 1


def test_report_kind_without_evidence_is_skipped_not_fatal(tmp_path):
    store, cap, service, ctx = setup(tmp_path)
    task = store.create({"schema_version": 1, "task_id": "report-task", "objective": "fixture",
                         "context": {"model": "toy"}, "mode": "environment"})
    def run(context, request):
        return CapabilityResult(cap.name, request.action, "incomplete",
                                outputs={"status": "incomplete", "context": context.context})
    cap.callback = run
    document = plan([{"id": "a", "capability": cap.name, "config": {"report_kind": "environment"}}])
    result = service.run_pipeline(document, CapabilityContext.from_task(task, store.root))
    assert result["status"] == "incomplete"
    assert result["reports"] == {}
    with store.db() as db:
        row = db.execute("SELECT payload FROM events WHERE kind='pipeline-report-skipped'").fetchone()
    payload = json.loads(row["payload"])
    assert payload["step"] == "a" and payload["reason"] == "no-retained-evidence"
