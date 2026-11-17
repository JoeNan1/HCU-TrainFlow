"""module-run reuses the persistent runtime: same evidence rules, no new engine."""
import json

import pytest

from hcu_trainflow.capabilities import CapabilityRegistry
from hcu_trainflow.core import FlowError, Store
from hcu_trainflow.kernel import CapabilityResult, PipelinePlan, PipelineRunner
from hcu_trainflow.modular_cli import module_run
from hcu_trainflow.services import RuntimeService


def training_log():
    lines = ["  load ........... None", "  load_weights ........... False", "  profile ........... False"]
    for step in range(1, 13):
        lines.append(f"iteration {step}/12 | elapsed time per iteration (ms): 10 | lm loss: 2 | "
                     "number of skipped iterations: 0 | number of nan iterations: 0 |")
    for split in ("validation", "test"):
        lines.append(f"validation loss at iteration 12 on {split} set | lm loss value: 2.0 |")
    return "\n".join(lines) + "\n"


def setup(tmp_path):
    store = Store(tmp_path / "store")
    task = store.create({"schema_version": 1, "task_id": "module-run", "mode": "analyze",
                         "objective": "Module catalog integration", "context": {"source": "fixture"},
                         "permissions": ["execute"],
                         "budget": {"max_operations": 3, "max_seconds": 90}})
    log = store.put(training_log().encode())
    contract = {"context": task["context"], "expected_steps": 12, "steady_start": 3,
                "world_size": 1, "global_batch_size": 1, "seq_length": 16,
                "timing_groups": 3, "min_samples_per_group": 3}
    return store, task, log, contract


def test_module_run_registers_the_module_report(tmp_path):
    store, task, log, contract = setup(tmp_path)
    result = module_run(store, {"modules": ["training.summarize"],
                                "inputs": {"contract": contract, "execution": log}},
                        task_id=task["id"])
    assert result["status"] == "complete"
    assert result["modules"] == ["training.summarize"]
    assert result["gates"] is None
    assert list(result["reports"]) == ["training.summarize"]
    assert list(result["steps"]) == ["training.summarize"]
    assert result["steps"]["training.summarize"]["status"] == "pass"


def test_module_run_resumes_the_same_identity(tmp_path):
    store, task, log, contract = setup(tmp_path)
    document = {"modules": ["training.summarize"],
                "inputs": {"contract": contract, "execution": log}}
    first = module_run(store, document, task_id=task["id"])
    second = module_run(store, document, task_id=task["id"])
    assert first["run_id"] == second["run_id"]
    assert first["resumed"] is False and second["resumed"] is True


def test_torch_log_summary_registers_the_baseline_report(tmp_path):
    store, task, _, _ = setup(tmp_path)
    log = "\n".join([json.dumps({"kind": "meta", "fresh": True, "profiler": False})]
                    + [json.dumps({"step": step, "loss": 2.0, "seconds": 0.01})
                       for step in range(1, 13)]) + "\n"
    sha = store.put(log.encode())
    contract = {"context": task["context"], "expected_steps": 12, "steady_start": 3,
                "timing_groups": 3, "min_samples_per_group": 3,
                "log_format": {"kind": "jsonl"}}
    result = module_run(store, {"modules": ["training.summarize-torch"],
                                "inputs": {"contract": contract, "execution": sha}},
                        task_id=task["id"])
    assert result["status"] == "complete", result["steps"]
    assert result["steps"]["training.summarize-torch"]["status"] == "pass"
    assert list(result["reports"]) == ["training.summarize-torch"]


def test_module_run_refuses_a_plan_with_problems(tmp_path):
    store, task, _, _ = setup(tmp_path)
    with pytest.raises(FlowError):
        module_run(store, {"modules": ["training.summarize"]}, task_id=task["id"])


def test_module_run_records_no_report_for_a_module_without_one(tmp_path):
    store, task, log, _ = setup(tmp_path)
    measurements = store.put(json.dumps({"measurements": [{"node": "cpu"}]}).encode())
    result = module_run(store, {"modules": ["execution.stdout-json"],
                                "inputs": {"stdout_artifact": measurements}},
                        task_id=task["id"])
    assert result["status"] == "complete"
    assert result["reports"] == {}
    assert result["steps"]["execution.stdout-json"]["outputs"]["document"] == {
        "measurements": [{"node": "cpu"}]}
    # A stdout that is not JSON is an incomplete observation, never a silent pass.
    raw = module_run(store, {"modules": ["execution.stdout-json"],
                             "inputs": {"stdout_artifact": log}}, task_id=task["id"])
    assert raw["status"] == "incomplete"
    assert "parsing_error" in raw["steps"]["execution.stdout-json"]["outputs"]


class Counting:
    """Count invocations without leaving the capability contract."""

    name = "execution.stdout-json"
    calls = 0

    def actions(self):
        return ("parse", "run")

    def run(self, context, request):
        type(self).calls += 1
        return CapabilityResult(self.name, request.action, "complete",
                                outputs={"context": context.context, "status": "complete",
                                         "document": {}, "evidence": []})


def test_declared_volatility_replaces_the_legacy_whitelist(tmp_path):
    from hcu_trainflow.kernel import CapabilityContext
    for declared, expected in ((None, 1), ({"result"}, 2)):
        Counting.calls = 0
        store = Store(tmp_path / ("store-" + str(declared)))
        context = CapabilityContext("standalone", "ctx", store.root)
        service = RuntimeService(store, registry=CapabilityRegistry([Counting()]))
        plan = PipelinePlan.from_dict({"name": "volatile", "steps": [
            {"id": "result", "capability": "execution.stdout-json", "action": "parse",
             "inputs": {"stdout_artifact": "sha"}}]})
        for _ in range(2):
            kwargs = {} if declared is None else {"volatile_steps": declared}
            service.run_pipeline(plan, context, {}, **kwargs)
        assert Counting.calls == expected


def test_pipeline_runner_agrees_with_the_module_bindings(tmp_path):
    """The auto-wired plan executes through the ordinary runner unchanged."""

    from hcu_trainflow.capabilities import default_registry
    from hcu_trainflow.kernel import CapabilityContext
    from hcu_trainflow import catalog
    built = catalog.build_plan(modules=["profiling.summarize", "quality.qualify"],
                               inputs={"profile": {"status": "complete"},
                                       "normalized_artifact": "sha"})
    assert built["status"] == "incomplete"  # quality.qualify still needs its inputs
    plan = PipelinePlan.from_dict({key: built["plan"][key]
                                   for key in ("schema_version", "name", "steps")})
    result = PipelineRunner(default_registry()).run(
        plan, CapabilityContext("standalone", "ctx", tmp_path), {})
    assert set(result.steps) == {"profiling.summarize", "quality.qualify"}
    # The wiring reaches the capability: it rejects the incomplete profile
    # instead of silently skipping the consumer.
    assert result.steps["profiling.summarize"].status == "fail"
    assert result.steps["quality.qualify"].status == "blocked"
    json.dumps(result.to_dict())
