"""Fault injection for the three failure modes: fabrication, context loss, drift.

Each case replays a small but complete task, then injects one fault that a
synthetic regression can otherwise not tell apart from real work. A case
"detects" the fault only when the guardrail refuses it; a silently accepted
fault is the failure this module exists to measure.
"""
import json

import pytest

from hcu_trainflow import flow
from hcu_trainflow.core import FlowError, Store

PROFILE = {"id": "llm-megatron", "reason": "megatron recipe with the standard gates"}
CONTEXT = {"source": "fixture", "engine": "megatron", "model_family": "llm"}
AUTONOMY = {"mode": "autonomous", "reviewers": ["agent:reviewer-1"]}


def setup(tmp_path, *, name="w", task_id="task", profile=PROFILE, mode="full",
          context=None, autonomy=None, acceptance=None):
    store = Store(tmp_path / name)
    spec = {"schema_version": 1, "task_id": task_id, "mode": mode,
            "objective": "Integrity fixture",
            "context": dict(context or CONTEXT),
            "permissions": ["execute"]}
    if profile is not None:
        spec["profile"] = profile
    if autonomy is not None:
        spec["autonomy"] = autonomy
    store.create(spec)
    flow.start(store, task_id, {"acceptance": acceptance or {"result": "Deliver evidence in scope"}})
    return store


def source(store, **values):
    """A retained JSON record a claim can point at."""

    return store.put(json.dumps(values, sort_keys=True).encode())


def pass_report(store, task_id, *, evidence, claims=None, snapshot=None):
    task = store.task(task_id)
    body = {"context": task["context"], "status": "pass", "executed": 3,
            "evidence": list(evidence)}
    if snapshot is not None:
        body["candidate_snapshot"] = snapshot
    if claims is not None:
        body["claims"] = claims
    return store.report(task_id, "environment", body)


def test_borrowed_evidence_is_rejected(tmp_path):
    store = setup(tmp_path, name="shared")
    owner = store.task("task")
    proof = store.put(b"owner-only proof")
    store.report("task", "environment", {
        "context": owner["context"], "status": "pass", "executed": 1, "evidence": [proof],
        "claims": [{"id": "own-1", "statement": "Owner environment verified",
                    "stage": "environment_checked",
                    "source": {"artifact": proof, "path": ["proof"]}}]})

    borrower = setup(tmp_path, name="shared", task_id="borrower",
                     context={"source": "second", "engine": "megatron", "model_family": "llm"})
    task = borrower.task("borrower")
    with pytest.raises(FlowError) as excinfo:
        borrower.report("borrower", "environment", {"context": task["context"], "status": "pass",
                                                    "executed": 1, "evidence": [proof]})
    assert "another task" in str(excinfo.value)


def test_a_public_artifact_may_be_shared_between_tasks(tmp_path):
    store = setup(tmp_path, name="shared-public")
    owner = store.task("task")
    shared = store.put(b"site-wide baseline", visibility="public")
    store.report("task", "environment", {
        "context": owner["context"], "status": "pass", "executed": 1, "evidence": [shared],
        "claims": [{"id": "own-1", "statement": "Environment verified",
                    "stage": "environment_checked",
                    "source": {"artifact": shared, "path": ["proof"]}}]})

    borrower = setup(tmp_path, name="shared-public", task_id="borrower",
                     context={"source": "second", "engine": "megatron", "model_family": "llm"})
    task = borrower.task("borrower")
    assert borrower.report("borrower", "environment", {
        "context": task["context"], "status": "pass", "executed": 1, "evidence": [shared],
        "claims": [{"id": "b-1", "statement": "Shared baseline reused",
                    "stage": "environment_checked",
                    "source": {"artifact": shared, "path": ["proof"]}}]})["status"] == "pass"


