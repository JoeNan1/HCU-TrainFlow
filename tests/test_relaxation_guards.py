"""A candidate may not widen the rules it is being judged by.

Each case here is a channel that was open: a threshold the candidate set
itself, a gate status that skipped the claims requirement, shadow mode that
turned a refused claim into ownership, a human-only question the Agent could
close, a profile the claims checker could not resolve, and a drift verdict the
CLI reported as success.
"""
import json
import tempfile
from pathlib import Path

import pytest

from hcu_trainflow import flow, integrity
from hcu_trainflow.cli import main
from hcu_trainflow.core import FlowError, Store

CONTEXT = {"source": "x", "engine": "megatron", "model_family": "llm"}


def workspace(tmp_path):
    store = Store(tmp_path)
    store.create({"schema_version": 1, "task_id": "t", "mode": "full", "objective": "o",
                  "context": dict(CONTEXT), "permissions": ["execute"]})
    return store


def started(tmp_path, plan=None):
    store = workspace(tmp_path)
    flow.start(store, "t", plan or {"acceptance": {"quality": "q"}})
    with store.db() as db:
        goal = flow.get_flow(db, "t")["goal"]
    return store, goal


def experiment(store, snapshot, evidence, **extra):
    context = store.task("t")["context"]
    document = {
        "context": context,
        "correctness": {"context": context, "executed": 3, "status": "pass",
                        "profiler_off": True, "measurement_protocol": "paired steady state",
                        "candidate_snapshot": snapshot, "evidence": [evidence],
                        "candidate_path_exercised": True},
        "baseline_times": [1.0, 1.0, 1.0], "candidate_times": [5.0, 5.0, 5.0],
    }
    document.update(extra)
    return store.put(json.dumps(document).encode())


def iteration_candidate(store, goal, snapshot, evidence, thresholds=None):
    artifact = experiment(store, snapshot, evidence, **(thresholds or {}))
    return {"author": "a", "context": store.task("t")["context"], "goal": goal,
            "snapshot": snapshot, "summary": "s", "reports": {}, "target": "iterate",
            "evidence": [artifact], "experiment": artifact}


def gate_reasons(store, candidate):
    with store.db() as db:
        return flow.gate(store, db, store.task("t"), candidate)


def test_a_candidate_cannot_declare_its_own_regression_budget(tmp_path):
    store, goal = started(tmp_path)
    snapshot = store.put(b'{"manifest": "m"}')
    evidence = store.put(b'{"t": 1}')
    honest = iteration_candidate(store, goal, snapshot, evidence)
    assert gate_reasons(store, honest) == ["iteration-not-kept"]
    cheat = iteration_candidate(store, goal, snapshot, evidence, {"max_regression": 1e9})
    assert gate_reasons(store, cheat) == ["experiment-declares-its-own-threshold"]


def test_the_plan_declares_the_regression_budget(tmp_path):
    store, goal = started(tmp_path, {"acceptance": {"quality": "q"}, "max_regression": 0.5})
    snapshot = store.put(b'{"manifest": "m"}')
    evidence = store.put(b'{"t": 1}')
    candidate = iteration_candidate(store, goal, snapshot, evidence)
    # A 1.4x slower candidate fits the declared 0.5 budget; the same shape at
    # 5x does not, which the previous test covers.
    document = json.loads(store.artifact(candidate["experiment"]))
    document["candidate_times"] = [1.4, 1.4, 1.4]
    candidate["experiment"] = store.put(json.dumps(document).encode())
    candidate["evidence"] = [candidate["experiment"]]
    assert gate_reasons(store, candidate) == []
    with pytest.raises(FlowError):
        flow.validate_plan({"acceptance": {"quality": "q"}, "max_regression": 5})


def test_complete_analysis_needs_claims_but_capability_reports_do_not(tmp_path):
    store = Store(tmp_path)
    store.create({"schema_version": 1, "task_id": "p", "mode": "full", "objective": "o",
                  "context": dict(CONTEXT), "permissions": ["execute"],
                  "profile": {"id": "llm-megatron", "reason": "r"}})
    proof = store.put(b'{"hotspot": "gemm", "executed": 1}')
    context = store.task("p")["context"]
    with pytest.raises(FlowError) as raised:
        store.report("p", "analysis", {"context": context, "status": "complete",
                                       "executed": 1, "evidence": [proof]})
    assert "claims" in str(raised.value).lower()
    # A capability-computed report is derived from typed inputs and is exempt.
    accepted = store.report("p", "analysis", {"context": context, "status": "complete",
                                              "executed": 1, "evidence": [proof]},
                            agent_authored=False)
    assert accepted["status"] == "complete"


