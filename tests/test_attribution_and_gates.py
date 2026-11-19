"""Evidence ownership covers executions and pipeline steps, and a profile may
not derive a gate it cannot produce."""
import json
import tempfile
from pathlib import Path

import pytest

from hcu_trainflow import catalog, integrity
from hcu_trainflow.catalog.contracts import ModuleContractError, Profile
from hcu_trainflow.core import FlowError, Store

CONTEXT = {"source": "x", "engine": "megatron", "model_family": "llm"}


def store_with_tasks(tmp_path, *tids):
    store = Store(tmp_path)
    for tid in tids:
        store.create({"schema_version": 1, "task_id": tid, "mode": "full", "objective": "o",
                      "context": dict(CONTEXT), "permissions": ["execute"]})
    return store


def test_an_execution_result_confers_ownership(tmp_path):
    store = store_with_tasks(tmp_path, "A", "B")
    evidence = store.put(b'{"throughput": 1.0}')
    with store.db() as db:
        db.execute("INSERT INTO operations(id,task,request_hash,status,result,created)"
                   " VALUES(?,?,?,?,?,?)",
                   ("op-1", "A", "h", "finished", json.dumps({"evidence": [evidence]}), "t"))
    assert store.artifact_tasks(evidence) == {"A"}
    with pytest.raises(FlowError):
        store.report("B", "environment", {"context": store.task("B")["context"],
                                          "status": "pass", "executed": 1,
                                          "evidence": [evidence]})


def test_a_pipeline_step_result_confers_ownership(tmp_path):
    store = store_with_tasks(tmp_path, "A", "B")
    evidence = store.put(b'{"k": 2}')
    with store.db() as db:
        db.execute("INSERT INTO pipeline_runs(id,task,name,plan,context,revision,status,result,"
                   "created,updated) VALUES(?,?,?,?,?,?,?,?,?,?)",
                   ("r1", "A", "n", "{}", store.task("A")["context"], 0, "finished", "{}", "t", "t"))
        db.execute("INSERT INTO pipeline_steps(run,step,capability,action,status,artifact,report,"
                   "result,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?)",
                   ("r1", "s1", "c", "run", "passed", None, None,
                    json.dumps({"evidence": [evidence]}), "t", "t"))
    assert store.artifact_tasks(evidence) == {"A"}
    with pytest.raises(FlowError):
        store.report("B", "environment", {"context": store.task("B")["context"],
                                          "status": "pass", "executed": 1,
                                          "evidence": [evidence]})


def test_a_user_dropped_result_is_not_attributed(tmp_path):
    store = store_with_tasks(tmp_path, "A")
    evidence = store.put(b'{"k": 3}')
    with store.db() as db:
        db.execute("INSERT INTO operations(id,task,request_hash,status,result,created)"
                   " VALUES(?,?,?,?,?,?)", ("op-2", "A", "h", "failed", "not json", "t"))
    assert store.artifact_tasks(evidence) == set()


def test_a_profile_may_not_drop_a_gate_its_modules_cannot_produce():
    thin = Profile("thin-optimize", applies_to={"engine": ("torch",)},
                   modules=("quality.loss",), stages=("optimizing",))
    catalog.validate_scope(thin)
    with pytest.raises(ModuleContractError) as raised:
        catalog.derived_gates(thin)
    assert "performance" in str(raised.value)


def test_the_shipped_profiles_still_derive_their_gates():
    for name in ("llm-megatron", "torch-native-llm", "torch-native-vision"):
        assert catalog.compare_to_flow(catalog.derived_gates(name))["equal"], name


def test_a_task_with_a_thinning_profile_refuses_at_the_flow_boundary(tmp_path):
    """The Flow surfaces the catalog refusal as a FlowError, not a crash."""

    from hcu_trainflow import flow

    store = store_with_tasks(tmp_path, "T")
    thin = Profile("thin-optimize", applies_to={"engine": ("megatron",)},
                   modules=("quality.loss",), stages=("optimizing",))
    with pytest.raises(FlowError) as raised:
        # profile_gates derives through the catalog, which refuses this set.
        flow.profile_gates({"id": "T", "spec": {"profile": {"id": thin.id, "reason": "r"}}})
    assert "cannot satisfy" in str(raised.value) or "Unknown profile" in str(raised.value)
