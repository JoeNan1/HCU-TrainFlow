"""Re-check a store's recorded reports against the current guardrails, read-only.

The write path refuses a report whose evidence is not attributable to the task
or whose claims do not resolve. This script asks the same questions of reports
that were accepted *before* those rules existed: a false positive here would
invalidate a real, already reviewed result, so the audit is the precision half
of the fault-injection tests.

    python scripts/audit_report_history.py STORE [STORE ...]
    python scripts/audit_report_history.py --json STORE

The database (and any WAL side files) is copied to a temporary directory and
read there, so the store directory gains no ``-wal``/``-shm`` and a read-only
mount works. Large *evidence* objects are checked for presence and size but not
re-digested; report bodies are always read in full, since a size cap applied to
a body turns a valid large report into a false positive.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hcu_trainflow import integrity  # noqa: E402
from hcu_trainflow.core import FlowError  # noqa: E402

MAX_DIGEST = 8 * 1024 * 1024


class ReadOnlyStore:
    """The slice of ``Store`` the claim checks need, backed by a private copy."""

    def __init__(self, root):
        self.root = Path(root)
        source = self.root / "state.sqlite3"
        if not source.exists():
            raise SystemExit("No state.sqlite3 under " + str(self.root))
        self._temp = tempfile.TemporaryDirectory(prefix="trainflow-audit-")
        self.path = Path(self._temp.name) / "state.sqlite3"
        shutil.copy2(source, self.path)
        for suffix in ("-wal", "-shm"):
            side = Path(str(source) + suffix)
            if side.exists():
                shutil.copy2(side, str(self.path) + suffix)

    @contextlib.contextmanager
    def db(self):
        connection = sqlite3.connect("file:" + str(self.path) + "?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        finally:
            connection.close()

    def task(self, tid):
        with self.db() as db:
            row = db.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
        if not row:
            raise FlowError("Unknown task " + tid)
        return {**dict(row), "spec": json.loads(row["spec"])}

    def _read(self, sha, limit):
        with self.db() as db:
            row = db.execute("SELECT path,size FROM artifacts WHERE id=?", (sha,)).fetchone()
        if not row:
            raise FlowError("Unknown artifact")
        path = (self.root / row["path"]).resolve()
        if not path.is_file() or path.stat().st_size != row["size"]:
            raise FlowError("Artifact missing or resized: " + sha)
        if limit is not None and row["size"] > limit:
            return b""  # presence checked; the digest is not needed to audit evidence
        return path.read_bytes()

    def artifact(self, sha):
        """Evidence object: size-capped, because only presence is audited."""

        return self._read(sha, MAX_DIGEST)

    def report_body(self, sha):
        """Report bodies are parsed in full; a size cap would flag a valid report."""

        return self._read(sha, None)

    def artifact_tasks(self, sha):
        with self.db() as db:
            return integrity.artifact_owners(db, sha)

    def artifact_public(self, sha):
        with self.db() as db:
            row = db.execute("SELECT visibility FROM artifacts WHERE id=?", (sha,)).fetchone()
        return bool(row) and row["visibility"] == "public"


def audit(root):
    store = ReadOnlyStore(root)
    result = {"store": str(root), "tasks": [], "reports": 0, "flagged": [], "unattributed": 0}
    with store.db() as db:
        tasks = [row["id"] for row in db.execute("SELECT id FROM tasks ORDER BY id")]
        rows = db.execute("SELECT task,kind,context,artifact,result FROM reports"
                          " ORDER BY task,kind").fetchall()
    for tid in tasks:
        task = store.task(tid)
        result["tasks"].append({"task": tid, "state": task["state"],
                                "profile": (task["spec"].get("profile") or {}).get("id")
                                if task["spec"].get("profile") else None,
                                "reports": sum(1 for row in rows if row["task"] == tid)})
    for row in rows:
        result["reports"] += 1
        task = store.task(row["task"])
        try:
            body = json.loads(store.report_body(row["artifact"]))
        except (FlowError, ValueError) as exc:
            result["flagged"].append({"task": row["task"], "kind": row["kind"],
                                      "problem": "unreadable report: " + str(exc)})
            continue
        try:
            integrity.check_claims(store, task, row["kind"], body,
                                   require=integrity.claims_required(task, row["kind"]))
        except FlowError as exc:
            result["flagged"].append({"task": row["task"], "kind": row["kind"],
                                      "problem": str(exc)})
            continue
        for sha in body.get("evidence") or []:
            try:
                store.artifact(sha)
                owners = set() if store.artifact_public(sha) else store.artifact_tasks(sha)
            except (FlowError, OSError) as exc:
                result["flagged"].append({"task": row["task"], "kind": row["kind"],
                                          "problem": "unreadable evidence " + sha + ": " + str(exc)})
                break
            if not owners:
                # A store written before attribution existed cannot refuse a
                # borrowed object; ``evidence-backfill`` recovers the owner from
                # the report bodies themselves.
                result["unattributed"] += 1
            if owners and row["task"] not in owners:
                result["flagged"].append({"task": row["task"], "kind": row["kind"],
                                          "problem": "evidence belongs to another task: " + sha})
                break
    result["status"] = "pass" if not result["flagged"] else "attention"
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stores", nargs="+", help="Store roots (directories holding state.sqlite3)")
    parser.add_argument("--json", action="store_true", help="Emit one JSON document per store")
    args = parser.parse_args(argv)
    results = [audit(root) for root in args.stores]
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        for result in results:
            print(f"{result['store']}: {result['reports']} report(s), "
                  f"{len(result['tasks'])} task(s), {len(result['flagged'])} flagged, "
                  f"{result['unattributed']} unattributed evidence")
            for item in result["flagged"]:
                print("  - " + item["task"] + "/" + item["kind"] + ": " + item["problem"])
    return 0 if all(result["status"] == "pass" for result in results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
