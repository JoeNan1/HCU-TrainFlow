"""Transactional task state, immutable artifacts and fenced resource ownership."""
from __future__ import annotations

import contextlib
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import time
import uuid


class FlowError(ValueError):
    pass


class PipelineContextConflict(FlowError):
    """A retained run cannot write facts into a changed task identity."""


def _check_lease_ttl(ttl):
    if (isinstance(ttl, bool) or not isinstance(ttl, (int, float))
            or not 0 < ttl <= 86400 or not math.isfinite(ttl)):
        raise FlowError("Lease TTL must be finite and in (0,86400]")


def _check_lease_expiry(row):
    expiry = row["expires"]
    if (isinstance(expiry, bool) or not isinstance(expiry, (int, float))
            or not math.isfinite(expiry)):
        raise FlowError("Invalid persisted lease expiry; inspect and reconcile before reuse")
    return expiry


def utc():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def fingerprint(value):
    return digest(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode())


def context_epoch(db, tid):
    """A reset invalidates earlier validation even when the context bytes return."""
    return db.execute("SELECT COALESCE(MAX(seq),0) FROM events WHERE task=? AND kind='context-changed'", (tid,)).fetchone()[0]


def valid_pass(value):
    return (type(value.get("executed")) is int and value["executed"] > 0
            and not value.get("failures") and not value.get("required_missing")
            and not value.get("skipped_required"))


def read_json(path):
    with open(path, encoding="utf-8-sig") as stream:
        return json.load(stream, parse_constant=lambda value: (_ for _ in ()).throw(FlowError("Non-finite JSON: " + value)))


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not isinstance(data, bytes):
        data = data.encode("utf-8")
    fd, name = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


_WINDOWS_OBJECT_CONFLICTS = {5, 32, 33}
_OBJECT_READ_DELAYS = (0.005, 0.01, 0.02, 0.04, 0.08, 0.16, 0.32)


def _read_object(path):
    """Retry only bounded Windows access/sharing conflicts, never bad bytes."""
    for delay in (*_OBJECT_READ_DELAYS, None):
        try:
            return path.read_bytes()
        except PermissionError as exc:
            if getattr(exc, "winerror", None) not in _WINDOWS_OBJECT_CONFLICTS or delay is None:
                raise
            time.sleep(delay)


