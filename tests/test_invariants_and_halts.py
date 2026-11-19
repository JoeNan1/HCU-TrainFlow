"""Budget ceilings, brief limits, halt hygiene and the remaining catalog edges."""
import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from hcu_trainflow import autopilot, flow, monitor
from hcu_trainflow.core import FlowError, Store

ROOT = Path(__file__).resolve().parents[1]
CONTEXT = {"source": "x", "engine": "megatron", "model_family": "llm"}


def make(tmp_path, *, budget=None, plan=None, autonomy=None, task_id="t"):
    store = Store(tmp_path)
    spec = {"schema_version": 1, "task_id": task_id, "mode": "full", "objective": "o",
            "context": dict(CONTEXT), "permissions": ["execute"]}
    if budget is not None:
        spec["budget"] = budget
    if autonomy is not None:
        spec["autonomy"] = autonomy
    store.create(spec)
    flow.start(store, task_id, plan or {"acceptance": {"quality": "q"}})
    return store


def test_invariants_report_the_effective_budget(tmp_path):
    policy = {"mode": "autonomous", "reviewers": ["agent:r"], "question_answers": [],
              "escalation": {"budget_extension": {"max_additions": 2,
                                                  "operations_per_addition": 4,
                                                  "hard_total_operations": 20}}}
    store = make(tmp_path, budget={"max_operations": 10, "max_seconds": 100}, autonomy=policy)
    before = flow.next_step(store, "t")["invariants"]["budget"]
    assert before == {"max_operations": 10, "max_seconds": 100}
    store.budget_extension("t", 4, 0, "extra work")
    after = flow.next_step(store, "t")["invariants"]["budget"]
    assert after["max_operations"] == 14
    assert flow.brief(store, "t")["budget"]["effective"]["max_operations"] == 14


def test_invariants_use_the_profile_budget_when_the_spec_has_none(tmp_path):
    store = Store(tmp_path)
    store.create({"schema_version": 1, "task_id": "t", "mode": "full", "objective": "o",
                  "context": dict(CONTEXT), "permissions": ["execute"],
                  "profile": {"id": "llm-megatron", "reason": "r"}})
    flow.start(store, "t", {"acceptance": {"quality": "q"}})
    with store.db() as db:
        effective = store.effective_budget(db, "t")
    shown = flow.next_step(store, "t")["invariants"]["budget"]
    assert shown["max_operations"] == effective["max_operations"]
    # An unbounded dimension is reported as null, never as a non-JSON infinity.
    assert shown["max_seconds"] is None


def test_the_brief_carries_the_loop_limits_and_they_invalidate_it(tmp_path):
    store = make(tmp_path, plan={"acceptance": {"quality": "q"}, "max_rounds": 20})
    brief = flow.brief(store, "t")
    assert brief["limits"]["max_rounds"] == 20
    token = brief["brief_hash"]
    flow.start(store, "t", {"acceptance": {"quality": "q"}, "max_rounds": 1},
               reason="the budget collapsed")
    assert flow.brief_token(store, "t") != token
    assert flow.brief(store, "t")["limits"]["max_rounds"] == 1


def test_the_round_budget_also_bounds_the_repair_loop(tmp_path):
    policy = {"mode": "autonomous", "reviewers": ["agent:r"], "question_answers": []}
    store = make(tmp_path, plan={"acceptance": {"quality": "q"}, "max_rounds": 2},
                 autonomy=policy)
    with store.db() as db:
        goal = flow.get_flow(db, "t")["goal"]
    snapshot = store.put(b'{"manifest": "m"}')
    evidence = store.put(b'{"t": 1}')

    def submit():
        flow.submit(store, "t", {"author": "a", "context": store.task("t")["context"],
                                 "goal": goal, "snapshot": snapshot, "summary": "s",
                                 "reports": {}, "target": "environment_checked",
                                 "evidence": [evidence]},
                    brief_hash=flow.brief_token(store, "t"))

    submit()
    assert flow.next_step(store, "t")["action"] == "repair"
    submit()
    decision = flow.next_step(store, "t")
    assert decision["action"] == "halt"
    assert decision["halt_reason"] == "round-budget-or-progress-plateau"
    with pytest.raises(FlowError):
        submit()


