"""Mechanical checks on report claims.

An agent writes the prose; nothing here judges it. A claim is accepted only
when it resolves to a retained object this task produced and, if it states a
value, when that value is the one on the object. The four checks cover the
hallucination classes that can be settled without semantics:

* referential - the cited object exists and belongs to this task;
* numeric     - a stated value matches the value at the cited path;
* procedural  - a claimed stage is one this task's profile actually serves;
* scope       - a claim does not cite another candidate's snapshot.

What remains (is this the right experiment at all) stays with the
independent review; a mechanical check that cannot be argued with beats a
judgement that can.
"""
from __future__ import annotations

import json

from .core import FlowError

CLAIM_FIELDS = {"id", "statement", "value", "source", "stage", "candidate_snapshot"}
SOURCE_FIELDS = {"artifact", "path"}
TOLERANCE = 1e-9


def artifact_owners(db, sha):
    """Tasks already attributable for a retained object (see Store.artifact_tasks).

    Kept next to the claim checks so a read-only audit and the write path ask
    exactly the same question. Executions and pipeline steps record their
    evidence as a *list*, so membership is tested with ``json_each``: a scalar
    comparison against the JSON array matched nothing and left every
    execution-produced object unowned.
    """

    tasks = {row[0] for row in db.execute(
        "SELECT DISTINCT task FROM events WHERE task IS NOT NULL"
        " AND json_extract(payload,'$.artifact')=?", (sha,))}
    tasks |= {row[0] for row in db.execute(
        "SELECT DISTINCT r.task FROM pipeline_steps s JOIN pipeline_runs r ON r.id=s.run"
        " WHERE s.artifact=? OR s.report=?"
        " OR (json_valid(s.result) AND (json_extract(s.result,'$.artifact')=?"
        " OR EXISTS (SELECT 1 FROM json_each(s.result,'$.evidence') WHERE json_each.value=?)))",
        (sha, sha, sha, sha))}
    tasks |= {row[0] for row in db.execute(
        "SELECT DISTINCT task FROM operations WHERE task IS NOT NULL"
        " AND (json_valid(result) AND (json_extract(result,'$.artifact')=?"
        " OR EXISTS (SELECT 1 FROM json_each(operations.result,'$.evidence')"
        " WHERE json_each.value=?)))", (sha, sha))}
    return {task for task in tasks if task}


def _stage_scope(task):
    """Stages the task's declared profile serves; every stage when undeclared.

    A declared profile that cannot be resolved fails closed: falling back to
    "every stage" would let a claim name a stage the task never planned.
    """

    from .catalog import contracts
    from .catalog.profiles import profile as declared_profile

    declared = task["spec"].get("profile")
    if not declared:
        return set(contracts.FLOW_STAGES)
    try:
        entry = declared_profile(declared.get("id"))
    except Exception:
        raise FlowError("Claim stage scope needs a known profile: "
                        + str(declared.get("id"))) from None
    return set(entry.stages)


def _resolve(document, path):
    if (not isinstance(path, list) or not path
            or not all(isinstance(step, (str, int)) and not isinstance(step, bool) for step in path)):
        raise FlowError("Claim source path must be a non-empty list of keys")
    node = document
    for step in path:
        try:
            node = node[step]
        except (KeyError, IndexError, TypeError):
            raise FlowError("Claim source path does not resolve: " + json.dumps(path)) from None
    return node


def _same(left, right):
    """Numeric equality with a relative tolerance.

    No absolute floor: a floor of 1.0*TOLERANCE let a claimed 0.0 match a source
    of 5e-10, i.e. an infinite relative error near zero. Exact integers still
    compare exactly, so values above 2**53 are not silently rounded together.
    """

    if isinstance(left, bool) or isinstance(right, bool):
        return left is right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        if left == right:
            return True
        scale = max(abs(float(left)), abs(float(right)))
        if scale == 0.0:
            return False
        return abs(float(left) - float(right)) <= TOLERANCE * scale
    return left == right


def claims_required(task, kind):
    """A profile task states what it measured; a legacy task may still omit it."""

    from .catalog.contracts import GATE_REPORTS

    return kind in GATE_REPORTS and bool(task["spec"].get("profile"))


