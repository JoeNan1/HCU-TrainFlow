import json

import pytest

from hcu_trainflow import flow
from hcu_trainflow.capabilities import default_registry
from hcu_trainflow.core import FlowError, Store
from hcu_trainflow.kernel import CapabilityContext, PipelinePlan, PipelineRunner
from hcu_trainflow.modular_cli import pipeline_run


def quality_inputs():
    contract = {
        "context": "ctx",
        "sample_fingerprint": "samples",
        "aggregation": "fixed-token-mean",
        "min_steps": 3,
        "atol": 0.01,
        "rtol": 0,
        "tolerance_basis": "synthetic contract",
    }
    record = {
        "context": "ctx",
        "sample_fingerprint": "samples",
        "aggregation": "fixed-token-mean",
        "executed": 3,
        "evidence": ["synthetic-evidence"],
        "candidate_path_exercised": True,
        "steps": [1, 2, 3],
        "loss": [2.0, 1.9, 1.8],
    }
    return {"contract": contract, "baseline": record, "candidate": record}


def test_default_registry_exposes_independent_capabilities():
    names = default_registry().names()
    assert {
        "adaptation.proxy", "environment.check", "environment.occupancy",
        "execution.command", "observation.collect", "optimization.iteration",
        "profiling.analyze", "profiling.plan", "quality.iteration",
        "quality.loss", "quality.proxy", "scale.admission",
    } <= set(names)


def test_quality_capability_runs_without_flow_or_wiki(tmp_path):
    context = CapabilityContext("standalone", "ctx", tmp_path)
    request = {
        "action": "compare",
        "inputs": quality_inputs(),
    }
    from hcu_trainflow.kernel import CapabilityRequest
    result = default_registry().resolve("quality.loss").run(
        context, CapabilityRequest.from_dict(request, capability="quality.loss"))
    assert result.status == "pass"
    assert result.outputs["status"] == "pass"


def test_pipeline_plan_rejects_cycles():
    with pytest.raises(ValueError, match="cycle"):
        PipelinePlan.from_dict({
            "name": "cycle",
            "steps": [
                {"id": "a", "capability": "quality.loss", "depends_on": ["b"]},
                {"id": "b", "capability": "quality.loss", "depends_on": ["a"]},
            ],
        })


def test_pipeline_runner_propagates_results_and_blocks_failed_dependencies(tmp_path):
    context = CapabilityContext("standalone", "ctx", tmp_path)
    inputs = quality_inputs()
    plan = PipelinePlan.from_dict({
        "name": "quality-chain",
        "steps": [
            {"id": "quality", "capability": "quality.loss", "action": "compare"},
            {"id": "downstream", "capability": "quality.loss", "action": "compare",
             "depends_on": ["quality"]},
        ],
    })
    result = PipelineRunner(default_registry()).run(plan, context, inputs)
    assert result.status == "complete"
    assert result.steps["quality"].status == "pass"
    assert result.steps["downstream"].status == "pass"


def test_pipeline_result_is_json_serializable(tmp_path):
    context = CapabilityContext("standalone", "ctx", tmp_path)
    plan = PipelinePlan.from_dict({
        "name": "quality",
        "steps": [{"id": "quality", "capability": "quality.loss", "action": "compare"}],
    })
    result = PipelineRunner(default_registry()).run(plan, context, quality_inputs())
    json.dumps(result.to_dict(), ensure_ascii=False)


def test_pipeline_runner_orders_dependencies_independent_of_document_order(tmp_path):
    context = CapabilityContext("standalone", "ctx", tmp_path)
    plan = PipelinePlan.from_dict({
        "name": "reverse-quality",
        "steps": [
            {"id": "downstream", "capability": "quality.loss", "action": "compare",
             "depends_on": ["quality"]},
            {"id": "quality", "capability": "quality.loss", "action": "compare"},
        ],
    })
    result = PipelineRunner(default_registry()).run(plan, context, quality_inputs())
    assert result.status == "complete"
    assert all(result.steps[key].status == "pass" for key in ("quality", "downstream"))


