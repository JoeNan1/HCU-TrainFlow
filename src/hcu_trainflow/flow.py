"""Persistent implement/review/correct decisions around the training evidence gates.

The Agent executes the decisions. This module never silently launches a model,
claims to authenticate reviewer identity, or treats a code review as a GPU test.
"""
import json
import time
from .core import DEGRADE_DETAILS, FlowError, GATES, atomic_write, child, context_epoch, fingerprint, safe_id, utc
from .skill_registry import STAGE_SKILLS, WIKI_UPDATE_SKILL

DEFAULTS = {'max_rounds': 20, 'max_stalled_rounds': 3, 'full_review_every': 4,
            'max_review_failures': 3, 'poll_seconds': 300}
DELIVERABLES = {'environment': 'environment', 'adapt': 'baseline', 'analyze': 'analysis',
                'optimize': 'stage-quality', 'diagnose': 'diagnosis', 'operate': 'operations'}
NEXT = {'prepared': 'environment_checked', 'environment_checked': 'baseline_validated',
        'baseline_validated': 'profiling', 'profiling': 'optimizing', 'optimizing': 'scale_ready',
        'scale_ready': 'training', 'training': 'completed'}
STAGES = {'prepared': 'adapt', 'environment_checked': 'adapt', 'baseline_validated': 'optimize',
          'profiling': 'optimize', 'optimizing': 'optimize', 'scale_ready': 'fault-tolerance',
          'training': 'fault-tolerance'}


def artifact_json(store, value):
    document = json.loads(store.artifact(value))
    if not isinstance(document, dict):
        raise FlowError('Expected a retained JSON object')
    return document


def retain(store, value):
    return store.put(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode())


AUTONOMY_ACTOR = 'autonomy-policy'


def autonomy(task):
    """Declared autonomous policy for this task, or None for a human channel."""
    policy = task['spec'].get('autonomy')
    return policy if isinstance(policy, dict) and policy.get('mode') == 'autonomous' else None


def policy_answer(policy, question):
    """First declared answer whose match phrase occurs in the question text."""
    text = ' '.join((question.get('id', ''), question.get('title', ''), question.get('body', ''))).lower()
    for row in policy.get('question_answers') or []:
        if row['match'].lower() in text:
            return row
    return None


def dispose_policy(store, tid, task=None):
    """Retain collected guidance as advisory; answer only declared questions.

    Autonomous tasks have no human channel. Guidance is kept with an explicit
    policy actor instead of impersonating a person, and a blocking question is
    closed only when the declared policy answers it. Anything else stays open so
    ``next_step`` halts with a retained reason rather than waiting.
    """
    task = task or store.task(tid)
    policy = autonomy(task)
    if policy is None:
        return {'guidance': 0, 'questions': 0}
    with store.db() as db:
        guidance = [row['id'] for row in db.execute(
            "SELECT id FROM flow_guidance WHERE task=? AND status IN ('pending','needs-human','queued')", (tid,))]
        questions = [(row['id'], json.loads(row['payload'])) for row in db.execute(
            "SELECT id,payload FROM flow_questions WHERE task=? AND status='open'", (tid,))]
    answers = {}
    for qid, payload in questions:
        if not payload.get('blocking'):
            continue
        match = policy_answer(policy, payload)
        if match is None:
            continue
        # Retain before the write transaction; Store.put uses its own connection.
        answers[qid] = retain(store, {
            'kind': 'autonomy-question-answer', 'context': task['context'], 'actor': AUTONOMY_ACTOR,
            'policy': fingerprint(policy), 'question': qid, 'question_title': payload['title'],
            'question_body': payload['body'], 'answer': match['answer'], 'source': match['source']})
    if not guidance and not answers:
        return {'guidance': 0, 'questions': 0}
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        for sha in guidance:
            db.execute("UPDATE flow_guidance SET status='not-applicable',note=? WHERE task=? AND id=?",
                       ('autonomy-policy: no human channel; retained as advisory', tid, sha))
            store.event(db, tid, 'human-guidance-acknowledged',
                        {'guidance': sha, 'decision': 'not-applicable', 'actor': AUTONOMY_ACTOR,
                         'note': 'autonomy policy: recorded as advisory, not as a human decision'})
        for qid, sha in answers.items():
            db.execute('INSERT OR REPLACE INTO flow_guidance VALUES(?,?,?,?,?,?)',
                       (tid, sha, task['context'], 'applied', 'autonomy-policy: declared answer', utc()))
            resolution = {'guidance': sha, 'note': 'autonomy-policy: declared answer'}
            db.execute("UPDATE flow_questions SET status='closed',resolution=? WHERE task=? AND id=?",
                       (json.dumps(resolution), tid, qid))
            store.event(db, tid, 'human-question-resolved',
                        {'id': qid, **resolution, 'actor': AUTONOMY_ACTOR})
    return {'guidance': len(guidance), 'questions': len(answers)}


MUST_ESCALATE = (
    'authorization: new host, credential, permission or shared resource',
    'acceptance: relaxing or rewriting the agreed criteria',
    'objective: the target cannot be met; deliver the negative result',
    'cancel: abandoning the task is a human decision',
)


def halt_options(store, task):
    """Machine-readable menu of the actions a halt still permits.

    Only what the policy already authorized is listed: the Agent still decides
    which (if any) to apply and must record the observed reason. Anything outside
    this menu stays a human decision.
    """
    policy = autonomy(task) or {}
    escalation = policy.get('escalation') or {}
    tid = task['id']
    state = degradation_state(store, tid)
    used = state['used']
    degrade = []
    for row in state['ladder']:
        attempts = row.get('max_attempts')
        if attempts is not None and used.get(row['action'], 0) >= attempts:
            continue
        degrade.append({**row, 'used': used.get(row['action'], 0)})
    budget = None
    rules = escalation.get('budget_extension')
    if isinstance(rules, dict):
        with store.db() as db:
            extensions = db.execute("SELECT operations FROM budget_extensions WHERE task=?", (tid,)).fetchall()
            spare = rules['hard_total_operations'] - store.effective_budget(db, tid)['max_operations']
        remaining = rules['max_additions'] - len(extensions)
        if remaining > 0 and spare > 0:
            budget = {'remaining_additions': remaining,
                      'operations_per_addition': rules['operations_per_addition'],
                      'operations_until_hard_ceiling': spare}
    with store.db() as db:
        questions = [row['id'] for row in db.execute(
            "SELECT id,payload FROM flow_questions WHERE task=? AND status='open'", (tid,))
            if json.loads(row['payload']).get('blocking')]
    return {'degrade': degrade, 'budget_extension': budget,
            'resolve_question': questions, 'must_escalate': list(MUST_ESCALATE)}


def _stop(store, task, result, reasons, **extra):
    """Human tasks wait for a person; autonomous tasks halt with a reason."""
    if autonomy(task) is None:
        return {**result, 'action': 'human', 'reasons': reasons, **extra}
    return {**result, 'action': 'halt', 'reasons': reasons,
            'halt_reason': reasons[0] if reasons else 'policy-stop',
            'options': halt_options(store, task), **extra}


def get_flow(db, tid):
    row = db.execute('SELECT * FROM flows WHERE task=?', (tid,)).fetchone()
    return {**dict(row), 'plan': json.loads(row['plan'])} if row else None


def needs_context_replan(db, tid):
    started = db.execute("SELECT COALESCE(MAX(seq),0) FROM events WHERE task=? AND kind IN ('flow-started','flow-replanned')", (tid,)).fetchone()[0]
    return context_epoch(db, tid) > started


def board_paths(store, tid):
    directory = child(store.root, 'collaboration/' + safe_id(tid))
    return directory, child(directory, 'BOARD.md'), child(directory, 'GUIDANCE.md')


