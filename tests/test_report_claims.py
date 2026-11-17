"""Claims are the one place a report states a number; they must resolve."""
import json

import pytest

from hcu_trainflow import flow, integrity
from hcu_trainflow.core import FlowError, Store

PROFILE = {"id": "llm-megatron", "reason": "megatron recipe"}
CONTEXT = {"source": "claims", "engine": "megatron", "model_family": "llm"}


def setup(tmp_path, profile=PROFILE):
    store = Store(tmp_path / "w")
    spec = {"schema_version": 1, "task_id": "t", "mode": "full", "objective": "claims",
            "context": dict(CONTEXT), "permissions": ["execute"]}
    if profile is not None:
        spec["profile"] = profile
    store.create(spec)
    flow.start(store, "t", {"acceptance": {"result": "Deliver evidence"}})
    return store


def record(store, **values):
    return store.put(json.dumps(values, sort_keys=True).encode())


def report(store, proof, claims=None, status="pass"):
    body = {"context": store.task("t")["context"], "status": status,
            "executed": 1, "evidence": [proof]}
    if claims is not None:
        body["claims"] = claims
    return store.report("t", "environment", body)


def claim(**values):
    body = {"id": "c1", "statement": "Environment verified", "stage": "environment_checked"}
    body.update(values)
    return body


def test_claim_needs_only_the_documented_fields(tmp_path):
    store = setup(tmp_path)
    proof = record(store, throughput=1234.0)
    with pytest.raises(FlowError):
        report(store, proof, [claim(extra="x")])
    with pytest.raises(FlowError):
        report(store, proof, [claim(id="")])
    with pytest.raises(FlowError):
        report(store, proof, [claim(statement="  ")])
    with pytest.raises(FlowError):
        report(store, proof, [claim(), claim()])
    with pytest.raises(FlowError):
        report(store, proof, [claim(source={"artifact": proof})])
    with pytest.raises(FlowError):
        report(store, proof, [claim(value=1)])
    assert report(store, proof, [claim()])["status"] == "pass"


def test_a_value_must_resolve_to_the_cited_path(tmp_path):
    store = setup(tmp_path)
    proof = record(store, metrics={"throughput": 1234.0})
    with pytest.raises(FlowError) as excinfo:
        report(store, proof, [claim(value=1234.0,
                                    source={"artifact": proof, "path": ["metrics", "missing"]})])
    assert "resolve" in str(excinfo.value)

    narrowed = claim(value=1234.0, source={"artifact": proof, "path": ["metrics", "throughput"]})
    assert report(store, narrowed and proof, [narrowed])["status"] == "pass"


def test_numeric_tolerance_is_relative_and_booleans_stay_distinct(tmp_path):
    store = setup(tmp_path)
    proof = record(store, throughput=1234.0, healthy=True)
    near = claim(value=1234.0 * (1 + 1e-12),
                 source={"artifact": proof, "path": ["throughput"]})
    assert report(store, proof, [near])["status"] == "pass"

    far = claim(value=1234.5, source={"artifact": proof, "path": ["throughput"]})
    with pytest.raises(FlowError):
        report(store, proof, [far])

    truthy = claim(value=1, source={"artifact": proof, "path": ["healthy"]})
    with pytest.raises(FlowError):
        report(store, proof, [truthy])


def test_a_legacy_task_may_still_report_without_claims(tmp_path):
    store = setup(tmp_path, profile=None)
    proof = record(store, stage="environment_checked")
    assert report(store, proof)["status"] == "pass"


def test_a_capability_computed_report_may_omit_claims(tmp_path):
    store = setup(tmp_path)
    proof = record(store, stage="environment_checked")
    body = {"context": store.task("t")["context"], "status": "pass", "executed": 1,
            "evidence": [proof]}
    assert store.report("t", "environment", body, agent_authored=False)["status"] == "pass"

    # The exemption is about who wrote it: claims it does state are still checked.
    drifted = {**body, "claims": [claim(value=1, source={"artifact": proof, "path": ["stage"]})]}
    with pytest.raises(FlowError):
        store.report("t", "environment", drifted, agent_authored=False)


def test_verify_rechecks_a_recorded_report(tmp_path):
    store = setup(tmp_path)
    proof = record(store, throughput=1234.0)
    report(store, proof, [claim(value=1234.0,
                                source={"artifact": proof, "path": ["throughput"]})])
    result = integrity.verify(store, "t", "environment")
    assert result["status"] == "pass"
    assert result["claims"] == 1
    with pytest.raises(FlowError):
        integrity.verify(store, "t", "baseline")


def test_shadow_mode_records_a_would_block_instead_of_refusing(tmp_path):
    store = Store(tmp_path / "w")
    store.create({"schema_version": 1, "task_id": "t", "mode": "full", "objective": "shadow",
                  "context": dict(CONTEXT), "permissions": ["execute"],
                  "profile": dict(PROFILE), "shadow_guardrails": True})
    flow.start(store, "t", {"acceptance": {"result": "Deliver evidence"}})
    proof = record(store, throughput=1234.0)
    body = {"context": store.task("t")["context"], "status": "pass", "executed": 1,
            "evidence": [proof]}  # no claims: refused normally
    with pytest.raises(FlowError):
        store.report("t", "environment", body)
    assert store.report("t", "environment", body, shadow=True)["status"] == "pass"
    findings = integrity.shadow_findings(store, "t")
    assert findings["status"] == "attention"
    assert "claims" in findings["findings"][0]["problems"][0]


def test_shadow_mode_must_be_declared_when_the_task_is_created(tmp_path):
    store = setup(tmp_path)  # no shadow_guardrails
    proof = record(store, stage="environment_checked")
    body = {"context": store.task("t")["context"], "status": "pass", "executed": 1, "evidence": [proof]}
    with pytest.raises(FlowError) as excinfo:
        store.report("t", "environment", body, shadow=True)
    assert "shadow_guardrails" in str(excinfo.value)


def test_a_report_cannot_declare_itself_capability_computed(tmp_path):
    """Only the runtime may set agent_authored; a body field changes nothing."""

    store = setup(tmp_path)
    proof = record(store, stage="environment_checked")
    body = {"context": store.task("t")["context"], "status": "pass", "executed": 1,
            "evidence": [proof], "agent_authored": False}
    with pytest.raises(FlowError) as excinfo:
        store.report("t", "environment", body)
    assert "claim" in str(excinfo.value)


def test_verify_lists_claims_that_point_at_nothing(tmp_path):
    store = setup(tmp_path)
    proof = record(store, stage="environment_checked")
    report(store, proof, [claim(), claim(id="c2", statement="Second conclusion")])
    result = integrity.verify(store, "t", "environment")
    assert result["claims"] == 2
    assert result["unbound"] == ["c1", "c2"]
    assert result["status"] == "pass"  # visible, not a refusal by itself
