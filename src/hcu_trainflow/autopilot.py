"""Bounded autonomous drive over the existing Flow decisions.

A task that declares ``spec.autonomy`` has no human channel, so the decisions
that used to wait for a person become deterministic stops with a retained
reason. This driver repeats the transitions that need no outside decision and
delegates the two that do to a caller-provided worker:

* ``advance`` is executed here, because the review already accepted the
  candidate and ``flow.advance`` re-checks the same gates;
* ``work`` / ``repair`` and ``review`` are handed to a worker, which returns a
  candidate or a review document for the existing Flow APIs to validate;
* ``halt`` stops the run and is queued as an inbox alert instead of waiting.

The driver never fabricates training evidence, never writes a review itself,
and never bypasses a gate. A rejected gate is a halt, not a retry.

Worker contract
---------------
``worker`` is any object (a plain Python object, or one returned by a
``--worker module:factory`` callable) with these optional methods::

    worker.work(store, tid, decision) -> dict     # candidate for flow.submit
    worker.review(store, tid, decision) -> dict   # document for flow.review

Both receive the current decision (goal, round, required_reports, reasons).
Returning ``None`` means "I cannot handle this"; raising ``autopilot.Handoff``
stops the run with the raised reason. Any other exception is recorded as a
worker error and the loop stops after ``max_worker_errors`` of them, so a buggy
worker cannot spin forever.
"""
from __future__ import annotations

import json

from .core import FlowError, utc
from . import flow


HANDLED_ACTIONS = {'work', 'repair', 'review'}
HALT_CHANNEL = 'agent'


class Handoff(FlowError):
    """Raised by a worker that cannot continue without an outside decision."""


def _halt(store, tid, decision, reasons, *, extra=None, channel=HALT_CHANNEL):
    task = store.task(tid)
    with store.db() as db:
        blocking = [row['id'] for row in db.execute(
            "SELECT id,payload FROM flow_questions WHERE task=? AND status='open'", (tid,))
            if json.loads(row['payload']).get('blocking')]
    body = {'state': task['state'], 'context': task['context'], 'reasons': reasons,
            'autonomy': flow.autonomy(task), 'decision': decision.get('action'),
            # Two stops with the same kind of reason are still different
            # incidents when the round or the open question differs; without a
            # discriminator the second alert was never queued.
            'round': decision.get('round'), 'blocking_questions': blocking}
    with store.db() as db:
        # Repeated drives against the same stop must not flood the event log,
        # but the first stop is queued as an inbox alert for any watcher.
        previous = db.execute("SELECT payload FROM events WHERE task=? AND kind='flow-halted'"
                              " ORDER BY seq DESC LIMIT 1", (tid,)).fetchone()
        if not previous or json.loads(previous['payload']) != body:
            store.event(db, tid, 'flow-halted', body, channel=channel)
    options = decision.get('options')
    if options is None:
        # A driver-produced stop (worker declined, gate rejected) faces the same
        # menu as a Flow stop; the caller should not have to special-case it.
        options = flow.halt_options(store, task)
    return {'status': 'halt', 'action': 'halt', 'halt_reason': reasons[0] if reasons else 'policy-stop',
            'reasons': reasons, 'options': options, 'context': task['context'],
            'state': task['state'], 'decision': decision, **(extra or {})}


def halts(store, include_delivered=False):
    """Queued ``flow-halted`` alerts from the existing inbox, newest first."""
    from . import monitor
    rows = [row for row in monitor.inbox(store, 'list') if row['kind'] == 'flow-halted']
    if not include_delivered:
        rows = [row for row in rows if row['status'] in {'pending', 'retry', 'claimed'}]
    result = []
    for row in reversed(rows):
        payload = json.loads(row['payload'])
        result.append({'task': row['task'], 'state': payload.get('state'),
                       'reasons': payload.get('reasons', []), 'status': row['status'],
                       'event': row['event_id'], 'channel': row['channel']})
    return result


def load_worker(spec, store, tid):
    """Resolve ``module:factory`` into a worker object for the given task.

    The factory is caller-supplied trusted code; the driver gives it the Store
    and task id so it can read retained evidence and the current decision.
    """
    if not isinstance(spec, str) or spec.count(':') != 1:
        raise FlowError('Worker must be given as module:factory')
    module_name, _, attribute = spec.partition(':')
    import importlib
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise FlowError('Worker module cannot be imported: ' + module_name) from exc
    factory = getattr(module, attribute, None)
    if not callable(factory):
        raise FlowError('Worker factory is not callable: ' + spec)
    worker = factory(store, tid)
    if worker is None:
        raise FlowError('Worker factory returned nothing: ' + spec)
    return worker


def _call(worker, method, store, tid, decision):
    handler = getattr(worker, method, None)
    if handler is None:
        return None
    return handler(store, tid, decision)