def knowledge_followup(task, goal, phase):
    """Advisory for the Agent, not a source fetch, shared write or acceptance gate."""
    scopes = {
        'task-start': ['relevant-official-freshness', 'affected-workflow-usage'],
        'environment-milestone': ['reusable-site-experience', 'confirmed-version-freshness'],
        'optimization-milestone': ['qualified-final-model-summary', 'affected-workflow-usage'],
        'task-completion': ['reusable-site-experience', 'qualified-final-model-summary', 'cookbook-linkage'],
    }
    return {
        'skill': WIKI_UPDATE_SKILL, 'phase': phase, 'task_mode': task['spec']['mode'],
        'scope': scopes[phase], 'blocking': False, 'automatic_execution': False,
        'disposition_key': f"{task['context']}:{goal}:{phase}",
        'guide': 'docs/knowledge-architecture.md#任务中的维护时机',
        'instruction': 'Reuse the disposition in the task plan/BOARD; check or curate only applicable knowledge. '
                       'Record updated, checked-current, deferred with reason, or no-shareable-knowledge. '
                       'No repeated update on polling; no invented final optimization/loss results in standalone modes.',
    }


def validate_plan(plan):
    """Validate a Flow plan; shared by start/replan and the site generator."""
    if not isinstance(plan, dict) or set(plan) - (set(DEFAULTS) | {'acceptance'}):
        raise FlowError('Unknown flow-plan fields')
    plan = {**DEFAULTS, **plan}
    for key in DEFAULTS:
        if type(plan[key]) is not int or plan[key] <= 0:
            raise FlowError('Flow limits must be positive integers')
    if not 1 <= plan['poll_seconds'] <= 3600:
        raise FlowError('Guidance polling interval must be 1..3600 seconds')
    acceptance = plan.get('acceptance')
    if (not isinstance(acceptance, dict) or not acceptance
            or any(not isinstance(value, str) or not value.strip() for value in acceptance.values())):
        raise FlowError('Plan requires named, concrete acceptance criteria')
    for key in acceptance:
        safe_id(key)
    return plan


def check_acceptance_edit(task, previous_plan, acceptance):
    """An autonomous task cannot quietly rewrite the agreed acceptance criteria.

    ``forbid`` (the default) keeps replanning limited to limits and context;
    ``add-only`` permits new criteria but never edits or drops an existing one.
    Weakening a target needs a new task, where a person states the goal again.
    """
    policy = autonomy(task)
    if policy is None:
        return
    previous = (previous_plan or {}).get('acceptance') or {}
    if previous == acceptance:
        return
    mode = (policy.get('escalation') or {}).get('acceptance_edit', 'forbid')
    removed = set(previous) - set(acceptance)
    changed = {key for key in set(previous) & set(acceptance) if previous[key] != acceptance[key]}
    if mode != 'add-only' or removed or changed:
        raise FlowError('Autonomous replanning may not rewrite agreed acceptance criteria;'
                        ' create a new task for a different objective')


def start(store, tid, plan, reason=None):
    task = store.task(tid)
    if task['state'] in {'completed', 'cancelled'}:
        raise FlowError('Create a new task for a new objective')
    check_profile(task)
    plan = validate_plan(plan)
    acceptance = plan['acceptance']
    goal_record = {'objective': task['spec']['objective'], 'context': task['context'], 'plan': plan}
    if reason is not None:
        if not reason.strip():
            raise FlowError('Replanning requires a concrete reason')
        goal_record.update(revision_reason=reason, replanned_at=utc())
    goal = retain(store, goal_record)
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        current = db.execute('SELECT context,state FROM tasks WHERE id=?', (tid,)).fetchone()
        if current['state'] in {'completed', 'cancelled'} or current['context'] != task['context'] or context_epoch(db, tid) != task['context_epoch']:
            raise FlowError('Task context/state changed while planning')
        old = get_flow(db, tid)
        if old and reason is not None:
            check_acceptance_edit(task, old['plan'], acceptance)
        if old and (old['goal'] != goal or needs_context_replan(db, tid)) and not reason:
            raise FlowError('Plan/context changed; use flow-replan with a concrete reason')
        unchanged = bool(old and old['goal'] == goal)
        if not unchanged:
            db.execute('INSERT OR REPLACE INTO flows VALUES(?,?,?,?)', (tid, json.dumps(plan), goal, task['context']))
            db.execute("UPDATE flow_rounds SET status='superseded' WHERE task=? AND status IN ('submitted','accepted')", (tid,))
            store.event(db, tid, 'flow-replanned' if old else 'flow-started', {'goal': goal, 'reason': reason, 'context': task['context']})
    # A committed plan is not proof that filesystem initialization or the
    # draft transition completed. Re-entry must finish these idempotent steps.
    directory, board, guidance = board_paths(store, tid)
    if not guidance.exists():
        with store.db() as db:
            if db.execute('SELECT 1 FROM flow_guidance_cursor WHERE task=?', (tid,)).fetchone():
                raise FlowError('Human guidance file is missing; restore it rather than silently resetting the inbox')
        directory.mkdir(parents=True, exist_ok=True)
        # Never overwrite this file after creation; it belongs to the human.
        with guidance.open('x', encoding='utf8') as stream:
            stream.write('# Human guidance\n\nAdd comments, answers and priorities below. Refer to a question ID when replying.\n')
        sha = store.put(guidance.read_bytes())
        with store.db() as db:
            db.execute('INSERT OR IGNORE INTO flow_guidance VALUES(?,?,?,?,?,?)', (tid, sha, task['context'], 'template', '', utc()))
            db.execute('INSERT OR REPLACE INTO flow_guidance_cursor VALUES(?,?)', (tid, sha))
    if store.task(tid)['state'] == 'draft':
        store.transition(tid, 'prepared')
    views = render_board(store, tid)
    return {'task': tid, 'goal': goal, 'status': 'unchanged' if unchanged else 'started', **views,
            'knowledge_followup': knowledge_followup(task, goal, 'task-start')}


def sync_guidance(store, tid, *, force=False):
    from . import file_questions
    guidance = _sync_guidance(store, tid, force=force)
    questions = file_questions.scan(store, tid, force=force)
    return {**guidance, 'questions_new': questions['new'], 'question_scan': questions}


def _sync_guidance(store, tid, *, force=False):
    with store.db() as db:
        flow = get_flow(db, tid)
        scan = db.execute('SELECT checked_at FROM flow_guidance_scans WHERE task=?', (tid,)).fetchone()
    if not flow:
        return {'new': 0}
    now = time.time()
    if not force and scan and 0 <= now - scan['checked_at'] < flow['plan']['poll_seconds']:
        return {'new': 0, 'scan': 'not-due'}
    _, _, path = board_paths(store, tid)
    if not path.is_file():
        raise FlowError('Human guidance file is missing; restore it rather than silently resetting the inbox')
    if path.stat().st_size > 1024 * 1024:
        raise FlowError('Guidance exceeds 1 MiB; retain large evidence separately')
    data = path.read_bytes()
    data.decode('utf-8-sig')
    sha = store.put(data)
    task = store.task(tid)
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('INSERT OR REPLACE INTO flow_guidance_scans VALUES(?,?)', (tid, now))
        previous = db.execute('SELECT hash FROM flow_guidance_cursor WHERE task=?', (tid,)).fetchone()
        if previous and previous['hash'] == sha:
            return {'new': 0, 'guidance': sha}
        # A deliberate revert to earlier content is still a new human action.
        db.execute('INSERT OR REPLACE INTO flow_guidance VALUES(?,?,?,?,?,?)', (tid, sha, task['context'], 'pending', '', utc()))
        db.execute('INSERT OR REPLACE INTO flow_guidance_cursor VALUES(?,?)', (tid, sha))
        db.execute("UPDATE flow_rounds SET status='superseded' WHERE task=? AND status IN ('submitted','accepted')", (tid,))
        event = store.event(db, tid, 'human-guidance-received', {'guidance': sha, 'context': task['context']}, channel='agent')
    return {'new': 1, 'guidance': sha, 'event_id': event}


def acknowledge(store, tid, sha, decision, note):
    if decision not in {'applied', 'queued', 'needs-human', 'not-applicable'} or not note.strip():
        raise FlowError('Guidance needs a disposition and concrete response')
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM flow_guidance WHERE task=? AND id=?', (tid, sha)).fetchone()
        if not row or row['status'] == 'template':
            raise FlowError('Unknown human guidance')
        db.execute('UPDATE flow_guidance SET status=?,note=? WHERE task=? AND id=?', (decision, note, tid, sha))
        store.event(db, tid, 'human-guidance-acknowledged', {'guidance': sha, 'decision': decision, 'note': note})
    return render_board(store, tid)


