"""Autonomous tasks change the decision source, never the evidence gates."""
import json
import sys

import pytest

from hcu_trainflow import autopilot, flow
from hcu_trainflow.cli import main
from hcu_trainflow.core import FlowError, Store


POLICY = {
    "mode": "autonomous",
    "reviewers": ["agent:reviewer-1"],
    "question_answers": [{
        "match": "baseline",
        "answer": "Use the frozen baseline retained in the task context.",
        "source": "policy:baseline-choice",
    }],
}


ESCALATION = {
    "degrade_ladder": [
        {"action": "micro_batch_down", "min": 1},
        {"action": "recompute_on", "allow": ["selective", "full"]},
        {"action": "rebalance_parallel", "allow": ["tp", "pp", "dp"]},
        {"action": "layers_down", "min_layers": 24, "record_scope_gap": True},
        {"action": "resume_from_checkpoint", "max_attempts": 2},
    ],
    "budget_extension": {"max_additions": 1, "operations_per_addition": 2,
                         "hard_total_operations": 6},
    "acceptance_edit": "forbid",
}


def setup(tmp_path, mode="full", task_id="t", autonomy=True, escalation=None, budget=None, **limits):
    store = Store(tmp_path / "workspace")
    spec = {"schema_version": 1, "task_id": task_id, "mode": mode,
            "objective": "Autonomous fixture", "context": {"source": "initial", "data": "frozen"},
            "permissions": ["execute", "agent-dispatch"]}
    if autonomy:
        policy = json.loads(json.dumps(POLICY))
        if escalation is not None:
            policy["escalation"] = escalation
        spec["autonomy"] = policy
    if budget is not None:
        spec["budget"] = budget
    store.create(spec)
    plan = {"acceptance": {"result": "Deliver evidence in the requested scope"}, **limits}
    flow.start(store, task_id, plan)
    return store


def candidate(store, task_id="t", label="candidate-1", reports=True):
    task = store.task(task_id)
    decision = flow.next_step(store, task_id)
    snap = flow.retain(store, {"source": label, "build": "fixture", "data": "frozen"})
    proof = store.put(("Synthetic fixture evidence: " + label).encode())
    destination = flow.target(task)
    bodies = {}
    if reports:
        for kind in flow.required_reports(task, destination):
            bodies[kind] = store.report(task_id, kind, {
                "context": task["context"], "candidate_snapshot": snap, "status": "pass",
                "executed": 3, "evidence": [proof]})["artifact"]
    return {"author": "agent:worker", "context": task["context"], "goal": decision["goal"],
            "snapshot": snap, "summary": label, "reports": bodies, "target": destination,
            "evidence": [proof]}


def send(store, value, task_id="t"):
    """Submit the way an autonomous run must: anchored to the current brief."""

    return flow.submit(store, task_id, value, brief_hash=flow.brief_token(store, task_id))


def verdict(store, task_id="t", reviewer="agent:reviewer-1", **changes):
    decision = flow.next_step(store, task_id)
    item = flow.artifact_json(store, decision["candidate"])
    value = {key: decision[key] for key in ("round", "candidate", "goal", "context")}
    value.update(reviewer=reviewer, verdict="accept",
                 summary="Reviewed retained evidence and the requested scope",
                 findings=[], acceptance={"result": "met"}, progress="advanced",
                 full_alignment=True, evidence=item["evidence"])
    return {**value, **changes}


@pytest.mark.parametrize("policy", [
    {"mode": "manual"},
    {"mode": "autonomous"},
    {"mode": "autonomous", "reviewers": []},
    {"mode": "autonomous", "reviewers": ["agent:r", "agent:r"]},
    {"mode": "autonomous", "reviewers": ["agent:r"], "auto_approve": True},
    {"mode": "autonomous", "reviewers": ["agent:r"], "question_answers": [{"match": "x"}]},
])
def test_spec_rejects_incomplete_or_open_ended_autonomy(tmp_path, policy):
    store = Store(tmp_path / "workspace")
    with pytest.raises(FlowError):
        store.create({"schema_version": 1, "task_id": "t", "mode": "full", "objective": "Fixture",
                      "context": {"source": "frozen"}, "autonomy": policy})