def check_claims(store, task, kind, value, *, require=False):
    """Validate a report's claims; returns them so callers can re-use the list."""

    claims = value.get("claims")
    if claims is None:
        # ``complete`` is gate-acceptable for the analysis report, so it needs
        # the same evidence binding as ``pass``; capability-computed reports are
        # exempt through ``require=False``, not through a status string.
        if require and value.get("status") in {"pass", "complete"}:
            raise FlowError("PASS/COMPLETE requires claims that resolve to retained evidence")
        return []
    if not isinstance(claims, list) or not claims:
        raise FlowError("Claims must be a non-empty list")
    scope = _stage_scope(task)
    seen = set()
    for claim in claims:
        if not isinstance(claim, dict) or set(claim) - CLAIM_FIELDS:
            raise FlowError("Unknown claim fields: " + ", ".join(sorted(set(claim) - CLAIM_FIELDS)))
        ident = claim.get("id")
        if not isinstance(ident, str) or not ident.strip() or ident in seen:
            raise FlowError("Claims need unique non-empty ids")
        seen.add(ident)
        if not isinstance(claim.get("statement"), str) or not claim["statement"].strip():
            raise FlowError("Claim " + ident + " needs a statement")
        stage = claim.get("stage")
        if stage is not None and stage not in scope:
            raise FlowError("Claim " + ident + " cites a stage this task does not serve: " + str(stage))
        snapshot = claim.get("candidate_snapshot")
        if snapshot is not None and snapshot != value.get("candidate_snapshot"):
            raise FlowError("Claim " + ident + " cites a different candidate snapshot")
        source = claim.get("source")
        if source is None:
            if "value" in claim:
                raise FlowError("Claim " + ident + " states a value without a source")
            continue
        if not isinstance(source, dict) or set(source) != SOURCE_FIELDS:
            raise FlowError("Claim source needs exactly artifact and path")
        artifact = source["artifact"]
        if not isinstance(artifact, str) or not artifact:
            raise FlowError("Claim " + ident + " source artifact must be an object id")
        store.artifact(artifact)
        owners = set() if store.artifact_public(artifact) else store.artifact_tasks(artifact)
        if owners and task["id"] not in owners:
            raise FlowError("Claim evidence belongs to another task: " + artifact)
        if "value" not in claim:
            continue
        document = json.loads(store.artifact(artifact))
        if not _same(_resolve(document, source["path"]), claim["value"]):
            raise FlowError("Claim " + ident + " value does not match its source")
    return claims


def shadow_findings(store, tid=None):
    """Refusals recorded while the task was in declared shadow mode."""

    with store.db() as db:
        rows = db.execute(
            "SELECT task,payload FROM events WHERE kind='integrity-shadow'"
            + (" AND task=?" if tid else "") + " ORDER BY seq", ((tid,) if tid else ())).fetchall()
    result = []
    for row in rows:
        body = json.loads(row["payload"])
        result.append({"task": row["task"], "kind": body.get("kind"),
                       "artifact": body.get("artifact"), "problems": body.get("problems", [])})
    return {"status": "attention" if result else "pass", "findings": result}


def verify(store, tid, kind):
    """Re-check a recorded report against the store without changing anything."""

    task = store.task(tid)
    with store.db() as db:
        row = db.execute("SELECT * FROM reports WHERE task=? AND kind=? AND context=?",
                         (tid, kind, task["context"])).fetchone()
    if not row:
        raise FlowError("No recorded report of kind " + kind + " for this context")
    body = json.loads(store.artifact(row["artifact"]))
    problems = []
    try:
        check_claims(store, task, kind, body, require=claims_required(task, kind))
    except FlowError as exc:
        problems.append(str(exc))
    for sha in body.get("evidence") or []:
        try:
            store.artifact(sha)
            owners = set() if store.artifact_public(sha) else store.artifact_tasks(sha)
        except (FlowError, OSError) as exc:
            problems.append("Unreadable evidence " + sha + ": " + str(exc))
            continue
        if owners and tid not in owners:
            problems.append("Evidence belongs to another task: " + sha)
    claims = body.get("claims") or []
    unbound = [claim.get("id") for claim in claims if "source" not in claim]
    return {"task": tid, "kind": kind, "artifact": row["artifact"],
            "status": "pass" if not problems else "incomplete",
            "claims": len(claims), "unbound": unbound, "problems": problems}