def question(store, tid, value):
    store.task(tid)
    if set(value) != {'id', 'title', 'body', 'blocking'} or type(value['blocking']) is not bool or any(not isinstance(value[k], str) or not value[k].strip() for k in ('title','body')):
        raise FlowError('Question requires id, title, body and boolean blocking')
    safe_id(value['id'])
    with store.db() as db:
        if not get_flow(db, tid):
            raise FlowError('Start the collaborative flow first')
        old = db.execute('SELECT payload FROM flow_questions WHERE task=? AND id=?', (tid, value['id'])).fetchone()
        if old and json.loads(old['payload']) != value:
            raise FlowError('Question ID already has different content')
        db.execute("INSERT OR IGNORE INTO flow_questions VALUES(?,?,?,'open',NULL)", (tid, value['id'], json.dumps(value)))
        if not old:
            store.event(db, tid, 'human-question-opened', value)
    return render_board(store, tid)


def degradation_state(store, tid):
    """The declared repair ladder and how much of it has already been spent."""
    task = store.task(tid)
    policy = autonomy(task) or {}
    ladder = list((policy.get('escalation') or {}).get('degrade_ladder') or [])
    with store.db() as db:
        rows = db.execute("SELECT payload FROM events WHERE task=? AND kind='flow-degraded'", (tid,)).fetchall()
    used = {}
    for row in rows:
        action = json.loads(row['payload'])['action']
        used[action] = used.get(action, 0) + 1
    return {'task': tid, 'ladder': ladder, 'used': used,
            'remaining': [row['action'] for row in ladder if row['action'] not in used]}


def record_degradation(store, tid, action, reason, details=None):
    """Apply one declared repair step; the policy's own bounds stay authoritative."""
    task = store.task(tid)
    policy = autonomy(task)
    if policy is None:
        raise FlowError('Only autonomous tasks may apply a declared degrade step')
    ladder = (policy.get('escalation') or {}).get('degrade_ladder') or []
    step = next((row for row in ladder if row['action'] == action), None)
    if step is None:
        raise FlowError('Degrade action is not declared for this task: ' + str(action))
    if not isinstance(reason, str) or not reason.strip():
        raise FlowError('A degrade step needs the observed blocking reason')
    details = {} if details is None else details
    if not isinstance(details, dict) or set(details) - set(DEGRADE_DETAILS[action]):
        raise FlowError('Degrade details contain undeclared fields')
    if 'max_attempts' in step and degradation_state(store, tid)['used'].get(action, 0) >= step['max_attempts']:
        raise FlowError('Degrade action exhausted its declared attempts: ' + action)
    if action == 'micro_batch_down':
        if type(details.get('micro_batch')) is not int or details['micro_batch'] < step['min']:
            raise FlowError('micro_batch must stay at or above the declared floor')
    elif action == 'layers_down':
        if type(details.get('layers')) is not int or details['layers'] < step['min_layers']:
            raise FlowError('layers must stay at or above the declared floor')
        if step.get('record_scope_gap') and not (isinstance(details.get('scope_gap'), str)
                                                and details['scope_gap'].strip()):
            raise FlowError('A reduced-layer proxy must record its scope gap')
    elif action == 'recompute_on':
        if details.get('recompute') not in step['allow']:
            raise FlowError('recompute mode is not declared in the policy')
    elif action == 'rebalance_parallel':
        if not details or any(key not in step['allow'] for key in details):
            raise FlowError('Only declared parallel dimensions may change')
        if any(type(value) is not int or value < 1 for value in details.values()):
            raise FlowError('Parallel dimensions must be positive integers')
    sha = retain(store, {'kind': 'autonomy-degradation', 'context': task['context'],
                         'actor': AUTONOMY_ACTOR, 'policy': fingerprint(policy), 'action': action,
                         'reason': reason, 'details': details, 'recorded_at': utc()})
    with store.db() as db:
        store.event(db, tid, 'flow-degraded',
                    {'action': action, 'reason': reason, 'details': details,
                     'evidence': sha, 'actor': AUTONOMY_ACTOR})
    render_board(store, tid)
    return {'task': tid, 'action': action, 'evidence': sha, **degradation_state(store, tid)}


def resolve_question(store, tid, qid, value):
    """Let an autonomous task resolve its own escalation with a retained decision.

    This is the only non-human way to close a question. The answer is attributed
    to the Agent that made it, never presented as human guidance, and it cannot
    change reports, reviews, gates or budgets -- it only unblocks the question.
    """
    task = store.task(tid)
    policy = autonomy(task)
    if policy is None:
        raise FlowError('Only autonomous tasks may resolve a question without human guidance')
    if (not isinstance(value, dict) or set(value) != {'answer', 'source', 'note'}
            or any(not isinstance(item, str) or not item.strip() for item in value.values())):
        raise FlowError('A resolved question needs answer, source and note')
    with store.db() as db:
        if not get_flow(db, tid):
            raise FlowError('Start the collaborative flow first')
        row = db.execute("SELECT status FROM flow_questions WHERE task=? AND id=?", (tid, qid)).fetchone()
        if not row:
            raise FlowError('Unknown question')
        already = row['status'] == 'closed'
    if already:
        return {'question': qid, 'status': 'closed', 'changed': False, 'board': render_board(store, tid)}
    sha = retain(store, {'kind': 'autonomy-agent-decision', 'context': task['context'],
                         'actor': AUTONOMY_ACTOR, 'policy': fingerprint(policy), 'question': qid,
                         'answer': value['answer'], 'source': value['source']})
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('INSERT OR REPLACE INTO flow_guidance VALUES(?,?,?,?,?,?)',
                   (tid, sha, task['context'], 'applied', 'autonomy: agent decision', utc()))
        resolution = {'guidance': sha, 'note': value['note']}
        db.execute("UPDATE flow_questions SET status='closed',resolution=? WHERE task=? AND id=?",
                   (json.dumps(resolution), tid, qid))
        store.event(db, tid, 'human-question-resolved',
                    {'id': qid, **resolution, 'actor': AUTONOMY_ACTOR})
    return {'question': qid, 'status': 'closed', 'changed': True, 'decision': sha,
            'board': render_board(store, tid)}


def close_question(store, tid, qid, guidance, note):
    if not note.strip():
        raise FlowError('Question resolution needs an explanation')
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        answer = db.execute('SELECT status FROM flow_guidance WHERE task=? AND id=?', (tid, guidance)).fetchone()
        if not answer or answer['status'] not in {'applied', 'not-applicable'}:
            raise FlowError('Resolve with reviewed human guidance, not an inferred answer')
        if not db.execute('SELECT 1 FROM flow_questions WHERE task=? AND id=?', (tid, qid)).fetchone():
            raise FlowError('Unknown question')
        resolution = {'guidance': guidance, 'note': note}
        db.execute("UPDATE flow_questions SET status='closed',resolution=? WHERE task=? AND id=?", (json.dumps(resolution), tid, qid))
        store.event(db, tid, 'human-question-resolved', {'id': qid, **resolution})
    return render_board(store, tid)


def blockers(db, tid, task, flow):
    reasons = []
    if flow['context'] != task['context'] or needs_context_replan(db, tid):
        reasons.append('context-changed: replan and revalidate')
    if db.execute("SELECT 1 FROM flow_guidance WHERE task=? AND status IN ('pending','needs-human')", (tid,)).fetchone():
        reasons.append('human-guidance-needs-response')
    if any(json.loads(x['payload'])['blocking'] for x in db.execute("SELECT payload FROM flow_questions WHERE task=? AND status='open'", (tid,))):
        reasons.append('blocking-human-question')
    return reasons


def target(task):
    return 'completed' if task['spec']['mode'] != 'full' else NEXT.get(task['state'])