def test_autonomous_task_proceeds_while_a_manual_task_still_waits(tmp_path):
    store = setup(tmp_path)
    assert flow.autonomy(store.task("t"))["mode"] == "autonomous"
    assert flow.next_step(store, "t")["action"] == "work"

    manual = setup(tmp_path / "manual", task_id="m", autonomy=False)
    flow.question(manual, "m", {"id": "q", "title": "Need a choice", "body": "Decide.", "blocking": True})
    assert flow.next_step(manual, "m")["action"] == "human"


def test_collected_guidance_is_advisory_and_cannot_block(tmp_path):
    store = setup(tmp_path)
    flow.board_paths(store, "t")[2].write_text("# Human guidance\n\nKeep the agreed scope.\n", encoding="utf8")
    flow.sync_guidance(store, "t", force=True)

    assert flow.next_step(store, "t")["action"] == "work"
    with store.db() as db:
        row = db.execute("SELECT status,note FROM flow_guidance WHERE task='t' AND status!='template'").fetchone()
        event = db.execute("SELECT payload FROM events WHERE kind='human-guidance-acknowledged'"
                           " ORDER BY seq DESC").fetchone()
    assert row["status"] == "not-applicable"
    payload = json.loads(event["payload"])
    assert payload["actor"] == flow.AUTONOMY_ACTOR and payload["decision"] == "not-applicable"


def test_chat_guidance_is_retained_without_waiting(tmp_path):
    from hcu_trainflow import chat_guidance
    store = setup(tmp_path)
    chat_guidance.record(store, "t", {"text": "Please keep the unexplained gap visible.",
                                      "source": "chat:msg-1", "author": "human-user"})

    assert flow.next_step(store, "t")["action"] == "work"
    with store.db() as db:
        assert db.execute("SELECT 1 FROM flow_guidance WHERE task='t'"
                          " AND status IN ('pending','needs-human','queued')").fetchone() is None


def test_unanswered_blocking_question_halts_with_a_reason(tmp_path):
    store = setup(tmp_path)
    flow.question(store, "t", {"id": "q-topology", "title": "Which fabric?",
                               "body": "Choose the inter-node topology.", "blocking": True})

    decision = flow.next_step(store, "t")
    assert decision["action"] == "halt"
    assert decision["halt_reason"].startswith("blocking-human-question")
    with store.db() as db:
        assert db.execute("SELECT status FROM flow_questions WHERE id='q-topology'").fetchone()["status"] == "open"


def test_declared_answer_closes_the_question_and_keeps_going(tmp_path):
    store = setup(tmp_path)
    flow.question(store, "t", {"id": "q-baseline", "title": "Which baseline?",
                               "body": "Pick the frozen baseline.", "blocking": True})

    assert flow.next_step(store, "t")["action"] == "work"
    with store.db() as db:
        row = db.execute("SELECT status,resolution FROM flow_questions WHERE id='q-baseline'").fetchone()
    assert row["status"] == "closed"
    answer = json.loads(store.artifact(json.loads(row["resolution"])["guidance"]))
    assert answer["kind"] == "autonomy-question-answer"
    assert answer["actor"] == flow.AUTONOMY_ACTOR and answer["source"] == "policy:baseline-choice"


def test_agent_decision_resolves_an_uncovered_question(tmp_path):
    store = setup(tmp_path)
    flow.question(store, "t", {"id": "q-topology", "title": "Which fabric?",
                               "body": "Choose the inter-node topology.", "blocking": True})
    assert flow.next_step(store, "t")["action"] == "halt"

    result = flow.resolve_question(store, "t", "q-topology", {
        "answer": "Use the 8-node fabric retained in the site contract.",
        "source": "agent:coordinator", "note": "No declared policy answer; recorded as an agent decision."})
    assert result["status"] == "closed" and result["changed"] is True
    assert flow.next_step(store, "t")["action"] == "work"
    with store.db() as db:
        row = db.execute("SELECT status,resolution FROM flow_questions WHERE id='q-topology'").fetchone()
        event = db.execute("SELECT payload FROM events WHERE kind='human-question-resolved'"
                           " ORDER BY seq DESC").fetchone()
    decision = json.loads(store.artifact(json.loads(row["resolution"])["guidance"]))
    assert row["status"] == "closed"
    assert decision["kind"] == "autonomy-agent-decision" and decision["actor"] == flow.AUTONOMY_ACTOR
    assert decision["source"] == "agent:coordinator"
    assert json.loads(event["payload"])["actor"] == flow.AUTONOMY_ACTOR


