"""Drift is measured against the stored plan, not against what an agent recalls."""
import json

import pytest

from hcu_trainflow import flow, team
from hcu_trainflow.core import FlowError, Store

PROFILE = {"id": "llm-megatron", "reason": "megatron recipe"}
CONTEXT = {"source": "align", "engine": "megatron", "model_family": "llm"}


def setup(tmp_path, *, profile=PROFILE, mode="full", context=None, acceptance=None):
    store = Store(tmp_path / "w")
    spec = {"schema_version": 1, "task_id": "t", "mode": mode, "objective": "Align fixture",
            "context": dict(context or CONTEXT), "permissions": ["execute", "agent-dispatch"]}
    if profile is not None:
        spec["profile"] = profile
    store.create(spec)
    flow.start(store, "t", {"acceptance": acceptance or {"result": "Deliver evidence in scope"}})
    return store


def test_a_fresh_profile_task_is_aligned(tmp_path):
    store = setup(tmp_path)
    result = flow.align(store, "t")
    assert result["status"] == "aligned"
    assert result["deltas"] == []
    assert result["next"] == "continue"
    assert result["gates"]


def test_a_changed_acceptance_becomes_visible_drift(tmp_path):
    store = setup(tmp_path)
    flow.start(store, "t", {"acceptance": {"result": "Something narrower"}},
               reason="reduced scope for the fixture")
    result = flow.align(store, "t")
    assert result["status"] == "drift"
    kinds = [delta["kind"] for delta in result["deltas"]]
    assert "acceptance-changed-since-start" in kinds
    assert result["next"] == "flow-replan"
    with store.db() as db:
        events = [json.loads(row["payload"]) for row in
                  db.execute("SELECT payload FROM events WHERE task='t' AND kind='flow-aligned'")]
    assert events and events[-1]["deltas"]


def test_a_context_change_makes_the_declared_profile_stale(tmp_path):
    store = setup(tmp_path)
    store.change_context("t", {"source": "align", "engine": "torch", "model_family": "vision"})
    result = flow.align(store, "t")
    assert result["status"] == "drift"
    assert {"profile-context-mismatch"} & {delta["kind"] for delta in result["deltas"]}


def test_a_stage_outside_the_profile_is_reported(tmp_path):
    store = setup(tmp_path, profile={"id": "analysis-only", "reason": "read-only"},
                  mode="analyze", context={"source": "align", "engine": "megatron"},
                  acceptance={"result": "Explain the hotspot"})
    result = flow.align(store, "t")
    assert {"stage-outside-profile"} & {delta["kind"] for delta in result["deltas"]}


def test_brief_and_next_step_publish_the_same_invariants(tmp_path):
    store = setup(tmp_path)
    brief = flow.brief(store, "t")
    decision = flow.next_step(store, "t")
    assert brief["invariants"] == decision["invariants"]
    assert brief["invariants"]["acceptance_edit"] == "forbid"
    assert brief["invariants"]["review_required"] is True
    assert sorted(brief["invariants"]["gates"]) == sorted(decision["invariants"]["gates"])


def _lane(store):
    return team.plan(store, "t", {
        "rationale": "One lane hands its scope to the next",
        "max_parallel": 2,
        "assignments": [{"id": "a", "owner": "a-owner", "goal": "Probe the fixture",
                         "scope": "Read the fixed fixture evidence",
                         "allowed_paths": ["evidence"],
                         "acceptance": "Return supported findings", "mode": "read",
                         "budget": {"max_operations": 2, "max_seconds": 60},
                         "context": store.task("t")["context"]}]})


def _handoff(store, **changes):
    proof = store.put(b"handoff proof")
    body = {"id": "h1", "sender": "controller", "recipient": "a", "owner": "controller",
            "kind": "handoff", "body": "Continue the probe from this state",
            "context": store.task("t")["context"], "evidence": [proof],
            "handoff": {"brief_hash": flow.brief_token(store, "t"),
                        "evidence_ids": [proof], "open_questions": ["Which denominator?"]}}
    return {**body, **changes}


def test_handoff_carries_state_and_is_accepted(tmp_path):
    store = setup(tmp_path)
    _lane(store)
    assert team.send(store, "t", _handoff(store))["status"]


def test_handoff_without_its_structured_block_is_rejected(tmp_path):
    store = setup(tmp_path)
    _lane(store)
    message = _handoff(store)
    message.pop("handoff")
    with pytest.raises(FlowError) as excinfo:
        team.send(store, "t", message)
    assert "handoff" in str(excinfo.value).lower()


def test_handoff_brief_hash_must_be_a_brief(tmp_path):
    store = setup(tmp_path)
    _lane(store)
    broken = _handoff(store, handoff={"brief_hash": "short", "evidence_ids": [],
                                      "open_questions": []})
    with pytest.raises(FlowError):
        team.send(store, "t", broken)


def test_handoff_evidence_must_be_a_subset_of_what_it_cites(tmp_path):
    store = setup(tmp_path)
    _lane(store)
    message = _handoff(store)
    message["handoff"] = {**message["handoff"], "evidence_ids": ["f" * 64]}
    with pytest.raises(FlowError):
        team.send(store, "t", message)