def declared_profile(task):
    """The sub-workflow this task declared, or None for the full workflow."""

    declared = task['spec'].get('profile')
    return declared['id'] if declared else None


def check_profile(task):
    """A declared profile must exist and agree with the task context.

    Routing answers "which module set applies"; a task may only *use* one that
    matches its own engine/model family/mode.  Selecting a profile never
    advances a stage and never relaxes a gate.
    """

    declared = task['spec'].get('profile')
    if not declared:
        return None
    from . import catalog
    context = {key: value for key, value in (task['spec'].get('context') or {}).items()
               if key in {'engine', 'model_family'}}
    context['mode'] = task['spec']['mode']
    try:
        return catalog.resolve_profile(context, requested=declared['id'])
    except catalog.ModuleContractError as exc:
        raise FlowError(str(exc)) from None


def profile_gates(task):
    """Stage gates derived from the declared profile, or None without one."""

    name = declared_profile(task)
    if name is None:
        return None
    from . import catalog
    return catalog.derived_gates(name)


def expected_evidence(task, destination):
    """Non-gate evidence the declared profile expects for this transition.

    Advisory only: the seven stage gates stay exactly as derived, and these
    evidence products (adaptation, qualification, profile summary, change
    record) never block an advance on their own.
    """

    name = declared_profile(task)
    if name is None:
        return []
    from . import catalog
    stages = [stage for stage, target in NEXT.items() if target == destination]
    if not stages:
        return []
    stage = stages[0]
    entry = catalog.profile(name)
    kinds = []
    for module_id in entry.module_ids():
        module = catalog.module(module_id)
        if module.report and module.report in catalog.EVIDENCE_REPORTS and stage in module.stage:
            kinds.append(module.report)
    return sorted(set(kinds))


def required_reports(task, destination):
    if destination == 'iterate':
        return []
    if task['spec']['mode'] != 'full':
        kinds = [DELIVERABLES[task['spec']['mode']]]
        if task['spec']['mode'] == 'optimize':
            kinds.append('performance')
        return kinds
    kinds = list(GATES.get(destination, []))
    derived = profile_gates(task)
    if derived is not None and destination in derived:
        narrowed = sorted(derived[destination])
        if not set(narrowed) <= set(kinds):
            # A profile may thin work, never a gate: fail loudly instead of
            # demanding evidence the Flow does not enforce.
            raise FlowError('Profile gate widens the Flow gate at ' + destination
                            + ': ' + ', '.join(sorted(set(narrowed) - set(kinds))))
        kinds = narrowed
    # A destination the profile does not cover keeps the full gate.
    return kinds


def invariants(task):
    """Constraints re-derived on every read, so a summary cannot narrow them.

    This is the answer to compaction: the gates, the acceptance boundary and
    the budget ceiling are recomputed from the store each time instead of
    being recalled from a conversation that may have lost them.
    """

    derived = profile_gates(task)
    gates = derived if derived is not None else {stage: list(kinds) for stage, kinds in GATES.items()}
    policy = autonomy(task) or {}
    escalation = policy.get('escalation') or {}
    return {
        'gates': {stage: sorted(set(kinds)) for stage, kinds in sorted(gates.items())},
        'acceptance_edit': escalation.get('acceptance_edit', 'forbid'),
        'budget': task['spec'].get('budget') or {},
        'profile': declared_profile(task),
        'autonomous': autonomy(task) is not None,
        'review_required': True,
        'stage_skills': sorted(set(STAGE_SKILLS.values())),
    }


def brief_state(store, tid):
    """The digest of everything a fresh session needs, assembled by the store.

    Read-only and cheap: no guidance scan, no round reconciliation, no event.
    ``brief`` adds the current decision on top; the hash binds a later write to
    exactly this state so an action taken on a stale picture fails loudly.
    """

    task = store.task(tid)
    destination = target(task)
    with store.db() as db:
        row = get_flow(db, tid)
        if not row:
            raise FlowError('Start the collaborative flow first')
        plan = row['plan']
        last = db.execute('SELECT * FROM flow_rounds WHERE task=? ORDER BY number DESC LIMIT 1',
                          (tid,)).fetchone()
        reports = store.current_reports(db, tid, task['context'])
        questions = [json.loads(item['payload']) for item in db.execute(
            "SELECT payload FROM flow_questions WHERE task=? AND status='open'", (tid,))]
        evidence = [item[0] for item in db.execute(
            "SELECT json_extract(payload,'$.artifact') FROM events WHERE task=?"
            " AND kind IN ('artifact-claimed','report-recorded')"
            " AND json_extract(payload,'$.artifact') IS NOT NULL"
            " ORDER BY seq DESC LIMIT 12", (tid,))]
        recent = [{'seq': item['seq'], 'kind': item['kind']} for item in db.execute(
            'SELECT seq,kind FROM events WHERE task=? ORDER BY seq DESC LIMIT 8', (tid,))]
        extensions = db.execute('SELECT COUNT(*) FROM budget_extensions WHERE task=?',
                                (tid,)).fetchone()[0]
    acceptance = plan.get('acceptance') or {}
    candidate = None
    if last is not None and last['candidate']:
        candidate = {'round': last['number'], 'status': last['status'],
                     'snapshot': artifact_json(store, last['candidate']).get('snapshot')}
    state = degradation_state(store, tid)
    return {
        'task': tid,
        'state': task['state'],
        'revision': task['revision'],
        'context': task['context'],
        'objective': plan.get('objective') or task['spec'].get('objective'),
        'acceptance': {'fingerprint': fingerprint(acceptance), 'clauses': acceptance},
        'profile': task['spec'].get('profile'),
        'autonomous': autonomy(task) is not None,
        'target': destination,
        'required_reports': required_reports(task, destination),
        'expected_evidence': expected_evidence(task, destination),
        'invariants': invariants(task),
        'candidate': candidate,
        'reports': sorted(reports),
        'evidence': [sha for sha in evidence if sha],
        'open_questions': [{'id': q['id'], 'title': q['title'], 'blocking': q['blocking']}
                           for q in questions],
        'budget': {'spec': task['spec'].get('budget') or {}, 'extensions': extensions},
        'degradation': {'ladder': state['ladder'], 'used': state['used']},
        'recent_events': recent,
    }


BRIEF_TOKEN_FIELDS = ('task', 'state', 'revision', 'context', 'objective', 'acceptance',
                      'profile', 'autonomous', 'target', 'required_reports',
                      'expected_evidence', 'invariants', 'candidate', 'open_questions',
                      'budget', 'degradation')


def brief_token(store, tid):
    """Fingerprint of the decision state a write may be bound to.

    Only the fields that change *what the next action must be* take part: the
    evidence inventory and the recent-event tail move with every step and would
    otherwise turn an ordinary report into a false ``stale-brief``.
    """

    body = brief_state(store, tid)
    return fingerprint({key: body[key] for key in BRIEF_TOKEN_FIELDS})


def verify_brief(store, tid, expected):
    if not isinstance(expected, str) or len(expected) != 64:
        raise FlowError('brief-hash must be the hash returned by flow-brief')
    current = brief_token(store, tid)
    if expected != current:
        raise FlowError('stale-brief: the task state changed since that brief; take a new one')
    return current


def brief(store, tid, notes=None):
    """One page a fresh session can resume from; nothing here trusts a summary."""

    body = brief_state(store, tid)
    decision = next_step(store, tid)
    stage = STAGES.get(body['state'], 'adapt')
    skill = decision.get('skill') or STAGE_SKILLS.get(stage)
    return {**body,
            'action': decision.get('action'),
            'skill': skill,
            'reasons': decision.get('reasons', []),
            'options': decision.get('options'),
            'reads': ['docs/skill-reading-map.md', 'skills/' + skill + '/SKILL.md'],
            'notes': notes or [],
            'brief_hash': brief_token(store, tid)}