@pytest.mark.parametrize("value", [
    {},
    {"answer": "a", "source": "s"},
    {"answer": "a", "source": "s", "note": " "},
    {"answer": "a", "source": "s", "note": "n", "extra": 1},
])
def test_resolution_requires_complete_attribution(tmp_path, value):
    store = setup(tmp_path)
    flow.question(store, "t", {"id": "q-topology", "title": "Which fabric?",
                               "body": "Choose.", "blocking": True})
    with pytest.raises(FlowError):
        flow.resolve_question(store, "t", "q-topology", value)
    with store.db() as db:
        assert db.execute("SELECT status FROM flow_questions WHERE id='q-topology'").fetchone()["status"] == "open"


def test_question_resolution_requires_an_autonomous_policy(tmp_path):
    store = setup(tmp_path, autonomy=False)
    flow.question(store, "t", {"id": "q-topology", "title": "Which fabric?",
                               "body": "Choose.", "blocking": True})
    with pytest.raises(FlowError, match="Only autonomous tasks"):
        flow.resolve_question(store, "t", "q-topology", {
            "answer": "a", "source": "agent:coordinator", "note": "n"})


def test_review_must_come_from_the_declared_pool(tmp_path):
    store = setup(tmp_path)
    send(store, candidate(store))
    with pytest.raises(FlowError, match="declared reviewer pool"):
        flow.review(store, "t", verdict(store, reviewer="agent:stranger"))
    # The declared reviewer is still accepted afterwards on the same round.
    assert flow.review(store, "t", verdict(store))["status"] == "accepted"
    assert flow.next_step(store, "t")["action"] == "advance"


def test_review_failure_budget_halts_instead_of_waiting(tmp_path):
    store = setup(tmp_path, max_review_failures=1)
    send(store, candidate(store))
    with pytest.raises(FlowError):
        flow.review(store, "t", {})

    decision = flow.next_step(store, "t")
    assert decision["action"] == "halt" and "review-failures" in decision["reasons"]


def test_round_budget_halts_after_the_declared_budget(tmp_path):
    store = setup(tmp_path, max_rounds=1)
    send(store, candidate(store))
    flow.review(store, "t", verdict(store))
    decision = flow.next_step(store, "t")
    while decision["action"] == "advance":
        flow.advance(store, "t")
        decision = flow.next_step(store, "t")
    assert decision["action"] == "halt"
    assert "round-budget-or-progress-plateau" in decision["reasons"]


def test_halted_autonomous_task_cannot_keep_executing(tmp_path):
    store = setup(tmp_path, max_review_failures=1)
    send(store, candidate(store))
    with pytest.raises(FlowError):
        flow.review(store, "t", {})
    assert flow.next_step(store, "t")["action"] == "halt"
    with pytest.raises(FlowError, match="Resolve flow decision"):
        flow.guard_execution(store, "t")


def test_autonomy_cannot_pass_a_missing_report(tmp_path):
    store = setup(tmp_path)
    result = send(store, candidate(store, reports=False))
    assert result["status"] == "needs-repair"
    assert any("missing-or-replaced-report:environment" in reason for reason in result["reasons"])
    assert flow.next_step(store, "t")["action"] == "repair"


def test_drive_advances_an_accepted_round_without_a_person(tmp_path):
    store = setup(tmp_path)
    send(store, candidate(store))
    flow.review(store, "t", verdict(store))

    result = autopilot.drive(store, "t")
    assert result["action"] == "work"
    assert result["advanced"][0] == {"from": "prepared", "to": "environment_checked"}
    assert store.task("t")["state"] == "environment_checked"


def test_halt_is_recorded_and_exits_nonzero(tmp_path, capsys):
    store = setup(tmp_path)
    flow.question(store, "t", {"id": "q-topology", "title": "Which fabric?",
                               "body": "Choose the inter-node topology.", "blocking": True})

    result = autopilot.drive(store, "t")
    assert result["status"] == "halt" and result["halt_reason"].startswith("blocking-human-question")
    with store.db() as db:
        payload = json.loads(db.execute("SELECT payload FROM events WHERE kind='flow-halted'").fetchone()["payload"])
    assert payload["state"] == "prepared" and payload["autonomy"]["mode"] == "autonomous"

    assert main(["--workspace", str(store.root), "flow-drive", "t"]) == 2
    assert '"halt"' in capsys.readouterr().out


def test_drive_refuses_a_human_channel_task(tmp_path):
    store = setup(tmp_path, autonomy=False)
    with pytest.raises(FlowError, match="does not declare"):
        autopilot.drive(store, "t")