def test_claim_for_unserved_stage_is_rejected(tmp_path):
    store = setup(tmp_path, profile={"id": "analysis-only", "reason": "read-only analysis"},
                  mode="analyze", context={"source": "fixture", "engine": "megatron"},
                  acceptance={"result": "Explain the observed hotspot"})
    record = source(store, stage="training")
    with pytest.raises(FlowError) as excinfo:
        pass_report(store, "task", evidence=[record], claims=[
            {"id": "c1", "statement": "Long training converged", "stage": "training",
             "source": {"artifact": record, "path": ["stage"]}}])
    assert "stage" in str(excinfo.value)


def test_claim_outside_the_candidate_scope_is_rejected(tmp_path):
    store = setup(tmp_path)
    task = store.task("task")
    record = source(store, stage="environment_checked")
    other = flow.retain(store, {"source": "some-other-candidate"})
    with pytest.raises(FlowError) as excinfo:
        pass_report(store, "task", evidence=[record], snapshot=other, claims=[
            {"id": "c1", "statement": "Environment verified", "stage": "environment_checked",
             "candidate_snapshot": "f" * 64,
             "source": {"artifact": record, "path": ["stage"]}}])
    assert "snapshot" in str(excinfo.value)


def test_claim_value_must_match_its_source(tmp_path):
    store = setup(tmp_path)
    record = source(store, throughput=1234.0)
    good = {"id": "c1", "statement": "Throughput was 1234 tokens/s", "value": 1234.0,
            "source": {"artifact": record, "path": ["throughput"]}}
    pass_report(store, "task", evidence=[record], claims=[good])

    drifted = {"id": "c2", "statement": "Throughput was 1235 tokens/s", "value": 1235.0,
               "source": {"artifact": record, "path": ["throughput"]}}
    with pytest.raises(FlowError) as excinfo:
        pass_report(store, "task", evidence=[record], claims=[drifted])
    assert "value" in str(excinfo.value) or "match" in str(excinfo.value)


def test_pass_without_claims_is_rejected_for_a_profile_task(tmp_path):
    store = setup(tmp_path)
    record = source(store, stage="environment_checked")
    with pytest.raises(FlowError) as excinfo:
        pass_report(store, "task", evidence=[record])
    assert "claim" in str(excinfo.value)


def test_brief_rederives_constraints_instead_of_recalling_them(tmp_path):
    store = setup(tmp_path)
    brief = flow.brief(store, "task")
    task = store.task("task")
    destination = flow.target(task)
    assert brief["required_reports"] == flow.required_reports(task, destination)
    assert brief["invariants"]["gates"]
    assert brief["brief_hash"]
    assert brief["objective"].startswith("Integrity fixture")

    # A constraint carried in somebody's summary cannot narrow the gate: the
    # brief is rebuilt from the store, so editing the summary changes nothing.
    narrowed = flow.brief(store, "task", notes={"required_reports": ["nothing"]})
    assert narrowed["required_reports"] == brief["required_reports"]


def test_autonomous_turn_needs_a_fresh_brief(tmp_path):
    store = setup(tmp_path, autonomy=AUTONOMY)
    decision = flow.next_step(store, "task")
    record = source(store, stage="environment_checked")
    snapshot = flow.retain(store, {"source": "candidate-1"})
    candidate = {"author": "agent:worker", "context": store.task("task")["context"],
                 "goal": decision["goal"], "snapshot": snapshot, "summary": "candidate-1",
                 "reports": {}, "target": decision["target"], "evidence": [record]}

    with pytest.raises(FlowError) as missing:
        flow.submit(store, "task", candidate)
    assert "unverified-turn" in str(missing.value)

    fresh = flow.brief(store, "task")["brief_hash"]
    with pytest.raises(FlowError) as stale:
        flow.submit(store, "task", candidate, brief_hash="0" * 64)
    assert "stale-brief" in str(stale.value)

    outcome = flow.submit(store, "task", candidate, brief_hash=fresh)
    assert outcome["status"]