def _full_task(store, task_id="pipeline-task"):
    task = store.create({
        "schema_version": 1,
        "task_id": task_id,
        "objective": "pipeline evidence",
        "context": {"model": "toy", "source": "fixture"},
        "mode": "full",
    })
    flow.start(store, task_id, {"acceptance": {"result": "pass"}})
    return task


def test_task_pipeline_registers_artifact_report_and_resumes(tmp_path):
    store = Store(tmp_path / "workspace")
    task = _full_task(store)
    evidence = store.put(b"raw health evidence")
    contract = {
        "required": [{"node": "node-a", "device": 0, "check": "ready", "conditions": {"driver": "ok"}}],
        "context": task["context"],
    }
    observations = [{
        "node": "node-a", "device": 0, "check": "ready", "conditions": {"driver": "ok"},
        "context": task["context"], "status": "pass", "executed": 1, "evidence": [evidence],
    }]
    request = tmp_path / "pipeline.json"
    request.write_text(json.dumps({
        "pipeline": {"name": "environment-evidence", "steps": [{
            "id": "environment", "capability": "environment.check", "action": "check",
            "config": {"report_kind": "environment"},
        }]},
        "inputs": {"contract": contract, "observations": observations},
    }), encoding="utf-8")

    first = pipeline_run(store, str(request), task["id"])
    second = pipeline_run(store, str(request), task["id"])

    assert first["status"] == "complete"
    assert first["artifacts"]["environment"]
    assert first["reports"]["environment"]
    assert second["resumed"] is True
    assert second["artifacts"] == first["artifacts"]
    state = store.pipeline_state(first["run_id"])
    assert state["status"] == "complete"
    assert state["steps"][0]["report"] == first["reports"]["environment"]
    with store.db() as db:
        reports = store.current_reports(db, task["id"], task["context"])
    assert reports["environment"]["artifact"] == first["reports"]["environment"]


def test_task_pipeline_is_invalidated_by_context_revision(tmp_path):
    store = Store(tmp_path / "workspace")
    task = _full_task(store, "revision-pipeline")
    evidence = store.put(b"raw health evidence")
    contract = {"required": [{"node": "node-a", "device": 0, "check": "ready", "conditions": {}}],
                "context": task["context"]}
    observations = [{"node": "node-a", "device": 0, "check": "ready", "conditions": {},
                     "context": task["context"], "status": "pass", "executed": 1,
                     "evidence": [evidence]}]
    request = tmp_path / "pipeline.json"
    request.write_text(json.dumps({
        "pipeline": {"name": "revision-bound", "steps": [{
            "id": "environment", "capability": "environment.check", "action": "check",
            "config": {"report_kind": "environment"},
        }]},
        "inputs": {"contract": contract, "observations": observations},
    }), encoding="utf-8")
    first = pipeline_run(store, str(request), task["id"])
    store.change_context(task["id"], {"model": "toy-v2", "source": "fixture"})
    with pytest.raises(FlowError, match="does not permit"):
        pipeline_run(store, str(request), task["id"])
    assert store.pipeline_state(first["run_id"])["status"] == "complete"


def test_task_pipeline_cannot_run_through_a_flow_gate(tmp_path):
    store = Store(tmp_path / "workspace")
    task = _full_task(store, "blocked-pipeline")
    flow.question(store, task["id"], {
        "id": "human-choice", "title": "Choose", "body": "Choose a baseline.", "blocking": True,
    })
    request = tmp_path / "pipeline.json"
    request.write_text(json.dumps({
        "pipeline": {"name": "blocked", "steps": [{"id": "quality", "capability": "quality.loss"}]},
        "inputs": quality_inputs(),
    }), encoding="utf-8")
    with pytest.raises(FlowError, match="does not permit"):
        pipeline_run(store, str(request), task["id"])