def test_stop_report_retains_reason_and_evidence(tmp_path):
    store = setup(tmp_path)
    proof = store.put(b"final retained evidence")

    result = autopilot.stop_report(store, "t", "budget exhausted before the scale stage", [proof])
    body = json.loads(store.artifact(result["artifact"]))
    assert body["reason"].startswith("budget exhausted")
    assert body["evidence"] == [proof] and body["actor"] == flow.AUTONOMY_ACTOR


@pytest.mark.parametrize("escalation", [
    {"degrade_ladder": []},
    {"degrade_ladder": [{"action": "unknown_step"}]},
    {"degrade_ladder": [{"action": "micro_batch_down"}]},
    {"degrade_ladder": [{"action": "micro_batch_down", "min": 0}]},
    {"degrade_ladder": [{"action": "micro_batch_down", "min": 1}, {"action": "micro_batch_down", "min": 2}]},
    {"degrade_ladder": [{"action": "recompute_on", "allow": []}]},
    {"degrade_ladder": [{"action": "layers_down", "min_layers": 24, "record_scope_gap": "yes"}]},
    {"budget_extension": {"max_additions": 1}},
    {"budget_extension": {"max_additions": 1, "operations_per_addition": 2,
                          "hard_total_operations": 1}},
    {"acceptance_edit": "relax-anything"},
    {"auto_approve": True},
])
def test_spec_rejects_unbounded_escalation(tmp_path, escalation):
    store = Store(tmp_path / "workspace")
    with pytest.raises(FlowError):
        store.create({"schema_version": 1, "task_id": "t", "mode": "full", "objective": "Fixture",
                      "context": {"source": "frozen"},
                      "autonomy": {"mode": "autonomous", "reviewers": ["agent:r"],
                                   "escalation": escalation}})


def test_degrade_ladder_applies_only_declared_steps(tmp_path):
    store = setup(tmp_path, escalation=ESCALATION)
    assert flow.degradation_state(store, "t")["remaining"][0] == "micro_batch_down"
    with pytest.raises(FlowError, match="not declared"):
        flow.record_degradation(store, "t", "drop_everything", "reason")
    with pytest.raises(FlowError, match="floor"):
        flow.record_degradation(store, "t", "micro_batch_down", "oom", {"micro_batch": 0})
    with pytest.raises(FlowError, match="undeclared fields"):
        flow.record_degradation(store, "t", "micro_batch_down", "oom", {"micro_batch": 2, "layers": 1})

    recorded = flow.record_degradation(store, "t", "micro_batch_down", "OOM at step 12", {"micro_batch": 2})
    assert recorded["evidence"] and recorded["used"]["micro_batch_down"] == 1
    assert "micro_batch_down" not in recorded["remaining"]

    with pytest.raises(FlowError, match="scope gap"):
        flow.record_degradation(store, "t", "layers_down", "oom", {"layers": 24})
    flow.record_degradation(store, "t", "layers_down", "oom", {"layers": 24, "scope_gap": "proxy 24/32 layers"})
    with pytest.raises(FlowError, match="recompute mode"):
        flow.record_degradation(store, "t", "recompute_on", "oom", {"recompute": "off"})
    flow.record_degradation(store, "t", "recompute_on", "oom", {"recompute": "selective"})
    flow.record_degradation(store, "t", "resume_from_checkpoint", "node lost")
    flow.record_degradation(store, "t", "resume_from_checkpoint", "node lost again")
    with pytest.raises(FlowError, match="exhausted its declared attempts"):
        flow.record_degradation(store, "t", "resume_from_checkpoint", "a third time")

    artifact = json.loads(store.artifact(recorded["evidence"]))
    assert artifact["kind"] == "autonomy-degradation" and artifact["actor"] == flow.AUTONOMY_ACTOR


def test_degradation_requires_an_autonomous_policy(tmp_path):
    store = setup(tmp_path, autonomy=False)
    with pytest.raises(FlowError, match="Only autonomous tasks"):
        flow.record_degradation(store, "t", "micro_batch_down", "oom", {"micro_batch": 2})