def align(store, tid):
    """Re-derive what this task is for and report every delta.

    This does not judge the work. It makes drift visible on a stage boundary:
    a changed objective or acceptance, a profile that no longer matches the
    context, or a stage the profile never planned has to be settled with
    ``flow-replan`` and a reason instead of sliding in unnoticed.
    """

    task = store.task(tid)
    with store.db() as db:
        row = get_flow(db, tid)
        if not row:
            raise FlowError('Start the collaborative flow first')
        first = db.execute("SELECT payload FROM events WHERE task=? AND kind='flow-started'"
                           " ORDER BY seq LIMIT 1", (tid,)).fetchone()
    deltas = []
    plan = row['plan']
    acceptance = plan.get('acceptance') or {}
    profile = declared_profile(task)
    if profile is not None:
        try:
            check_profile(task)
        except FlowError as exc:
            deltas.append({'kind': 'profile-context-mismatch', 'detail': str(exc)})
        from .catalog.profiles import profile as profile_entry
        if task['state'] in STAGES and task['state'] not in profile_entry(profile).stages:
            deltas.append({'kind': 'stage-outside-profile', 'detail': task['state']})
    try:
        for stage in GATES:
            required_reports(task, stage)
    except FlowError as exc:
        deltas.append({'kind': 'gate-widened', 'detail': str(exc)})
    if first:
        original = artifact_json(store, json.loads(first['payload'])['goal'])
        started = (original.get('plan') or {}).get('acceptance') or {}
        if fingerprint(started) != fingerprint(acceptance):
            deltas.append({'kind': 'acceptance-changed-since-start',
                           'from': fingerprint(started), 'to': fingerprint(acceptance),
                           'action': 'flow-replan'})
        if original.get('objective') != (plan.get('objective') or task['spec'].get('objective')):
            deltas.append({'kind': 'objective-changed-since-start',
                           'from': original.get('objective'),
                           'to': plan.get('objective') or task['spec'].get('objective'),
                           'action': 'flow-replan'})
    result = {'task': tid, 'state': task['state'], 'profile': profile,
              'status': 'drift' if deltas else 'aligned',
              'deltas': deltas, 'next': 'flow-replan' if deltas else 'continue',
              'acceptance': fingerprint(acceptance),
              'gates': invariants(task)['gates']}
    if deltas:
        with store.db() as db:
            store.event(db, tid, 'flow-aligned', {'deltas': deltas, 'state': task['state']})
    return result


def gate(store, db, task, candidate):
    """Reports are current and belong to this exact candidate; LLM verdict cannot waive them."""
    from .team import completion_blockers
    reasons = completion_blockers(db,task['id'])
    if candidate['target'] == 'completed' and db.execute("SELECT 1 FROM flow_guidance WHERE task=? AND status='queued'", (task['id'],)).fetchone():
        reasons.append('queued-human-guidance-needs-final-disposition')
    reports = store.current_reports(db, task['id'], task['context'])
    for kind in required_reports(task, candidate['target']):
        sha = candidate['reports'].get(kind)
        row = reports.get(kind)
        if not row or row['artifact'] != sha:
            reasons.append('missing-or-replaced-report:' + kind)
            continue
        body = artifact_json(store, sha)
        if body.get('candidate_snapshot') != candidate['snapshot']:
            reasons.append('snapshot-mismatch:' + kind)
        delivery_only = task['spec']['mode'] in {'environment', 'analyze', 'diagnose', 'operate'}
        accepted = {'pass', 'complete', 'fail', 'incomplete'} if delivery_only else {'pass', 'complete'} if kind == 'analysis' else {'pass'}
        if row['result'] not in accepted:
            reasons.append('report-not-passing:' + kind)
    experiment = candidate.get('experiment')
    if candidate['target'] == 'iterate' or (candidate['target'] == 'scale_ready' or task['spec']['mode'] == 'optimize'):
        if not experiment:
            reasons.append('missing-local-correctness-and-performance-experiment')
        else:
            from .quality import assess_iteration
            inputs = artifact_json(store, experiment)
            if inputs.get('context') != task['context'] or inputs.get('correctness', {}).get('candidate_snapshot') != candidate['snapshot']:
                reasons.append('experiment-context-or-snapshot-mismatch')
            else:
                for sha in inputs['correctness'].get('evidence', []):
                    store.artifact(sha)
                try:
                    assessment = assess_iteration(**inputs)
                except (ValueError, TypeError, KeyError):
                    assessment = {'status': 'invalid-experiment'}
                if assessment['status'] != 'iteration-kept':
                    reasons.append('iteration-not-kept')
    return reasons


def last_round(db, tid):
    return db.execute('SELECT * FROM flow_rounds WHERE task=? ORDER BY number DESC LIMIT 1', (tid,)).fetchone()


def baseline_handoff(store, db, task, flow, row):
    """Reuse the reviewed baseline only for its unchanged, administrative handoff.

    This neither accepts a new candidate nor inherits review across a new goal,
    context, report, team plan or human/peer instruction.
    """
    if (task['spec']['mode'] != 'full' or task['state'] != 'baseline_validated'
            or not row or row['status'] not in {'accepted', 'advanced'}
            or row['context'] != task['context'] or row['goal'] != flow['goal']
            or task['revision'] != row['revision'] + 1 or not row['review']):
        return None
    candidate = artifact_json(store, row['candidate'])
    if candidate['target'] != 'baseline_validated':
        return None
    reviewed_at = db.execute("SELECT MAX(seq) FROM events WHERE task=? AND kind='flow-reviewed'", (task['id'],)).fetchone()[0]
    if reviewed_at is None or db.execute(
            "SELECT 1 FROM events WHERE task=? AND seq>? AND kind IN "
            "('human-guidance-received','team-planned','agent-message')",
            (task['id'], reviewed_at)).fetchone():
        return None
    if gate(store, db, task, {**candidate, 'target': 'profiling'}):
        return None
    return candidate