def test_a_driver_halt_carries_the_same_options_menu(tmp_path):
    policy = {"mode": "autonomous", "reviewers": ["agent:r"], "question_answers": [],
              "escalation": {"degrade_ladder": [{"action": "micro_batch_down", "min": 1}]}}
    store = make(tmp_path, autonomy=policy)

    class Worker:
        def work(self, store, tid, decision):
            return None

    result = autopilot.drive(store, "t", worker=Worker(), max_steps=2)
    assert result["status"] == "halt"
    assert result["options"] is not None
    assert [row["action"] for row in result["options"]["degrade"]] == ["micro_batch_down"]


def test_two_distinct_halts_produce_two_alerts(tmp_path):
    policy = {"mode": "autonomous", "reviewers": ["agent:r"], "question_answers": []}
    store = make(tmp_path, autonomy=policy)
    flow.question(store, "t", {"id": "q1", "title": "Q1", "body": "first", "blocking": True})
    assert autopilot.drive(store, "t", max_steps=2)["status"] == "halt"
    with store.db() as db:
        event = db.execute("SELECT event_id FROM events WHERE task='t' AND kind='flow-halted'"
                           " ORDER BY seq DESC LIMIT 1").fetchone()["event_id"]
    monitor.inbox(store, "claim", event_id=event, owner="watch")
    monitor.inbox(store, "complete", event_id=event, owner="watch")
    flow.resolve_question(store, "t", "q1", {"answer": "a", "source": "policy", "note": "done"})
    flow.question(store, "t", {"id": "q2", "title": "Q2", "body": "second", "blocking": True})
    assert autopilot.drive(store, "t", max_steps=2)["status"] == "halt"
    assert len(autopilot.halts(store)) == 1


def test_public_artifacts_stay_public_across_re_puts(tmp_path):
    store = Store(tmp_path)
    shared = store.put(b"shared baseline", visibility="public")
    assert store.artifact_public(shared)
    store.put(b"shared baseline", visibility="private")
    assert store.artifact_public(shared)


def test_the_audit_reads_report_bodies_in_full_and_leaves_no_side_files(tmp_path):
    store = make(tmp_path / "s")
    evidence = store.put(b'{"k": 1}')
    big = "x" * (9 * 1024 * 1024)
    store.report("t", "environment", {"context": store.task("t")["context"], "status": "pass",
                                      "executed": 1, "evidence": [evidence],
                                      "note": big})
    store_root = tmp_path / "s"
    before = sorted(p.name for p in store_root.iterdir())
    completed = subprocess.run([sys.executable, str(ROOT / "scripts" / "audit_report_history.py"),
                                str(store_root)], capture_output=True, text=True, cwd=ROOT)
    assert completed.returncode == 0, completed.stderr
    assert "0 flagged" in completed.stdout
    assert sorted(p.name for p in store_root.iterdir()) == before


def test_derive_accepts_a_profile_and_interface_ignores_member_order():
    catalog = importlib.import_module("hcu_trainflow.catalog")
    gates = importlib.import_module("hcu_trainflow.catalog.gates")
    entry = catalog.profile("llm-megatron")
    assert gates.derive(entry) == catalog.derived_gates(entry)
    assert gates.missing_producers(entry) == []
    first = catalog.interface(["quality.iteration", "optimization.netgain"])
    second = catalog.interface(["optimization.netgain", "quality.iteration"])
    assert first == second
    assert first["provides"]["performance"] == "iteration-verdict|performance-report"


def test_an_empty_stage_scope_is_refused():
    catalog = importlib.import_module("hcu_trainflow.catalog")
    with pytest.raises(catalog.ModuleContractError):
        catalog.select(modules=["environment.probe"], stages=[])
    with pytest.raises(catalog.ModuleContractError):
        catalog.select(profile="analysis-only", stages=["prepared"])