def test_graded_budget_extension_is_enforced_at_execution(tmp_path):
    escalation = {"budget_extension": {"max_additions": 1, "operations_per_addition": 2,
                                       "hard_total_operations": 3}}
    store = setup(tmp_path, mode="environment", task_id="b", escalation=escalation,
                  budget={"max_operations": 1, "max_seconds": 60})
    lease = store.lease("cpu-fixture", "controller", ttl=30)
    card = {"schema_version": 1, "backend": "local", "cwd": str(tmp_path),
            "argv": [sys.executable, "-c", "print(1)"], "basis": "budget fixture",
            "timeout_seconds": 5}
    from hcu_trainflow.execution import run_command

    run_command(store, "b", "op-1", card, lease)
    with pytest.raises(FlowError, match="budget exhausted"):
        run_command(store, "b", "op-2", card, lease)

    extended = store.budget_extension("b", 2, 0, "second short baseline after the first was invalidated")
    assert extended["budget"]["max_operations"] == 3 and extended["remaining_additions"] == 0
    run_command(store, "b", "op-2", card, lease)
    with store.db() as db:
        payload = json.loads(db.execute("SELECT payload FROM events WHERE kind='budget-extended'").fetchone()["payload"])
    assert payload["operations"] == 2 and payload["actor"] == "autonomy-policy"
    store.release(lease)


def test_budget_extension_respects_ceiling_allowance_and_policy(tmp_path):
    escalation = {"budget_extension": {"max_additions": 1, "operations_per_addition": 2,
                                       "hard_total_operations": 5}}
    store = setup(tmp_path, escalation=escalation, budget={"max_operations": 4, "max_seconds": 60})
    with pytest.raises(FlowError, match="hard operations ceiling"):
        store.budget_extension("t", 2, 0, "would exceed")
    assert store.budget_extension("t", 1, 0, "small top-up")["budget"]["max_operations"] == 5
    with pytest.raises(FlowError, match="allowance is exhausted"):
        store.budget_extension("t", 1, 0, "again")
    with pytest.raises(FlowError, match="per-addition"):
        store.budget_extension("t", 3, 0, "too many")
    with pytest.raises(FlowError, match="blocking reason"):
        store.budget_extension("t", 1, 0, "  ")

    plain = setup(tmp_path / "plain", task_id="p")
    with pytest.raises(FlowError, match="does not authorize"):
        plain.budget_extension("p", 1, 0, "no policy")


def test_acceptance_cannot_be_weakened_by_autonomous_replan(tmp_path):
    store = setup(tmp_path)
    with pytest.raises(FlowError, match="acceptance criteria"):
        flow.start(store, "t", {"acceptance": {"result": "Anything at all"}}, "trying to relax")
    # An unchanged objective with a different loop budget is still a valid replan.
    flow.start(store, "t", {"acceptance": {"result": "Deliver evidence in the requested scope"},
                            "max_rounds": 10}, "tighten the loop budget")


def test_acceptance_add_only_policy_permits_new_criteria_only(tmp_path):
    store = setup(tmp_path, escalation={"acceptance_edit": "add-only"})
    flow.start(store, "t", {"acceptance": {"result": "Deliver evidence in the requested scope",
                                           "extra": "Also retain raw logs"}}, "add a criterion")
    with pytest.raises(FlowError, match="acceptance criteria"):
        flow.start(store, "t", {"acceptance": {"result": "Weaker", "extra": "Also retain raw logs"},
                                "max_rounds": 10}, "relax the goal")


def test_manual_task_may_still_replan_acceptance(tmp_path):
    store = setup(tmp_path, autonomy=False)
    flow.start(store, "t", {"acceptance": {"result": "Changed by a person"}}, "person changed the goal")
    with store.db() as db:
        assert flow.get_flow(db, "t")["plan"]["acceptance"] == {"result": "Changed by a person"}


class RecordingWorker:
    """Minimal worker: one evidence-backed candidate and one accepted review."""

    def __init__(self):
        self.calls = []

    def work(self, store, tid, decision):
        self.calls.append('work')
        task = store.task(tid)
        snap = flow.retain(store, {'label': 'worker-snapshot'})
        proof = store.put(b'worker evidence')
        report = store.report(tid, 'analysis', {
            'context': task['context'], 'candidate_snapshot': snap,
            'status': 'complete', 'executed': 1, 'evidence': [proof]})['artifact']
        return {'author': 'agent:worker', 'context': task['context'], 'goal': decision['goal'],
                'snapshot': snap, 'summary': 'worker candidate', 'reports': {'analysis': report},
                'target': 'completed', 'evidence': [proof]}

    def review(self, store, tid, decision):
        self.calls.append('review')
        item = flow.artifact_json(store, decision['candidate'])
        value = {key: decision[key] for key in ('round', 'candidate', 'goal', 'context')}
        value.update(reviewer='agent:reviewer-1', verdict='accept', summary='worker-reviewed evidence',
                     findings=[], acceptance={'result': 'met'}, progress='advanced',
                     full_alignment=True, evidence=item['evidence'])
        return value