def next_step(store, tid):
    sync_guidance(store, tid)
    from .file_questions import state as question_state
    inbox = question_state(store, tid)
    task = store.task(tid)
    if autonomy(task) is not None:
        # No human channel: retain guidance as advisory and answer only the
        # questions the declared policy covers. The rest stay open so this
        # decision can halt with a retained reason instead of waiting.
        dispose_policy(store, tid, task)
        inbox = question_state(store, tid)
    mode = task['spec']['mode']
    stage = STAGES.get(task['state']) if mode == 'full' else 'adapt' if mode in {'environment', 'adapt'} else 'optimize' if mode in {'analyze', 'optimize'} else 'fault-tolerance'
    with store.db() as db:
        flow = get_flow(db, tid)
        if not flow:
            raise FlowError('Start the collaborative flow first')
        result = {'task': tid, 'state': task['state'], 'context': task['context'], 'goal': flow['goal'],
                  'profile': task['spec'].get('profile'),
                  'invariants': invariants(task),
                  'file_questions': {'pending': inbox['pending'], 'path': inbox['path'], 'scan_error': inbox['scan_error'], 'blocking': False}}
        row = last_round(db, tid)
        if row and row['status'] == 'accepted':
            candidate = artifact_json(store, row['candidate'])
            # Includes a crash just after committing the terminal transition.
            if row['context'] == task['context'] and row['goal'] == flow['goal'] and task['state'] == candidate['target'] and task['revision'] == row['revision'] + 1:
                db.execute("UPDATE flow_rounds SET status='advanced' WHERE task=? AND number=?", (tid, row['number']))
                row = last_round(db, tid)
        from .team import active_operation, completion_blockers, schedule
        terminal = task['state'] in {'completed', 'cancelled'}
        uncertain = [r['id'] for r in db.execute("SELECT id,status FROM operations WHERE task=? AND status IN ('started','unknown')", (tid,))
                     if terminal or r['status']=='unknown' or not active_operation(db,r['id'],tid)]
        if uncertain:
            return {**result, 'action': 'reconcile', 'operations': uncertain}
        if terminal:
            if task['state'] == 'completed':
                result['knowledge_followup'] = knowledge_followup(task, flow['goal'], 'task-completion')
            return {**result, 'action': task['state']}
        reasons = blockers(db, tid, task, flow)
        if task['state'] in {'paused', 'blocked', 'failed'}:
            reasons.append('task-' + task['state'])
        if reasons:
            return _stop(store, task, result, reasons)
        result['skill'] = STAGE_SKILLS[stage]
        if row and row['status'] == 'blocked' and row['goal'] == flow['goal']:
            return _stop(store, task, result, ['review-blocked'], review=row['review'])
        if row and row['status'] in {'submitted', 'accepted'}:
            candidate = artifact_json(store, row['candidate'])
            # Reconcile a crash after the core transition committed but before advance recorded it.
            if row['status'] == 'accepted' and task['state'] == candidate['target'] and task['revision'] == row['revision'] + 1:
                db.execute("UPDATE flow_rounds SET status='advanced' WHERE task=? AND number=?", (tid, row['number']))
            elif row['context'] != task['context'] or row['goal'] != flow['goal'] or row['revision'] != task['revision']:
                return {**result, 'action': 'repair', 'reasons': ['stale-round'], 'round': row['number']}
            else:
                if row['failures'] >= flow['plan']['max_review_failures']:
                    return _stop(store, task, result, ['review-failures'], round=row['number'])
                # Reject mechanically incomplete evidence before spending an
                # independent review, and recheck it after review as before.
                problems = gate(store, db, task, candidate)
                team_reasons = completion_blockers(db, tid)
                if team_reasons:
                    return {**result, 'action': 'coordinate', 'reasons': team_reasons, 'team': schedule(store, tid)}
                return {**result, 'action': 'repair' if problems else 'advance' if row['status'] == 'accepted' else 'review',
                        'round': row['number'], 'candidate': row['candidate'], 'review': row['review'], 'reasons': problems,
                        'full_alignment_required': row['number'] % flow['plan']['full_review_every'] == 0 or candidate['target'] in {'scale_ready', 'training', 'completed'}}
        if baseline_handoff(store, db, task, flow, row):
            return {**result, 'action': 'advance', 'target': 'profiling',
                    'round': row['number'], 'candidate': row['candidate'],
                    'review': row['review'], 'review_reused': True, 'reasons': []}
        rounds = db.execute('SELECT * FROM flow_rounds WHERE task=? AND goal=? ORDER BY number DESC', (tid, flow['goal'])).fetchall()
        stalled = 0
        for previous in rounds:
            if not previous['review']:
                break
            review = artifact_json(store, previous['review'])
            if review['progress'] == 'advanced':
                break
            stalled += 1
        if len(rounds) >= flow['plan']['max_rounds'] or stalled >= flow['plan']['max_stalled_rounds']:
            return _stop(store, task, result, ['round-budget-or-progress-plateau'],
                         rounds=len(rounds), stalled=stalled)
        action = 'repair' if row and row['status'] in {'revise', 'superseded'} else 'work'
        team_reasons=completion_blockers(db,tid)
        if team_reasons:
            return {**result,'action':'coordinate','reasons':team_reasons,'team':schedule(store,tid)}
        phase = {'prepared': 'task-start', 'environment_checked': 'environment-milestone',
                 'scale_ready': 'optimization-milestone'}.get(task['state'])
        if phase == 'task-start' and row and row['goal'] == flow['goal']:
            phase = None  # Standalone iterations also remain in prepared; do not repeat startup work.
        if phase:
            result['knowledge_followup'] = knowledge_followup(task, flow['goal'], phase)
        return {**result, 'action': action, 'target': target(task),
                'required_reports': required_reports(task, target(task)),
                'expected_evidence': expected_evidence(task, target(task)),
                'last_review': row['review'] if row else None,
                'poll_seconds': flow['plan']['poll_seconds']}


def submit(store, tid, candidate, *, brief_hash=None):
    task = store.task(tid)
    if brief_hash is None:
        if autonomy(task) is not None:
            # No human channel: the turn must be anchored to a state the agent
            # actually re-read, otherwise a long run drifts off a stale picture.
            raise FlowError('unverified-turn: take flow-brief and pass its brief_hash before submitting')
    else:
        verify_brief(store, tid, brief_hash)
    decision = next_step(store, tid)
    if decision['action'] not in {'work', 'repair'}:
        raise FlowError('Resolve the current flow decision before submitting another candidate')
    task = store.task(tid)
    fields = {'author', 'context', 'goal', 'snapshot', 'summary', 'reports', 'target', 'evidence'}
    if fields - candidate.keys() or set(candidate) - (fields | {'experiment'}):
        raise FlowError('Invalid candidate fields')
    if any(not isinstance(candidate[k], str) or not candidate[k].strip() for k in ('author','summary')) or not isinstance(candidate['reports'], dict):
        raise FlowError('Candidate needs author, substantive summary and reports')
    if candidate['context'] != task['context'] or candidate['goal'] != decision['goal']:
        raise FlowError('Candidate context/goal is stale')
    allowed = {target(task)}
    if task['state'] == 'optimizing' or task['spec']['mode'] == 'optimize':
        allowed.add('iterate')
    if candidate['target'] not in allowed:
        raise FlowError('Candidate cannot skip a workflow stage')
    if not isinstance(candidate['evidence'], list) or not candidate['evidence']:
        raise FlowError('Candidate needs retained evidence')
    for sha in [candidate['snapshot'], *candidate['evidence'], *candidate['reports'].values(), *([candidate['experiment']] if candidate.get('experiment') else [])]:
        store.artifact(sha)
    if candidate.get('experiment'):
        inputs = artifact_json(store, candidate['experiment'])
        required = {'context', 'correctness', 'baseline_times', 'candidate_times'}
        if required - inputs.keys() or set(inputs) - (required | {'max_regression'}) or not isinstance(inputs['correctness'], dict):
            raise FlowError('Experiment must follow the iteration-check input contract')
    sha = retain(store, candidate)
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        current = db.execute('SELECT context,revision FROM tasks WHERE id=?', (tid,)).fetchone()
        row = last_round(db, tid)
        if current['context'] != task['context'] or current['revision'] != task['revision'] or get_flow(db, tid)['goal'] != candidate['goal']:
            raise FlowError('Task changed while submitting')
        if row and row['status'] in {'submitted', 'accepted'} and decision.get('round') != row['number']:
            raise FlowError('Another controller submitted a round')
        number = row['number'] + 1 if row else 1
        if row and row['status'] in {'submitted', 'accepted'}:
            db.execute("UPDATE flow_rounds SET status='superseded' WHERE task=? AND number=?", (tid, row['number']))
        db.execute('INSERT INTO flow_rounds VALUES(?,?,?,?,?,?,NULL,?,0)', (tid, number, task['context'], task['revision'], candidate['goal'], sha, 'submitted'))
        problems = gate(store, db, task, candidate)
        store.event(db, tid, 'flow-candidate-needs-repair' if problems else 'flow-review-requested',
                    {'round': number, 'candidate': sha, 'context': task['context'], 'reasons': problems}, channel='agent')
    render_board(store, tid)
    return {'round': number, 'candidate': sha,
            'status': 'needs-repair' if problems else 'awaiting-review', 'reasons': problems}


def review_failure(store, tid, number, reason):
    if not reason.strip():
        raise FlowError('Record the actual review failure')
    with store.db() as db:
        row = last_round(db, tid)
        if not row or row['number'] != number or row['status'] != 'submitted':
            raise FlowError('No such pending review')
        db.execute('UPDATE flow_rounds SET failures=failures+1 WHERE task=? AND number=?', (tid, number))
        store.event(db, tid, 'flow-review-failed', {'round': number, 'reason': reason})
    render_board(store, tid)
    return {'status': 'review-failed', 'round': number}


def review(store, tid, value):
    """Invalid reviewer output is an attempt, never implicit acceptance."""
    decision = next_step(store, tid)
    if decision['action'] != 'review':
        raise FlowError('No current review request')
    try:
        return _review(store, tid, value, decision)
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        # Do not count an old result against a different concurrently submitted round.
        with store.db() as db:
            current = last_round(db, tid)
        if current and current['number'] == decision['round'] and current['status'] == 'submitted':
            review_failure(store, tid, decision['round'], str(exc))
        raise FlowError(str(exc)) from exc