def _publish_object(path, data):
    """Atomically create an immutable object without replacing a competitor.

    POSIX filesystems must support same-directory hard links; unsupported links
    and genuine I/O failures propagate, with no unsafe overwrite fallback.
    Windows rename already refuses an existing destination. The staged inode
    is complete and fsynced before either publication operation exposes it.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            if os.name == "nt":
                os.rename(name, path)
            else:
                os.link(name, path)
        except FileExistsError:
            if digest(_read_object(path)) != digest(data):
                raise FlowError("Corrupted competing artifact")
        except PermissionError as publish_error:
            if getattr(publish_error, "winerror", None) not in _WINDOWS_OBJECT_CONFLICTS:
                raise
            # Windows may report access denied rather than already-exists for
            # an occupied destination. Accept only verified competing bytes.
            try:
                published = _read_object(path)
            except OSError:
                raise publish_error
            if digest(published) != digest(data):
                raise FlowError("Corrupted competing artifact")
    finally:
        if os.path.exists(name):
            os.unlink(name)


def write_json(path, value):
    atomic_write(path, json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def safe_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", value):
        raise FlowError("Invalid identifier")
    return value


def child(root, relative):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if path == root or not path.is_relative_to(root):
        raise FlowError("Path must stay inside its managed root")
    return path


MODES = {"environment", "adapt", "analyze", "optimize", "diagnose", "operate", "full"}
PIPELINE = ["draft", "prepared", "environment_checked", "baseline_validated", "profiling", "optimizing", "scale_ready", "training", "completed"]
GATES = {"environment_checked": ["environment"], "baseline_validated": ["baseline"],
         "profiling": ["baseline"], "optimizing": ["analysis"], "scale_ready": ["stage-quality", "performance"],
         "training": ["environment", "stage-quality", "scale"], "completed": ["completion"]}


DEGRADE_ACTIONS = {
    # action -> (required policy fields, optional policy fields)
    "micro_batch_down": (("min",), ()),
    "recompute_on": (("allow",), ()),
    "rebalance_parallel": (("allow",), ()),
    "layers_down": (("min_layers",), ("record_scope_gap",)),
    "resume_from_checkpoint": ((), ("max_attempts",)),
    "restart_clean": ((), ("max_attempts",)),
}

DEGRADE_DETAILS = {
    # action -> detail keys an Agent may record when applying the step
    "micro_batch_down": ("micro_batch",),
    "recompute_on": ("recompute",),
    "rebalance_parallel": ("tp", "pp", "dp"),
    "layers_down": ("layers", "scope_gap"),
    "resume_from_checkpoint": (),
    "restart_clean": (),
}


def _positive_integer(value):
    return type(value) is int and value >= 1


def _validate_degrade_ladder(ladder):
    """A declared, bounded list of repairs an Agent may apply without a person."""
    if not isinstance(ladder, list) or not ladder:
        raise FlowError("Degrade ladder must be a nonempty list")
    seen = set()
    for row in ladder:
        if not isinstance(row, dict):
            raise FlowError("Invalid degrade step")
        action = row.get("action")
        if action not in DEGRADE_ACTIONS:
            raise FlowError("Unknown degrade action")
        if action in seen:
            raise FlowError("Degrade actions must be unique")
        seen.add(action)
        required, optional = DEGRADE_ACTIONS[action]
        allowed = {"action", *required, *optional}
        if set(row) - allowed or set(required) - set(row):
            raise FlowError("Degrade step fields do not match its action: " + action)
        if action == "micro_batch_down" and not _positive_integer(row["min"]):
            raise FlowError("Degrade requires a positive micro-batch floor")
        if action == "layers_down" and not _positive_integer(row["min_layers"]):
            raise FlowError("Degrade requires a positive layer floor")
        if action in {"recompute_on", "rebalance_parallel"}:
            names = row["allow"]
            if (not isinstance(names, list) or not names
                    or any(not isinstance(name, str) or not name.strip() for name in names)
                    or len(set(names)) != len(names)):
                raise FlowError("Degrade allow-list must contain distinct names")
        if "max_attempts" in row and not _positive_integer(row["max_attempts"]):
            raise FlowError("max_attempts must be a positive integer")
        if "record_scope_gap" in row and type(row["record_scope_gap"]) is not bool:
            raise FlowError("record_scope_gap must be boolean")


def _validate_budget_extension(value):
    allowed = {"max_additions", "operations_per_addition",
               "hard_total_operations", "seconds_per_addition"}
    if not isinstance(value, dict) or set(value) - allowed:
        raise FlowError("Unknown budget extension fields")
    for key in ("max_additions", "operations_per_addition", "hard_total_operations"):
        if not _positive_integer(value.get(key)):
            raise FlowError("Budget extension requires positive integers: " + key)
    if value["operations_per_addition"] > value["hard_total_operations"]:
        raise FlowError("Per-addition operations cannot exceed the hard total ceiling")
    if "seconds_per_addition" in value:
        seconds = value["seconds_per_addition"]
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not 0 < seconds < float("inf"):
            raise FlowError("seconds_per_addition must be positive and finite")


def validate_autonomy(autonomy):
    """Closed policy language for tasks that have no human channel.

    Only declared decisions are permitted: who may review, which recurring
    questions have a written answer, and which bounded repairs or budget
    additions an Agent may apply on its own. Unknown fields are rejected so a
    policy cannot silently grow into an unbounded permission grant.
    """
    allowed = {"mode", "reviewers", "question_answers", "escalation"}
    if not isinstance(autonomy, dict) or set(autonomy) - allowed:
        raise FlowError("Unknown autonomy policy fields")
    if autonomy.get("mode") != "autonomous":
        raise FlowError("Only mode=autonomous is supported")
    reviewers = autonomy.get("reviewers")
    if (not isinstance(reviewers, list) or not reviewers
            or any(not isinstance(name, str) or not name.strip() for name in reviewers)
            or len(set(reviewers)) != len(reviewers)):
        raise FlowError("Autonomy requires distinct declared reviewer identities")
    answers = autonomy.get("question_answers", [])
    if not isinstance(answers, list):
        raise FlowError("Autonomy question answers must be a list")
    for row in answers:
        if (not isinstance(row, dict) or set(row) != {"match", "answer", "source"}
                or any(not isinstance(row[key], str) or not row[key].strip() for key in row)):
            raise FlowError("Autonomy answers require nonempty match, answer and source")
    escalation = autonomy.get("escalation", {})
    if not isinstance(escalation, dict) or set(escalation) - {"degrade_ladder", "budget_extension", "acceptance_edit"}:
        raise FlowError("Unknown autonomy escalation fields")
    if "degrade_ladder" in escalation:
        _validate_degrade_ladder(escalation["degrade_ladder"])
    if "budget_extension" in escalation:
        _validate_budget_extension(escalation["budget_extension"])
    if "acceptance_edit" in escalation and escalation["acceptance_edit"] not in {"forbid", "add-only"}:
        raise FlowError("acceptance_edit must be forbid or add-only")
    return autonomy


PROFILE_ID = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")


def validate_spec(spec):
    allowed = {"schema_version", "task_id", "mode", "objective", "context", "permissions",
               "recovery_owner", "budget", "external_job", "autonomy", "profile",
               "shadow_guardrails"}
    if set(spec) - allowed or spec.get("schema_version") != 1:
        raise FlowError("Unsupported TaskSpec version or unknown fields")
    safe_id(spec.get("task_id"))
    if spec.get("mode") not in MODES or not isinstance(spec.get("objective"), str) or not spec["objective"].strip():
        raise FlowError("Task requires a supported mode and objective")
    if not isinstance(spec.get("context"), dict) or not spec["context"]:
        raise FlowError("Context must identify the evidence/model/environment scope")
    permissions = spec.get("permissions", [])
    if not isinstance(permissions, list) or set(permissions) - {"execute", "sync", "notify", "agent-dispatch"}:
        raise FlowError("Unknown permissions; training recovery belongs to the configured external owner")
    if "budget" in spec and (not isinstance(spec["budget"], dict) or set(spec["budget"]) - {"max_operations", "max_seconds"}):
        raise FlowError("Invalid budget")
    for value in spec.get("budget", {}).values():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value < float("inf"):
            raise FlowError("Budgets must be positive finite numbers")
    if "autonomy" in spec:
        validate_autonomy(spec["autonomy"])
    if "shadow_guardrails" in spec and spec["shadow_guardrails"] is not True:
        # Declared at creation so an operator decides to measure; an agent
        # cannot switch the guardrails into observation mode mid-run.
        raise FlowError("shadow_guardrails must be true when declared")
    if "profile" in spec:
        # A sub-workflow selection must be reproducible: the chosen id and the
        # reason it was chosen are both required, so a later reader can tell
        # whether the thinning was deliberate.
        profile = spec["profile"]
        if not isinstance(profile, dict) or set(profile) != {"id", "reason"}:
            raise FlowError("Task profile requires exactly id and reason")
        if not isinstance(profile["id"], str) or not PROFILE_ID.match(profile["id"]):
            raise FlowError("Task profile id must be a hyphenated slug")
        if not isinstance(profile["reason"], str) or not profile["reason"].strip():
            raise FlowError("Task profile requires a reason for the chosen sub-workflow")
    return spec


class Store:
    def __init__(self, root):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "state.sqlite3"
        with self.db() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,spec TEXT NOT NULL,state TEXT NOT NULL,context TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 0,created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS artifacts(id TEXT PRIMARY KEY,path TEXT NOT NULL,size INTEGER NOT NULL,visibility TEXT NOT NULL,created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS reports(task TEXT,kind TEXT,context TEXT,artifact TEXT,result TEXT,created TEXT,PRIMARY KEY(task,kind,context));
            CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,event_id TEXT UNIQUE,task TEXT,kind TEXT,payload TEXT,created TEXT);
            CREATE INDEX IF NOT EXISTS events_artifact ON events(json_extract(payload,'$.artifact'));
            CREATE INDEX IF NOT EXISTS events_task ON events(task,seq);
            CREATE INDEX IF NOT EXISTS events_task_kind ON events(task,kind,seq);
            CREATE TABLE IF NOT EXISTS outbox(event_id TEXT PRIMARY KEY,channel TEXT,status TEXT,attempts INTEGER DEFAULT 0,detail TEXT);
            CREATE TABLE IF NOT EXISTS leases(resource TEXT PRIMARY KEY,owner TEXT,token INTEGER,expires REAL);
            CREATE TABLE IF NOT EXISTS operations(id TEXT PRIMARY KEY,task TEXT,request_hash TEXT,status TEXT,result TEXT,created TEXT);
            CREATE TABLE IF NOT EXISTS cursors(peer TEXT PRIMARY KEY,seq INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS assignments(id TEXT PRIMARY KEY,task TEXT,payload TEXT,status TEXT);
            CREATE TABLE IF NOT EXISTS flows(task TEXT PRIMARY KEY,plan TEXT,goal TEXT,context TEXT);
            CREATE TABLE IF NOT EXISTS budget_extensions(task TEXT NOT NULL,addition INTEGER NOT NULL,operations INTEGER NOT NULL,seconds REAL NOT NULL,reason TEXT NOT NULL,artifact TEXT,created TEXT NOT NULL,PRIMARY KEY(task,addition));
            CREATE TABLE IF NOT EXISTS pipeline_runs(id TEXT PRIMARY KEY,task TEXT NOT NULL,name TEXT NOT NULL,plan TEXT NOT NULL,context TEXT NOT NULL,revision INTEGER NOT NULL,status TEXT NOT NULL,result TEXT,created TEXT NOT NULL,updated TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS pipeline_steps(run TEXT NOT NULL,step TEXT NOT NULL,capability TEXT NOT NULL,action TEXT NOT NULL,status TEXT NOT NULL,artifact TEXT,report TEXT,result TEXT NOT NULL,created TEXT NOT NULL,updated TEXT NOT NULL,PRIMARY KEY(run,step));
            CREATE TABLE IF NOT EXISTS flow_rounds(task TEXT,number INTEGER,context TEXT,revision INTEGER,goal TEXT,candidate TEXT,review TEXT,status TEXT,failures INTEGER DEFAULT 0,PRIMARY KEY(task,number));
            CREATE TABLE IF NOT EXISTS flow_guidance(task TEXT,id TEXT,context TEXT,status TEXT,note TEXT,created TEXT,PRIMARY KEY(task,id));
            CREATE TABLE IF NOT EXISTS flow_guidance_cursor(task TEXT PRIMARY KEY,hash TEXT);
            CREATE TABLE IF NOT EXISTS flow_guidance_scans(task TEXT PRIMARY KEY,checked_at REAL);
            CREATE TABLE IF NOT EXISTS flow_questions(task TEXT,id TEXT,payload TEXT,status TEXT,resolution TEXT,PRIMARY KEY(task,id));
            CREATE TABLE IF NOT EXISTS file_question_scans(task TEXT PRIMARY KEY,hash TEXT,checked_at REAL,scope TEXT,error TEXT);
            CREATE TABLE IF NOT EXISTS file_question_versions(task TEXT,id TEXT,version TEXT,scope TEXT,payload TEXT,status TEXT,answer TEXT,created TEXT,PRIMARY KEY(task,id,version,scope));
            CREATE TABLE IF NOT EXISTS file_question_current(task TEXT,id TEXT,version TEXT,scope TEXT,PRIMARY KEY(task,id));
            CREATE TABLE IF NOT EXISTS file_question_answers(task TEXT,id TEXT,payload TEXT,status TEXT,created TEXT,PRIMARY KEY(task,id));
            CREATE TABLE IF NOT EXISTS flow_status(task TEXT PRIMARY KEY,payload TEXT,created TEXT);
            CREATE TABLE IF NOT EXISTS team_plans(task TEXT PRIMARY KEY,artifact TEXT,max_parallel INTEGER);
            CREATE TABLE IF NOT EXISTS assignment_runs(assignment TEXT PRIMARY KEY,token INTEGER,session TEXT,inputs TEXT,report TEXT,updated TEXT,note TEXT);
            CREATE TABLE IF NOT EXISTS assignment_operations(operation TEXT PRIMARY KEY,assignment TEXT,token INTEGER);
            CREATE TABLE IF NOT EXISTS agent_messages(id TEXT PRIMARY KEY,task TEXT,payload TEXT,status TEXT,created TEXT,receipt TEXT);
            """)
            row = db.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
            if row and row[0] != "1":
                raise FlowError("Unsupported workspace schema; do not overwrite it")
            db.execute("INSERT OR IGNORE INTO meta VALUES('schema','1')")
            columns = {row[1] for row in db.execute('PRAGMA table_info(pipeline_runs)')}
            if 'input_identity' not in columns:
                db.execute('ALTER TABLE pipeline_runs ADD COLUMN input_identity TEXT')

    @contextlib.contextmanager
    def db(self):
        db = sqlite3.connect(self.db_path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def event(self, db, task, kind, payload, event_id=None, channel=None):
        eid = event_id or uuid.uuid4().hex
        existing = db.execute("SELECT * FROM events WHERE event_id=?", (eid,)).fetchone()
        body = json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False)
        if existing:
            if (existing["task"], existing["kind"], existing["payload"]) != (task, kind, body):
                raise FlowError("An event ID cannot be reused for different content")
            return eid
        db.execute("INSERT INTO events(event_id,task,kind,payload,created) VALUES(?,?,?,?,?)", (eid, task, kind, body, utc()))
        if channel:
            db.execute("INSERT INTO outbox(event_id,channel,status) VALUES(?,?,'pending')", (eid, channel))
        return eid

    def create(self, spec):
        validate_spec(spec)
        with self.db() as db:
            db.execute("INSERT INTO tasks(id,spec,state,context,created) VALUES(?,?,'draft',?,?)", (spec["task_id"], json.dumps(spec), fingerprint(spec["context"]), utc()))
            self.event(db, spec["task_id"], "task-created", {"mode": spec["mode"]})
        return self.task(spec["task_id"])

    def task(self, tid):
        with self.db() as db:
            row = db.execute("SELECT tasks.*, (SELECT COALESCE(MAX(seq),0) FROM events WHERE task=tasks.id AND kind='context-changed') AS context_epoch FROM tasks WHERE id=?", (tid,)).fetchone()
        if not row:
            raise FlowError("Unknown task: " + tid)
        result = dict(row)
        result["spec"] = json.loads(result["spec"])
        return result

    def put(self, data, visibility="private"):
        return self.put_many([data], visibility)[0]

    def put_many(self, payloads, visibility="private"):
        """Persist each object, then register the whole batch in one transaction.

        Payloads may be a generator: only hashes/metadata remain in memory.
        An interrupted write can leave unregistered immutable objects, never a
        registered partial batch. A retry verifies and reuses those objects.
        """
        if visibility not in {"private", "public"}:
            raise FlowError("Invalid visibility")
        hashes, records = [], {}
        for data in payloads:
            sha = digest(data)
            path = self.root / "objects" / sha[:2] / sha
            if sha not in records:
                try:
                    published = _read_object(path)
                except FileNotFoundError:
                    _publish_object(path, data)
                else:
                    if digest(published) != sha:
                        raise FlowError("Corrupted existing artifact")
                records[sha] = (path.relative_to(self.root).as_posix(), len(data))
            hashes.append(sha)
        if not records:
            return hashes
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            created = utc()
            # Evaluate visibility inside the write lock: a concurrent private
            # registration cannot be promoted by a public re-import.
            db.executemany("INSERT INTO artifacts VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                           "visibility=CASE WHEN artifacts.visibility='private' THEN 'private' ELSE excluded.visibility END",
                           ((sha, path, size, visibility, created) for sha, (path, size) in records.items()))
        return hashes

    def artifact(self, sha):
        with contextlib.closing(self.iter_artifacts([sha])) as objects:
            return next(objects)[1]

    def iter_artifacts(self, hashes):
        """Stream verified objects while reusing one read connection."""
        with self.db() as db:
            for sha in hashes:
                row = db.execute("SELECT * FROM artifacts WHERE id=?", (sha,)).fetchone()
                if not row:
                    raise FlowError("Unknown artifact")
                data = _read_object(child(self.root, row["path"]))
                if len(data) != row["size"] or digest(data) != sha:
                    raise FlowError("Artifact hash mismatch")
                yield sha, data

    def artifact_tasks(self, sha):
        """Tasks a retained object is already attributable to.

        Attribution comes from whatever recorded the object: an event that
        names it, a Pipeline step that produced it, or an operation result.
        Unattributed and public objects stay usable (existing workspaces and
        shared baselines keep working), but a private object attributable only
        to another task may not be cited here.
        """

        from .integrity import artifact_owners

        with self.db() as db:
            return artifact_owners(db, sha)

    def artifact_public(self, sha):
        """Public objects are the declared way to share evidence across tasks."""

        with self.db() as db:
            row = db.execute("SELECT visibility FROM artifacts WHERE id=?", (sha,)).fetchone()
        return bool(row) and row[0] == "public"

    def attribute_evidence(self, tid=None):
        """Backfill attribution for evidence recorded before it was tracked.

        Reports written before attribution existed still name their evidence in
        the body, so the owner can be recovered from them. Idempotent: an object
        that already has a claim event for this task is skipped.
        """

        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            query = "SELECT task,kind,artifact FROM reports"
            rows = db.execute(query + (" WHERE task=?" if tid else ""),
                              ((tid,) if tid else ())).fetchall()
            written = 0
            for row in rows:
                body = json.loads(self.artifact(row["artifact"]))
                for sha in body.get("evidence") or []:
                    known = db.execute(
                        "SELECT 1 FROM events WHERE task=? AND kind='artifact-claimed'"
                        " AND json_extract(payload,'$.artifact')=?",
                        (row["task"], sha)).fetchone()
                    if known:
                        continue
                    self.event(db, row["task"], "artifact-claimed",
                               {"artifact": sha, "kind": row["kind"], "backfilled": True})
                    written += 1
            return {"reports": len(rows), "attributed": written}

    def report(self, tid, kind, value, *, expected_revision=None, agent_authored=True,
               shadow=False):
        task = self.task(tid)
        if expected_revision is not None and task["revision"] != expected_revision:
            raise PipelineContextConflict("Task revision changed before recording Pipeline report")
        if value.get("context") != task["context"]:
            raise FlowError("Report belongs to another environment/model/source context")
        if value.get("status") not in {"pass", "fail", "incomplete", "complete"}:
            raise FlowError("Report needs an explicit status")
        if not value.get("evidence") or not isinstance(value["evidence"], list):
            raise FlowError("Report requires retained evidence IDs")
        if shadow and task["spec"].get("shadow_guardrails") is not True:
            # Measuring is declared when the task is created; a run cannot opt
            # itself into observation mode to get past a refusal.
            raise FlowError("shadow mode requires shadow_guardrails declared at task creation")
        problems = []
        for sha in value["evidence"]:
            self.artifact(sha)
            owners = set() if self.artifact_public(sha) else self.artifact_tasks(sha)
            if owners and tid not in owners:
                problems.append("Evidence " + sha + " belongs to another task")
        from .integrity import check_claims, claims_required
        # Claims are checked here, at the boundary where the evidence is turned
        # into a conclusion, not at the end of the flow: detectability decays
        # once a number has become prose. A capability-computed report is
        # already derived from typed inputs, so only agent-authored prose must
        # carry them; any claims it does state are still verified.
        try:
            check_claims(self, task, kind, value,
                         require=agent_authored and claims_required(task, kind))
        except FlowError as exc:
            problems.append(str(exc))
        if problems and not shadow:
            raise FlowError(problems[0])
        if value["status"] == "pass" and not valid_pass(value):
            raise FlowError("PASS requires actual execution, no failures and required coverage")
        if kind == "stage-quality" and value["status"] == "pass":
            from .quality import validate_stage_report
            validate_stage_report(self, value)
        data = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
        sha = self.put(data)
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("SELECT context,revision FROM tasks WHERE id=?", (tid,)).fetchone()
            if expected_revision is not None and current["revision"] != expected_revision:
                raise PipelineContextConflict("Task revision changed while recording Pipeline report")
            if current["context"] != task["context"] or context_epoch(db, tid) != task["context_epoch"]:
                raise FlowError("Task context changed while recording report; revalidate before retrying")
            db.execute("INSERT OR REPLACE INTO reports VALUES(?,?,?,?,?,?)", (tid, kind, task["context"], sha, value["status"], utc()))
            self.event(db, tid, "report-recorded", {"kind": kind, "artifact": sha, "status": value["status"],
                                                   "context_spec": task['spec']['context']})
            if problems:
                # Declared measurement: the report stands, the refusal it would
                # have earned is retained so the false-positive rate is countable.
                self.event(db, tid, "integrity-shadow",
                           {"kind": kind, "artifact": sha, "problems": problems})
            # Remember which task produced each cited object, so a later report
            # cannot borrow evidence that belongs to another task.
            for item in value["evidence"]:
                self.event(db, tid, "artifact-claimed", {"artifact": item, "kind": kind})
        from .experience import sync
        try:
            knowledge=sync(self,tid)
        except (OSError,ValueError,sqlite3.Error) as exc:
            knowledge={'status':'pending','reason':type(exc).__name__,'resume':'experience-sync '+tid}
        return {"artifact": sha, "status": value["status"], 'knowledge':knowledge}

    def current_reports(self, db, tid, context):
        """Keep historical reports, but only expose evidence recorded since the last reset."""
        rows = db.execute("""SELECT r.* FROM reports r WHERE r.task=? AND r.context=? AND EXISTS (
            SELECT 1 FROM events e WHERE e.task=r.task AND e.kind='report-recorded'
            AND json_extract(e.payload,'$.kind')=r.kind
            AND json_extract(e.payload,'$.artifact')=r.artifact AND e.seq>?)""",
            (tid, context, context_epoch(db, tid)))
        result = {}
        for row in rows:
            if row["result"] == "pass":
                value = json.loads(self.artifact(row["artifact"]))
                if not valid_pass(value):
                    continue
                if row["kind"] == "stage-quality":
                    from .quality import validate_stage_report
                    try:
                        validate_stage_report(self, value)
                    except FlowError:
                        # Historical artifacts remain readable but cannot grant
                        # a new transition using an incomplete old contract.
                        continue
            result[row["kind"]] = row
        return result

    def pipeline_start(self, tid, run_id, name, plan, context, revision, input_identity=None):
        """Create or resume a task-bound Pipeline run.

        The run identity is supplied by the orchestrator and should include
        the task, plan, context and revision.  Reusing an ID with different
        inputs is rejected so a stale run cannot write into a new context.
        """

        # Empty task denotes a standalone run, without a synthetic Task row.
        tid = tid or ""
        if tid:
            task = self.task(tid)
            if task["context"] != context or task["revision"] != revision:
                raise PipelineContextConflict("Pipeline context or revision is stale")
        if not isinstance(run_id, str) or not run_id.strip() or not isinstance(name, str) or not name.strip():
            raise FlowError("Pipeline run requires an ID and name")
        if not isinstance(plan, dict):
            raise FlowError("Pipeline plan must be an object")
        plan_body = json.dumps(plan, sort_keys=True, ensure_ascii=False, allow_nan=False)
        now = utc()
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            self._pipeline_identity(db, {"task": tid, "context": context, "revision": revision})
            row = db.execute("SELECT * FROM pipeline_runs WHERE id=?", (run_id,)).fetchone()
            if row:
                if (row["task"], row["name"], row["plan"], row["context"], row["revision"], row["input_identity"]) != (tid, name, plan_body, context, revision, input_identity):
                    raise FlowError("Pipeline run ID is already bound to different inputs")
                return dict(row)
            db.execute("INSERT INTO pipeline_runs(id,task,name,plan,context,revision,status,result,created,updated,input_identity) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       (run_id, tid, name, plan_body, context, revision, "running", None, now, now, input_identity))
            self.event(db, tid, "pipeline-started", {"run": run_id, "name": name, "context": context, "revision": revision})
            return {"id": run_id, "task": tid, "name": name, "plan": plan_body,
                    "context": context, "revision": revision, "status": "running",
                    "result": None, "created": now, "updated": now}

    @staticmethod
    def _pipeline_identity(db, run):
        if not run["task"]:
            return
        task = db.execute("SELECT context,revision FROM tasks WHERE id=?", (run["task"],)).fetchone()
        if not task or task["context"] != run["context"] or task["revision"] != run["revision"]:
            raise PipelineContextConflict("Task context or revision changed while running Pipeline")

    def pipeline_reopen(self, run_id):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            run = db.execute("SELECT * FROM pipeline_runs WHERE id=?", (run_id,)).fetchone()
            if not run:
                raise FlowError("Unknown Pipeline run")
            self._pipeline_identity(db, run)
            db.execute("UPDATE pipeline_runs SET status='running',result=NULL,updated=? WHERE id=?", (utc(), run_id))

    def pipeline_step(self, run_id, step, capability, action, status, result, artifact=None, report=None):
        """Persist one immutable step result after rechecking task identity."""

        if not isinstance(result, dict):
            raise FlowError("Pipeline step result must be an object")
        if status not in {"pass", "complete", "fail", "incomplete", "unknown", "blocked"}:
            raise FlowError("Unsupported Pipeline step status")
        body = json.dumps(result, sort_keys=True, ensure_ascii=False, allow_nan=False)
        now = utc()
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            run = db.execute("SELECT * FROM pipeline_runs WHERE id=?", (run_id,)).fetchone()
            if not run:
                raise FlowError("Unknown Pipeline run")
            if run["status"] not in {"running", "incomplete", "failed"}:
                raise FlowError("Pipeline run is already terminal")
            self._pipeline_identity(db, run)
            db.execute("INSERT INTO pipeline_steps VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(run,step) DO UPDATE SET "
                       "capability=excluded.capability,action=excluded.action,status=excluded.status,artifact=excluded.artifact,report=excluded.report,result=excluded.result,updated=excluded.updated",
                       (run_id, step, capability, action, status, artifact, report, body, now, now))
            self.event(db, run["task"], "pipeline-step-recorded", {"run": run_id, "step": step,
                                                                      "status": status, "artifact": artifact, "report": report})
        return {"run": run_id, "step": step, "status": status, "artifact": artifact, "report": report}

    def pipeline_finish(self, run_id, status, result):
        if status not in {"complete", "incomplete", "failed", "blocked", "interrupted", "conflicted"}:
            raise FlowError("Unsupported Pipeline run status")
        body = json.dumps(result, sort_keys=True, ensure_ascii=False, allow_nan=False)
        now = utc()
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            run = db.execute("SELECT * FROM pipeline_runs WHERE id=?", (run_id,)).fetchone()
            if not run:
                raise FlowError("Unknown Pipeline run")
            if status != "conflicted":
                self._pipeline_identity(db, run)
            db.execute("UPDATE pipeline_runs SET status=?,result=?,updated=? WHERE id=?", (status, body, now, run_id))
            self.event(db, run["task"], "pipeline-finished", {"run": run_id, "status": status})
        return {"run": run_id, "status": status}

    def effective_budget(self, db, tid):
        """Declared budget plus graded, policy-authorized extensions."""
        row = db.execute("SELECT spec FROM tasks WHERE id=?", (tid,)).fetchone()
        if not row:
            raise FlowError("Unknown task")
        budget = (json.loads(row["spec"]) or {}).get("budget") or {}
        operations = budget.get("max_operations", 100)
        seconds = budget.get("max_seconds", float("inf"))
        for extra in db.execute("SELECT operations,seconds FROM budget_extensions WHERE task=?", (tid,)):
            operations += extra["operations"]
            seconds += extra["seconds"]
        return {"max_operations": operations, "max_seconds": seconds}

    def budget_extension(self, tid, operations, seconds, reason):
        """Add execution budget only where the autonomy policy pre-authorized it.

        The policy's hard ceiling is absolute: an Agent may spend approved
        headroom but never invent it, and every addition stays in the ledger and
        event log with its stated reason.
        """
        task = self.task(tid)
        policy = task["spec"].get("autonomy") or {}
        rules = (policy.get("escalation") or {}).get("budget_extension")
        if not isinstance(rules, dict):
            raise FlowError("Task policy does not authorize budget extensions")
        if not isinstance(reason, str) or not reason.strip():
            raise FlowError("A budget extension needs the observed blocking reason")
        if type(operations) is not int or operations < 0:
            raise FlowError("Budget extension operations must be a nonnegative integer")
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or seconds < 0 or not math.isfinite(seconds):
            raise FlowError("Budget extension seconds must be finite and nonnegative")
        if operations > rules["operations_per_addition"]:
            raise FlowError("Requested operations exceed the declared per-addition limit")
        if "seconds_per_addition" in rules and seconds > rules["seconds_per_addition"]:
            raise FlowError("Requested seconds exceed the declared per-addition limit")
        with self.db() as db:
            task_row = db.execute("SELECT spec FROM tasks WHERE id=?", (tid,)).fetchone()
            if not task_row or json.loads(task_row["spec"]).get("autonomy") != policy:
                raise FlowError("Task policy changed while requesting an extension")
            rows = db.execute("SELECT operations FROM budget_extensions WHERE task=?", (tid,)).fetchall()
            if len(rows) >= rules["max_additions"]:
                raise FlowError("Budget extension allowance is exhausted")
            declared = ((json.loads(task_row["spec"]) or {}).get("budget") or {}).get("max_operations", 100)
            if declared + sum(row["operations"] for row in rows) + operations > rules["hard_total_operations"]:
                raise FlowError("Budget extension would exceed the declared hard operations ceiling")
            addition = db.execute("SELECT COALESCE(MAX(addition),0) FROM budget_extensions WHERE task=?",
                                  (tid,)).fetchone()[0] + 1
        ledger = {"kind": "autonomy-budget-extension", "context": task["context"],
                  "actor": "autonomy-policy", "policy": fingerprint(policy),
                  "addition": addition, "operations": operations, "seconds": seconds, "reason": reason}
        sha = self.put(json.dumps(ledger, sort_keys=True, ensure_ascii=False, allow_nan=False).encode())
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT INTO budget_extensions VALUES(?,?,?,?,?,?,?)",
                       (tid, addition, operations, seconds, reason, sha, utc()))
            self.event(db, tid, "budget-extended",
                       {"addition": addition, "operations": operations, "seconds": seconds,
                        "reason": reason, "evidence": sha, "actor": "autonomy-policy"})
            budget = self.effective_budget(db, tid)
        return {"task": tid, "addition": addition, "evidence": sha, "budget": budget,
                "remaining_additions": rules["max_additions"] - addition}

    def pipeline_state(self, run_id):
        with self.db() as db:
            run = db.execute("SELECT * FROM pipeline_runs WHERE id=?", (run_id,)).fetchone()
            if not run:
                raise FlowError("Unknown Pipeline run")
            steps = [dict(row) for row in db.execute("SELECT * FROM pipeline_steps WHERE run=? ORDER BY rowid", (run_id,))]
        value = dict(run)
        value["steps"] = steps
        if value.get("result"):
            value["result"] = json.loads(value["result"])
        for step in steps:
            step["result"] = json.loads(step["result"])
        return value

    def change_context(self, tid, context):
        if not isinstance(context, dict) or not context:
            raise FlowError("A nonempty context is required")
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
            if not row:
                raise FlowError("Unknown task")
            if row["state"] in {"completed", "cancelled"}:
                raise FlowError("Terminal task; create a new task for a new context")
            spec = json.loads(row["spec"])
            spec["context"] = context
            db.execute("UPDATE tasks SET spec=?,context=?,state='prepared',revision=revision+1 WHERE id=?", (json.dumps(spec), fingerprint(context), tid))
            self.event(db, tid, "context-changed", {"old": row["context"], "new": fingerprint(context), "evidence": "requires-revalidation"})
        return self.task(tid)

    def transition(self, tid, state, reason=None):
        from .flow import sync_guidance, guard_transition
        sync_guidance(self, tid)
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
            if not row:
                raise FlowError("Unknown task")
            spec = json.loads(row["spec"])
            if row["state"] in {"completed", "cancelled"}:
                raise FlowError("Terminal task; create a new task")
            guard_transition(self, db, dict(row), state)
            if state in {"paused", "blocked", "failed", "cancelled"}:
                if not reason:
                    raise FlowError("A reason is required")
            else:
                modes = {"environment": "environment", "adapt": "baseline", "analyze": "analysis", "diagnose": "diagnosis", "optimize": "stage-quality", "operate": "operations"}
                reports = self.current_reports(db, tid, row["context"])
                if state == "completed" and spec["mode"] in modes:
                    kind = modes[spec["mode"]]
                    if kind not in reports:
                        raise FlowError("Missing requested deliverable: " + kind)
                    if spec["mode"] in {"adapt", "optimize"} and reports[kind]["result"] != "pass":
                        raise FlowError("The requested validated result has not passed")
                elif state == "prepared":
                    if row["state"] not in {"draft", "paused", "blocked", "failed"}:
                        raise FlowError("Cannot reset an active task without a context change")
                else:
                    if state not in PIPELINE or row["state"] not in PIPELINE or PIPELINE.index(state) != PIPELINE.index(row["state"]) + 1:
                        raise FlowError("Invalid state transition")
                    for kind in GATES.get(state, []):
                        accepted = {"pass", "complete"} if kind == "analysis" else {"pass"}
                        if kind not in reports or reports[kind]["result"] not in accepted:
                            raise FlowError("Missing passing current evidence: " + kind)
            db.execute("UPDATE tasks SET state=?,revision=revision+1 WHERE id=?", (state, tid))
            self.event(db, tid, "state-changed", {"from": row["state"], "to": state, "reason": reason})
        return self.task(tid)

    def lease(self, resource, owner, ttl=300):
        _check_lease_ttl(ttl)
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            running = db.execute("SELECT o.id FROM operations o JOIN events e ON json_extract(e.payload,'$.operation')=o.id WHERE e.kind='operation-started' AND json_extract(e.payload,'$.lease.resource')=? AND o.status IN ('started','unknown')", (resource,)).fetchone()
            if running:
                raise FlowError("Resource has an unresolved execution; reconcile before acquiring it")
            row = db.execute("SELECT * FROM leases WHERE resource=?", (resource,)).fetchone()
            if row and _check_lease_expiry(row) > time.time():
                raise FlowError("Resource is already leased; renew with its fencing token")
            token = row["token"] + 1 if row else 1
            db.execute("INSERT OR REPLACE INTO leases VALUES(?,?,?,?)", (resource, owner, token, time.time() + ttl))
        return {"resource": resource, "owner": owner, "token": token}

    def check_lease(self, db, resource, owner, token):
        row = db.execute("SELECT * FROM leases WHERE resource=?", (resource,)).fetchone()
        if not row or row["owner"] != owner or row["token"] != token:
            raise FlowError("Expired lease or stale fencing token")
        if _check_lease_expiry(row) <= time.time():
            raise FlowError("Expired lease or stale fencing token")

    def renew(self, lease, ttl=300):
        _check_lease_ttl(ttl)
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            self.check_lease(db, **lease)
            db.execute("UPDATE leases SET expires=? WHERE resource=?", (time.time() + ttl, lease["resource"]))
        return lease

    def events(self, after=0):
        with self.db() as db:
            return [{**dict(x), "payload": json.loads(x["payload"])} for x in db.execute("SELECT * FROM events WHERE seq>? ORDER BY seq", (after,))]

    def release(self, lease):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            self.check_lease(db, **lease)
            db.execute("UPDATE leases SET expires=0 WHERE resource=?", (lease["resource"],))
        return {**lease, "released": True}