def test_worker_drives_a_task_to_completion(tmp_path):
    store = setup(tmp_path, mode='analyze', task_id='a')
    worker = RecordingWorker()
    result = autopilot.drive(store, 'a', worker=worker)
    assert result['status'] == 'completed'
    assert result['worker']['submits'] == 1 and result['worker']['reviews'] == 1
    assert worker.calls == ['work', 'review']
    assert store.task('a')['state'] == 'completed'


def test_worker_declining_or_crashing_halts_with_a_reason(tmp_path):
    store = setup(tmp_path, mode='analyze', task_id='decline')
    class Declining:
        def work(self, store, tid, decision):
            return None
    result = autopilot.drive(store, 'decline', worker=Declining())
    assert result['status'] == 'halt' and result['halt_reason'] == 'worker-declined:work'

    crashing = setup(tmp_path / 'crash', mode='analyze', task_id='crash')
    class Crashing:
        def work(self, store, tid, decision):
            raise RuntimeError('worker bug')
    result = autopilot.drive(crashing, 'crash', worker=Crashing(), max_worker_errors=1)
    assert result['status'] == 'halt' and result['halt_reason'] == 'worker-error:RuntimeError'
    with crashing.db() as db:
        assert json.loads(db.execute("SELECT payload FROM events WHERE kind='worker-error'").fetchone()['payload'])['action'] == 'work'


def test_worker_handoff_stops_with_its_own_reason(tmp_path):
    store = setup(tmp_path, mode='analyze', task_id='handoff')
    class Handing:
        def work(self, store, tid, decision):
            raise autopilot.Handoff('need a new site authorization')
    result = autopilot.drive(store, 'handoff', worker=Handing())
    assert result['status'] == 'halt'
    assert result['reasons'] == ['worker-handoff', 'need a new site authorization']


def test_halt_alerts_are_queued_and_cleared_through_the_inbox(tmp_path):
    store = setup(tmp_path)
    flow.question(store, 't', {'id': 'q-topology', 'title': 'Which fabric?',
                               'body': 'Choose.', 'blocking': True})
    autopilot.drive(store, 't')

    alerts = autopilot.halts(store)
    assert len(alerts) == 1 and alerts[0]['task'] == 't' and alerts[0]['status'] == 'pending'
    from hcu_trainflow import monitor
    assert monitor.inbox(store, 'claim', alerts[0]['event'], 'watcher')['status'] == 'claimed'
    monitor.inbox(store, 'complete', alerts[0]['event'], 'watcher')
    assert autopilot.halts(store) == []
    assert len(autopilot.halts(store, include_delivered=True)) == 1

    assert main(['--workspace', str(store.root), 'halt-list']) == 0


def test_cli_drive_uses_an_external_worker_module(tmp_path, monkeypatch):
    store = setup(tmp_path, mode='analyze', task_id='cli-worker')
    module = tmp_path / 'cli_worker_mod.py'
    module.write_text(
        "from hcu_trainflow import flow\n"
        "class Worker:\n"
        "    def work(self, store, tid, decision):\n"
        "        task = store.task(tid)\n"
        "        snap = flow.retain(store, {'label': 'cli-worker'})\n"
        "        proof = store.put(b'cli worker evidence')\n"
        "        report = store.report(tid, 'analysis', {'context': task['context'],"
        " 'candidate_snapshot': snap, 'status': 'complete', 'executed': 1,"
        " 'evidence': [proof]})['artifact']\n"
        "        return {'author': 'agent:worker', 'context': task['context'],"
        " 'goal': decision['goal'], 'snapshot': snap, 'summary': 'cli worker candidate',"
        " 'reports': {'analysis': report}, 'target': 'completed', 'evidence': [proof]}\n"
        "    def review(self, store, tid, decision):\n"
        "        item = flow.artifact_json(store, decision['candidate'])\n"
        "        value = {k: decision[k] for k in ('round', 'candidate', 'goal', 'context')}\n"
        "        value.update(reviewer='agent:reviewer-1', verdict='accept',"
        " summary='cli worker review', findings=[], acceptance={'result': 'met'},"
        " progress='advanced', full_alignment=True, evidence=item['evidence'])\n"
        "        return value\n"
        "def build(store, tid):\n"
        "    return Worker()\n", encoding='utf-8')
    monkeypatch.syspath_prepend(str(tmp_path))
    assert main(['--workspace', str(store.root), 'flow-drive', 'cli-worker',
                 '--worker', 'cli_worker_mod:build']) == 0
    assert store.task('cli-worker')['state'] == 'completed'