def _review(store, tid, value, decision):
    fields = {'round', 'candidate', 'goal', 'context', 'reviewer', 'verdict', 'summary', 'findings', 'acceptance', 'progress', 'full_alignment', 'evidence'}
    if set(value) != fields:
        raise FlowError('Review must follow the complete structured contract; empty/partial output is not a pass')
    candidate = artifact_json(store, decision['candidate'])
    if any(value[k] != decision[k] for k in ('round', 'candidate', 'goal', 'context')):
        raise FlowError('Review refers to a different round/goal/context')
    if not value['reviewer'].strip() or value['reviewer'] == candidate['author'] or not value['summary'].strip():
        raise FlowError('Require a separate reviewer identity and a substantive review')
    policy = autonomy(store.task(tid))
    if policy is not None and value['reviewer'] not in policy['reviewers']:
        raise FlowError('Autonomous reviews must come from the declared reviewer pool')
    if value['verdict'] not in {'accept', 'revise', 'blocked'} or value['progress'] not in {'advanced', 'stalled', 'regressed'}:
        raise FlowError('Invalid review verdict/progress')
    if type(value['full_alignment']) is not bool or decision['full_alignment_required'] and not value['full_alignment']:
        raise FlowError('This boundary requires review against the complete goal')
    with store.db() as db:
        criteria = get_flow(db, tid)['plan']['acceptance']
    if set(value['acceptance']) != set(criteria) or any(v not in {'met', 'pending'} for v in value['acceptance'].values()):
        raise FlowError('Review every named acceptance criterion without weakening the goal')
    if not isinstance(value['findings'], list) or any(not isinstance(f, dict) or f.get('severity') not in {'blocking', 'followup'} or not f.get('detail') for f in value['findings']):
        raise FlowError('Findings require severity and actionable details')
    if not isinstance(value['evidence'], list) or not value['evidence']:
        raise FlowError('Review needs evidence, not only a completion marker')
    for sha in value['evidence']:
        store.artifact(sha)
    if value['verdict'] == 'accept' and (any(f['severity'] == 'blocking' for f in value['findings']) or candidate['target'] == 'completed' and 'pending' in value['acceptance'].values()):
        raise FlowError('Blocking findings or unfinished final criteria prohibit acceptance')
    sha = retain(store, value)
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        row = last_round(db, tid)
        task = store.task(tid)
        if not row or row['candidate'] != decision['candidate'] or row['status'] != 'submitted' or row['revision'] != task['revision'] or get_flow(db, tid)['goal'] != value['goal']:
            raise FlowError('Review request changed while reviewing')
        status = 'accepted' if value['verdict'] == 'accept' else value['verdict']
        db.execute('UPDATE flow_rounds SET review=?,status=? WHERE task=? AND number=?', (sha, status, tid, row['number']))
        store.event(db, tid, 'flow-reviewed', {'round': row['number'], 'review': sha, 'verdict': value['verdict']})
    render_board(store, tid)
    return {'round': value['round'], 'status': status, 'review': sha}


def guard_transition(store, db, task, destination):
    flow = get_flow(db, task['id'])
    if not flow or destination in {'prepared', 'paused', 'blocked', 'failed', 'cancelled'}:
        return
    row = last_round(db, task['id'])
    reasons = blockers(db, task['id'], task, flow)
    if db.execute("SELECT 1 FROM operations WHERE task=? AND status IN ('started','unknown')", (task['id'],)).fetchone():
        reasons.append('reconcile-unresolved-execution')
    task = {**task, 'spec': json.loads(task['spec']) if isinstance(task['spec'], str) else task['spec']}
    if not reasons and destination == 'profiling' and baseline_handoff(store, db, task, flow, row):
        # Store.transition commits this event and the state change atomically.
        store.event(db, task['id'], 'flow-review-reused', {
            'round': row['number'], 'candidate': row['candidate'], 'review': row['review'],
            'target': destination, 'reason': 'unchanged-reviewed-baseline-handoff'})
        return
    if not row or row['status'] != 'accepted' or row['context'] != task['context'] or row['goal'] != flow['goal'] or row['revision'] != task['revision']:
        reasons.append('current-independent-review-required')
    else:
        candidate = artifact_json(store, row['candidate'])
        if candidate['target'] != destination:
            reasons.append('review-target-mismatch')
        reasons += gate(store, db, task, candidate)
    if reasons:
        raise FlowError('Flow transition blocked: ' + ', '.join(reasons))


def advance(store, tid):
    decision = next_step(store, tid)
    if decision['action'] != 'advance':
        raise FlowError('Cannot advance: ' + decision['action'] + ' ' + ', '.join(decision.get('reasons', [])))
    candidate = artifact_json(store, decision['candidate'])
    destination = decision.get('target', candidate['target'])
    if destination != 'iterate':
        store.transition(tid, destination)
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        if candidate['target'] == 'iterate':
            task = dict(db.execute('SELECT * FROM tasks WHERE id=?', (tid,)).fetchone())
            guard_transition(store, db, task, 'iterate')
        changed = db.execute("UPDATE flow_rounds SET status='advanced' WHERE task=? AND number=? AND status='accepted'", (tid, decision['round'])).rowcount
        if changed:
            current = store.task(tid)
            store.event(db, tid, 'flow-advanced', {'round': decision['round'], 'target': candidate['target'],
                'context_spec':current['spec']['context'],'evidence':[decision['candidate']]})
    from .experience import sync
    try:
        knowledge=sync(store,tid)
    except (OSError,ValueError) as exc:
        knowledge={'status':'pending','reason':type(exc).__name__,'resume':'experience-sync '+tid}
    render_board(store, tid)
    return {**next_step(store, tid),'knowledge':knowledge}


def guard_execution(store, tid, *, allow_parallel=False):
    with store.db() as db:
        flow = get_flow(db, tid)
    if flow:
        decision = next_step(store, tid)
        task=store.task(tid)
        with store.db() as db: reasons=blockers(db,tid,task,flow)
        if reasons or decision['action'] in {'human', 'halt', 'completed', 'cancelled'} or decision['action']=='reconcile' and not allow_parallel:
            raise FlowError('Resolve flow decision before more execution: ' + decision['action'] + ' ' + ', '.join(decision.get('reasons', [])))


def status_update(store, tid, value):
    """A scoped human-facing summary and technical patch; never execution gates."""
    from . import technical_board
    required = {'summary', 'progress', 'next', 'needs_human', 'evidence'}
    if not isinstance(value, dict) or not required <= set(value) or set(value) - required - {'technical', 'context', 'context_epoch'}:
        raise FlowError('Status requires summary, progress, next, needs_human and evidence; optional technical and context/context_epoch')
    technical_board.text(value['summary'], 'Status summary', 240, single_line=True)
    for key in ('progress', 'next', 'needs_human'):
        if not isinstance(value[key], list) or len(value[key]) > 3:
            raise FlowError('Status lists allow at most three concise single-line items')
        for item in value[key]:
            technical_board.text(item, 'Status item', 200, single_line=True)
    technical_board.evidence(store, value['evidence'])
    task = store.task(tid)
    supplied_scope = set(value) & {'context', 'context_epoch'}
    if supplied_scope and (supplied_scope != {'context', 'context_epoch'}
            or not isinstance(value['context'], str) or type(value['context_epoch']) is not int
            or not technical_board.fresh(value, task)):
        raise FlowError('Status context/context_epoch must both match the current task')
    patch = value.get('technical', {})
    technical_board.validate(store, patch, patch=True)
    with store.db() as db:
        previous = db.execute('SELECT payload FROM flow_status WHERE task=?', (tid,)).fetchone()
    previous_payload = previous['payload'] if previous else None
    sections = technical_board.merge(json.loads(previous_payload) if previous_payload else None, patch, task)
    technical_board.validate(store, sections)
    body = {**value, 'context': task['context'], 'context_epoch': task['context_epoch']}
    if sections or 'technical' in value:
        body['technical'] = sections
    artifact = retain(store, body)
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        current = db.execute('SELECT context FROM tasks WHERE id=?', (tid,)).fetchone()
        if not get_flow(db, tid) or current['context'] != task['context'] or context_epoch(db, tid) != task['context_epoch']:
            raise FlowError('Start/reconcile the current flow before writing its status')
        latest = db.execute('SELECT payload FROM flow_status WHERE task=?', (tid,)).fetchone()
        if (latest['payload'] if latest else None) != previous_payload:
            raise FlowError('Status changed while merging technical sections; reread and retry')
        db.execute('INSERT OR REPLACE INTO flow_status VALUES(?,?,?)', (tid, json.dumps(body, ensure_ascii=False), utc()))
        store.event(db, tid, 'flow-status-updated', {'artifact': artifact, **body})
    return {**render_board(store, tid), 'status_artifact': artifact}


