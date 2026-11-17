"""Replay a store's recorded decisions against the current Flow machine.

The guardrail work added fields to ``flow-next`` (invariants) and new code on
the report path. This script answers the question that matters for an existing
workspace: does the machine still accept the history it already recorded, and
does it derive the same requirements for it?

For every task in a copy of the store it checks:

* every recorded ``state-changed`` transition is still legal (the stage graph
  and the reset rules are unchanged);
* ``required_reports`` equals ``flow.GATES`` for a task that declares no
  profile (the migration must not have changed an existing task's gates);
* ``brief_token`` is stable across two reads and ``flow.brief`` works on the
  real shape (rounds, questions, pipeline runs);
* ``flow-align`` reports no drift.

The store is copied first: ``next_step``/``align`` may record events, and the
original history must stay byte-identical.

    python scripts/replay_flow_decisions.py STORE [STORE ...]
    python scripts/replay_flow_decisions.py --json STORE
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hcu_trainflow import flow  # noqa: E402
from hcu_trainflow.core import GATES, PIPELINE, FlowError, Store  # noqa: E402
from hcu_trainflow.flow import get_flow  # noqa: E402

RESET = {"paused", "blocked", "failed", "cancelled"}


def transition_ok(source, destination):
    """Mirror Store.transition's structural rules without touching the store."""

    if destination in RESET or destination == "prepared":
        return True
    if source not in PIPELINE or destination not in PIPELINE:
        return False
    return PIPELINE.index(destination) == PIPELINE.index(source) + 1


def replay(root):
    with tempfile.TemporaryDirectory(prefix="replay-") as tmp:
        copy = Path(tmp) / "store"
        shutil.copytree(root, copy)
        store = Store(copy)
        report = {"store": str(root), "tasks": [], "problems": []}
        with store.db() as db:
            tasks = [row["id"] for row in db.execute("SELECT id FROM tasks ORDER BY id")]
        for tid in tasks:
            task = store.task(tid)
            with store.db() as db:
                changes = [json.loads(row["payload"]) for row in db.execute(
                    "SELECT payload FROM events WHERE task=? AND kind='state-changed' ORDER BY seq",
                    (tid,))]
            item = {"task": tid, "state": task["state"], "mode": task["spec"]["mode"],
                    "profile": (task["spec"].get("profile") or {}).get("id"),
                    "transitions": len(changes), "transitions_ok": 0,
                    "gates_match": None, "brief_stable": None, "align": None, "action": None}
            source = "draft"
            for change in changes:
                if transition_ok(source, change["to"]):
                    item["transitions_ok"] += 1
                else:
                    report["problems"].append({"task": tid, "problem": "illegal transition "
                                               + source + "->" + change["to"]})
                source = change["to"]
            with store.db() as db:
                started = get_flow(db, tid) is not None
            item["flow"] = started
            if not started:
                # No collaborative flow attached: there is no decision to replay.
                report["tasks"].append(item)
                continue
            destination = flow.target(task)
            if item["profile"] is None and item["mode"] == "full":
                expected = GATES.get(destination, [])
                actual = flow.required_reports(task, destination)
                item["gates_match"] = sorted(actual) == sorted(expected)
                if not item["gates_match"]:
                    report["problems"].append({"task": tid, "problem": "gates changed",
                                               "expected": sorted(expected), "actual": sorted(actual)})
            try:
                first = flow.brief_token(store, tid)
                flow.brief(store, tid)
                item["brief_stable"] = flow.brief_token(store, tid) == first
                if not item["brief_stable"]:
                    report["problems"].append({"task": tid, "problem": "brief hash moved on a read"})
            except FlowError as exc:
                report["problems"].append({"task": tid, "problem": "brief failed: " + str(exc)})
            try:
                aligned = flow.align(store, tid)
                item["align"] = aligned["status"]
                if aligned["status"] != "aligned":
                    report["problems"].append({"task": tid, "problem": "drift",
                                               "deltas": aligned["deltas"]})
            except FlowError as exc:
                report["problems"].append({"task": tid, "problem": "align failed: " + str(exc)})
            try:
                item["action"] = flow.next_step(store, tid)["action"]
            except FlowError as exc:
                report["problems"].append({"task": tid, "problem": "next_step failed: " + str(exc)})
            report["tasks"].append(item)
        report["status"] = "pass" if not report["problems"] else "attention"
        return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stores", nargs="+", help="Store roots holding state.sqlite3")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    results = [replay(root) for root in args.stores]
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        for result in results:
            print(result["store"])
            for item in result["tasks"]:
                print(f"  {item['task']}: state={item['state']} transitions={item['transitions_ok']}/"
                      f"{item['transitions']} gates_match={item['gates_match']} "
                      f"brief_stable={item['brief_stable']} align={item['align']} action={item['action']}")
            for problem in result["problems"]:
                print("  ! " + problem["task"] + ": " + problem["problem"])
    return 0 if all(result["status"] == "pass" for result in results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