def test_worker_that_never_converges_halts_before_burning_the_budget(tmp_path):
    store = setup(tmp_path, mode='analyze', task_id='loop')
    class Broken:
        def work(self, store, tid, decision):
            task = store.task(tid)
            snap = flow.retain(store, {'label': 'broken'})
            proof = store.put(b'broken evidence')
            # No reports: the gate rejects it every time.
            return {'author': 'agent:worker', 'context': task['context'], 'goal': decision['goal'],
                    'snapshot': snap, 'summary': 'broken candidate', 'reports': {},
                    'target': 'completed', 'evidence': [proof]}
    result = autopilot.drive(store, 'loop', worker=Broken(), max_worker_errors=2)
    assert result['status'] == 'halt' and result['halt_reason'] == 'repair-not-converging'
    assert result['worker']['submits'] == 2


def test_halt_carries_the_declared_options_menu(tmp_path):
    store = setup(tmp_path, escalation=ESCALATION, budget={"max_operations": 2, "max_seconds": 60})
    flow.question(store, 't', {'id': 'q-topology', 'title': 'Which fabric?',
                               'body': 'Choose.', 'blocking': True})
    decision = flow.next_step(store, 't')
    options = decision['options']
    assert [row['action'] for row in options['degrade']] == [
        'micro_batch_down', 'recompute_on', 'rebalance_parallel', 'layers_down', 'resume_from_checkpoint']
    assert options['degrade'][0]['used'] == 0 and options['degrade'][0]['min'] == 1
    assert options['resolve_question'] == ['q-topology']
    assert options['budget_extension'] == {'remaining_additions': 1, 'operations_per_addition': 2,
                                          'operations_until_hard_ceiling': 4}
    assert any(entry.startswith('authorization:') for entry in options['must_escalate'])


def test_halt_options_shrink_once_the_policy_is_spent(tmp_path):
    escalation = {'degrade_ladder': [{'action': 'resume_from_checkpoint', 'max_attempts': 1}],
                  'budget_extension': {'max_additions': 1, 'operations_per_addition': 2,
                                       'hard_total_operations': 4}}
    store = setup(tmp_path, escalation=escalation, budget={'max_operations': 2, 'max_seconds': 60})
    flow.question(store, 't', {'id': 'q', 'title': 'Which?', 'body': 'Decide.', 'blocking': True})
    flow.record_degradation(store, 't', 'resume_from_checkpoint', 'node lost')
    store.budget_extension('t', 2, 0, 'top-up after the invalidated baseline')

    options = flow.halt_options(store, store.task('t'))
    assert options['degrade'] == []
    assert options['budget_extension'] is None
    assert options['resolve_question'] == ['q']


def test_non_blocking_questions_are_not_offered_and_manual_tasks_have_no_menu(tmp_path):
    store = setup(tmp_path)
    flow.question(store, 't', {'id': 'q-note', 'title': 'FYI', 'body': 'Not blocking.', 'blocking': False})
    assert flow.halt_options(store, store.task('t'))['resolve_question'] == []

    manual = setup(tmp_path / 'manual', autonomy=False)
    flow.question(manual, 't', {'id': 'q', 'title': 'Need', 'body': 'Decide.', 'blocking': True})
    decision = flow.next_step(manual, 't')
    assert decision['action'] == 'human' and 'options' not in decision


def test_drive_returns_the_options_menu_on_halt(tmp_path):
    store = setup(tmp_path, escalation=ESCALATION, budget={'max_operations': 2, 'max_seconds': 60})
    flow.question(store, 't', {'id': 'q-topology', 'title': 'Which fabric?',
                               'body': 'Choose.', 'blocking': True})
    result = autopilot.drive(store, 't')
    assert result['status'] == 'halt'
    assert result['options']['resolve_question'] == ['q-topology']
    assert result['options']['budget_extension']['remaining_additions'] == 1