def test_shadow_mode_does_not_launder_borrowed_evidence(tmp_path):
    store = Store(tmp_path)
    for tid in ("A", "B"):
        store.create({"schema_version": 1, "task_id": tid, "mode": "full", "objective": "o",
                      "context": dict(CONTEXT), "permissions": ["execute"],
                      **({"shadow_guardrails": True} if tid == "B" else {})})
    proof = store.put(b'{"k": 1}')
    store.report("A", "environment", {"context": store.task("A")["context"], "status": "pass",
                                      "executed": 1, "evidence": [proof]})
    assert store.artifact_tasks(proof) == {"A"}
    store.report("B", "environment", {"context": store.task("B")["context"], "status": "pass",
                                      "executed": 1, "evidence": [proof]}, shadow=True)
    assert store.artifact_tasks(proof) == {"A"}
    with pytest.raises(FlowError):
        store.report("B", "environment", {"context": store.task("B")["context"],
                                          "status": "pass", "executed": 1,
                                          "evidence": [proof]})


def test_an_authorization_question_cannot_be_self_resolved(tmp_path):
    store = Store(tmp_path)
    store.create({"schema_version": 1, "task_id": "t", "mode": "full", "objective": "o",
                  "context": dict(CONTEXT), "permissions": ["execute"],
                  "autonomy": {"mode": "autonomous", "reviewers": ["agent:r"],
                               "question_answers": []}})
    flow.start(store, "t", {"acceptance": {"quality": "q"}})
    flow.question(store, "t", {"id": "q-auth", "title": "Authorization",
                               "body": "new host and credential", "blocking": True})
    flow.question(store, "t", {"id": "q-plan", "title": "Which trace window",
                               "body": "step 40 or 60", "blocking": True})
    options = flow.next_step(store, "t")["options"]
    assert options["resolve_question"] == ["q-plan"]
    assert options["escalation_questions"] == [{"question": "q-auth", "category": "authorization"}]
    with pytest.raises(FlowError) as raised:
        flow.resolve_question(store, "t", "q-auth",
                              {"answer": "yes", "source": "policy", "note": "self granted"})
    assert "human decision" in str(raised.value)
    flow.resolve_question(store, "t", "q-plan",
                          {"answer": "step 40", "source": "policy", "note": "window chosen"})


def test_claims_fail_closed_on_an_unknown_profile(tmp_path):
    store = Store(tmp_path)
    store.create({"schema_version": 1, "task_id": "u", "mode": "full", "objective": "o",
                  "context": dict(CONTEXT), "permissions": ["execute"],
                  "profile": {"id": "no-such-profile", "reason": "r"}})
    proof = store.put(b'{"k": 1}')
    with pytest.raises(FlowError) as raised:
        store.report("u", "environment", {
            "context": store.task("u")["context"], "status": "pass", "executed": 1,
            "evidence": [proof],
            "claims": [{"id": "c", "statement": "s", "stage": "training",
                        "source": {"artifact": proof, "path": ["k"]}}]})
    assert "known profile" in str(raised.value)


def test_a_drift_verdict_is_not_a_success_exit_code(tmp_path):
    store, _ = started(tmp_path)
    with store.db() as db:  # a plan edited without a replan is exactly what drift means
        db.execute("UPDATE flows SET plan=? WHERE task='t'",
                   (json.dumps({"acceptance": {"quality": "different"}, **flow.DEFAULTS}),))
    assert flow.align(store, "t")["status"] == "drift"
    assert main(["--workspace", str(tmp_path), "flow-align", "t"]) == 2


def test_near_zero_claims_need_exact_equality(tmp_path):
    store = Store(tmp_path)
    store.create({"schema_version": 1, "task_id": "z", "mode": "full", "objective": "o",
                  "context": dict(CONTEXT), "permissions": ["execute"]})
    tiny = store.put(b'{"v": 5e-10}')
    zero = store.put(b'{"v": 0.0}')
    context = store.task("z")["context"]
    with pytest.raises(FlowError):
        store.report("z", "environment", {
            "context": context, "status": "pass", "executed": 1, "evidence": [tiny],
            "claims": [{"id": "c", "statement": "s", "value": 0.0,
                        "source": {"artifact": tiny, "path": ["v"]}}]})
    assert integrity._same(0.0, 0.0) and integrity._same(0, 0)
    assert not integrity._same(0.0, 5e-10)