def render_board(store, tid):
    task = store.task(tid)
    with store.db() as db:
        flow = get_flow(db, tid)
        if not flow:
            raise FlowError('Start the collaborative flow first')
        rounds = [dict(x) for x in db.execute('SELECT * FROM flow_rounds WHERE task=? ORDER BY number', (tid,))]
        guidance = [dict(x) for x in db.execute("SELECT * FROM flow_guidance WHERE task=? AND status!='template' ORDER BY created", (tid,))]
        questions = [dict(x) for x in db.execute('SELECT * FROM flow_questions WHERE task=?', (tid,))]
        reports = [dict(x) for x in store.current_reports(db, tid, task['context']).values()]
        events = [dict(x) for x in db.execute('SELECT kind,payload,created FROM events WHERE task=? ORDER BY seq DESC', (tid,))]
        status = db.execute('SELECT payload,created FROM flow_status WHERE task=?', (tid,)).fetchone()
    directory, board, human = board_paths(store, tid)
    from . import file_questions
    try:
        file_questions.ensure(store, tid)
    except FlowError:
        pass  # Missing user content is shown below, never recreated.
    inbox = file_questions.state(store, tid)
    details = child(directory, 'DETAILS.md')
    def link(sha):
        return f'[{sha[:12]}](../../objects/{sha[:2]}/{sha})'
    lines = ['# HCU-TrainFlow collaboration board', '', task['spec']['objective'], '',
             f"Updated: {utc()} · State: **{task['state']}** · Mode: {task['spec']['mode']}",
             f"Context: `{task['context']}` · Goal: {link(flow['goal'])}", '',
             'Write comments in [GUIDANCE.md](GUIDANCE.md). This board is generated; guidance is never overwritten.',
             'Local tests, source inspection and real HCU validation are separate evidence scopes.', '', '## Acceptance', '']
    lines += [f'- **{key}**: {text}' for key, text in flow['plan']['acceptance'].items()]
    lines += ['', '## Questions', '']
    for row in questions:
        q = json.loads(row['payload'])
        lines += [f"### {q['id']} · {row['status']} · {'blocking' if q['blocking'] else 'advisory'}", '', q['title'], '', q['body'], '']
        if row['resolution']:
            lines += ['Resolution: ' + json.loads(row['resolution'])['note'], '']
    lines += ['', '## Human guidance and responses', '']
    lines += [f"- {link(x['id'])} · **{x['status']}** · {x['note'] or 'Awaiting agent response'}" for x in guidance]
    lines += ['', '## Iteration and independent review', '']
    for row in rounds:
        c = artifact_json(store, row['candidate'])
        lines += [f"### Round {row['number']} · {row['status']} · target {c['target']}", '', c['summary'], '',
                  f"Candidate {link(row['candidate'])} · snapshot {link(c['snapshot'])} · review {link(row['review']) if row['review'] else 'pending'} · review failures: {row['failures']}", '']
        if row['review']:
            review = artifact_json(store, row['review'])
            lines += [review['summary'], ''] + [f"- {f['severity']}: {f['detail']}" for f in review['findings']]
    lines += ['', '## Current evidence', ''] + [f"- {r['kind']}: {r['result']} · {link(r['artifact'])}" for r in reports]
    lines += ['', '## Recent progress and incidents', ''] + [f"- {e['created']} · {e['kind']} · `{e['payload']}`" for e in reversed(events)]
    from .team import schedule, messages
    team=schedule(store,tid)
    lines += ['', '## Agent work and dependencies', '', f"Parallel slots: {team['max_parallel']} · Ready: {', '.join(team['dispatchable']) or 'none'}", '']
    for item in team['assignments']:
        lines += [f"- **{item['id']}** · {item['owner']} · {item['status']} · stale={item['stale']} · depends on {', '.join(item['depends_on']) or 'none'}: {item['goal']}"]
        run=item['run']
        if run:lines += [f"  - Session: {run['session'] or 'not bound'} · token {run['token']} · result {link(run['report']) if run['report'] else 'pending'}"]
    lines += ['', '## Agent questions and findings', '']
    for item in messages(store,tid):
        m=item['message']
        lines += [f"- **{item['id']}** · {m['sender']} → {m['recipient']} · {m['kind']} / {item['status']} · stale={item['stale']}: {m['body']}"]
    lines += ['', '## User file questions (not execution authorization)', '',
              f"Pending: {inbox['pending']} · [QUESTIONS.md](QUESTIONS.md) · scan error: {inbox['scan_error'] or 'none'}"]
    atomic_write(details, '\n'.join(lines) + '\n')
    labels = {'draft':'任务已登记', 'prepared':'准备阶段', 'environment_checked':'环境已验收',
              'baseline_validated':'初始基线已验证', 'profiling':'性能分析', 'optimizing':'优化迭代',
              'scale_ready':'准备扩容', 'training':'持续训练', 'completed':'已完成',
              'cancelled':'已取消', 'paused':'已暂停', 'blocked':'等待解决阻塞', 'failed':'出现失败'}
    concise = ['# 训练工作看板', '',
               f"更新：{utc()} · 流程登记：**{labels.get(task['state'], task['state'])}**", '',
               '[提问与回答](QUESTIONS.md) · [修改要求与指导](GUIDANCE.md) · [完整协作记录](DETAILS.md)',
               '[计划](../../task_plan.md) · [发现](../../findings.md) · [过程](../../progress.md)', '',
               '## 当前进展', '']
    from . import technical_board
    safe = technical_board.plain
    status_body = json.loads(status['payload']) if status else None
    fresh = technical_board.fresh(status_body, task)
    if fresh:
        concise += [safe(status_body['summary']), ''] + ['- ' + safe(x) for x in status_body['progress']]
        if status_body['evidence']:
            concise += ['', '进展证据：' + ' · '.join(link(sha) for sha in status_body['evidence'])]
        concise += ['', '## 接下来', ''] + (['- ' + safe(x) for x in status_body['next']] or ['- 按当前计划继续。'])
    else:
        concise += ['主控尚未更新当前上下文的简要进展；请查看完整记录。']
        if rounds:
            latest = rounds[-1]
            concise += ['- 最近候选（历史记录）：' + safe(artifact_json(store, latest['candidate'])['summary'][:200])]
    concise += ['', '## 需要你关注', '']
    needs = list(status_body['needs_human']) if fresh else []
    needs += [json.loads(q['payload'])['title'][:200] for q in questions if q['status']=='open' and json.loads(q['payload'])['blocking']]
    pending_guidance = sum(x['status'] in {'pending','needs-human'} for x in guidance)
    if pending_guidance:
        needs.append(f'有 {pending_guidance} 版指导等待主控处理。')
    if inbox['scan_error']:
        needs.append('问题文件暂时无法正常采集，请保留原件并查看完整记录中的原因。')
    concise += ['- ' + safe(x) for x in needs[:5]] or ['- 当前没有已登记的人工决策需求。']
    if fresh:
        concise += technical_board.render(status_body.get('technical', {}), link)
    concise += ['', f"你的问题：{inbox['pending']} 项待回答；默认每 5 分钟采集，在线 Agent 会在原问题下回复。",
                '此页由程序生成；原始证据、团队消息和历史保存在完整协作记录中。看板内容不替代训练验收。', '']
    atomic_write(board, '\n'.join(concise))
    return {'board': str(board), 'guidance': str(human), 'questions': inbox['path'], 'details': str(details), 'task': tid}