def drive(store, tid, *, worker=None, max_steps=50, advance=True, max_worker_errors=3):
    """Walk the current Flow as far as the policy and worker allow.

    Returns ``status=halt`` with retained reasons when nothing can decide,
    ``status=work``/``review`` when no worker is supplied (the caller must act),
    and ``status=completed|cancelled`` at the terminal states. ``max_steps``
    bounds the loop so an unexpected oscillation cannot run forever.
    """
    if type(max_steps) is not int or max_steps <= 0:
        raise FlowError('max_steps must be a positive integer')
    if type(max_worker_errors) is not int or max_worker_errors <= 0:
        raise FlowError('max_worker_errors must be a positive integer')
    task = store.task(tid)
    if flow.autonomy(task) is None:
        raise FlowError('Task does not declare an autonomous policy; keep the human channel')
    advanced, stats = [], {'submits': 0, 'reviews': 0, 'errors': 0}
    steps = 0
    while steps < max_steps:
        steps += 1
        decision = flow.next_step(store, tid)
        action = decision.get('action')
        if action == 'advance' and advance:
            before = store.task(tid)['state']
            try:
                flow.advance(store, tid)
            except FlowError as exc:
                return _halt(store, tid, decision, ['advance-rejected', str(exc)],
                             extra={'steps': steps, 'advanced': advanced, 'worker': stats})
            advanced.append({'from': before, 'to': store.task(tid)['state']})
            continue
        if action in HANDLED_ACTIONS and worker is not None:
            method = 'review' if action == 'review' else 'work'
            try:
                document = _call(worker, method, store, tid, decision)
            except Handoff as exc:
                return _halt(store, tid, decision, ['worker-handoff', str(exc)],
                             extra={'steps': steps, 'advanced': advanced, 'worker': stats})
            except Exception as exc:  # A worker bug must not corrupt Flow state.
                stats['errors'] += 1
                with store.db() as db:
                    store.event(db, tid, 'worker-error',
                                {'action': action, 'error': type(exc).__name__, 'message': str(exc),
                                 'attempt': stats['errors']})
                if stats['errors'] >= max_worker_errors:
                    return _halt(store, tid, decision, ['worker-error:' + type(exc).__name__],
                                 extra={'steps': steps, 'advanced': advanced, 'worker': stats})
                continue
            if document is None:
                return _halt(store, tid, decision, ['worker-declined:' + action],
                             extra={'steps': steps, 'advanced': advanced, 'worker': stats})
            try:
                if method == 'work':
                    # Anchor the submit to the state the decision came from: the
                    # driver re-reads the brief each turn instead of trusting
                    # whatever it still remembers about this run.
                    outcome = flow.submit(store, tid, document,
                                          brief_hash=flow.brief_token(store, tid))
                    stats['submits'] += 1
                    # A worker that keeps shipping a gate-rejected candidate must
                    # not burn the whole step budget: stop when it does not converge.
                    if outcome.get('status') == 'needs-repair':
                        stats['unconverged'] = stats.get('unconverged', 0) + 1
                        if stats['unconverged'] >= max_worker_errors:
                            return _halt(store, tid, decision, ['repair-not-converging'],
                                         extra={'steps': steps, 'advanced': advanced, 'worker': stats})
                    else:
                        stats['unconverged'] = 0
                else:
                    flow.review(store, tid, document)
                    stats['reviews'] += 1
            except FlowError as exc:
                stats['errors'] += 1
                with store.db() as db:
                    store.event(db, tid, 'worker-rejected',
                                {'action': action, 'error': type(exc).__name__, 'message': str(exc),
                                 'attempt': stats['errors']})
                if stats['errors'] >= max_worker_errors:
                    return _halt(store, tid, decision, [action + '-rejected', str(exc)],
                                 extra={'steps': steps, 'advanced': advanced, 'worker': stats})
            continue
        if action == 'halt':
            return _halt(store, tid, decision, list(decision.get('reasons') or ['policy-stop']),
                         extra={'steps': steps, 'advanced': advanced, 'worker': stats})
        if action == 'human':
            # Defensive: an autonomous task must not fall back to the human
            # channel. Record it as a policy gap rather than waiting.
            return _halt(store, tid, decision, list(decision.get('reasons') or ['human-channel-required']),
                         extra={'steps': steps, 'advanced': advanced, 'worker': stats})
        if action in {'completed', 'cancelled'}:
            return {'status': action, 'action': action, 'steps': steps, 'advanced': advanced,
                    'worker': stats, 'context': task['context'],
                    'state': store.task(tid)['state'], 'decision': decision}
        return {'status': action, 'action': action, 'steps': steps, 'advanced': advanced,
                'worker': stats, 'context': store.task(tid)['context'],
                'state': store.task(tid)['state'], 'decision': decision}
    return {'status': 'incomplete', 'action': 'step-budget', 'steps': steps, 'advanced': advanced,
            'worker': stats, 'context': store.task(tid)['context'], 'state': store.task(tid)['state'],
            'message': 'max_steps reached before a decision that needs the caller'}


def stop_report(store, tid, reason, evidence=None):
    """Retain a halt receipt so a stopped autonomous run stays auditable."""
    task = store.task(tid)
    if not isinstance(reason, str) or not reason.strip():
        raise FlowError('A halt report needs a concrete reason')
    evidence = list(evidence or [])
    for sha in evidence:
        store.artifact(sha)
    return {'artifact': flow.retain(store, {
        'kind': 'autonomy-halt-report', 'context': task['context'], 'state': task['state'],
        'actor': flow.AUTONOMY_ACTOR, 'reason': reason, 'evidence': evidence,
        'recorded_at': utc(),
    }), 'evidence': evidence}
