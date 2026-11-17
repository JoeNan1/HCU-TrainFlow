"""Measure what the claim and ownership checks cost on the report write path.

    python scripts/bench_report_path.py [--reports 200] [--events 20000]

Reports the p50/p95 of ``Store.report`` with evidence, claims and a store that
already holds ``--events`` events, which is where a JSON path query would hurt
if it were not indexed.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hcu_trainflow.core import Store  # noqa: E402

PROFILE = {"id": "llm-megatron", "reason": "benchmark"}


def bench(reports, events):
    with tempfile.TemporaryDirectory(prefix="bench-") as tmp:
        store = Store(Path(tmp) / "store")
        store.create({"schema_version": 1, "task_id": "t", "mode": "full", "objective": "bench",
                      "context": {"source": "bench", "engine": "megatron", "model_family": "llm"},
                      "permissions": ["execute"], "profile": dict(PROFILE)})
        # Fill the event log first: the ownership query must not degrade with it.
        from hcu_trainflow import flow  # noqa: E402
        flow.start(store, "t", {"acceptance": {"result": "Deliver evidence"}})
        with store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            for index in range(events):
                store.event(db, "t", "filler", {"index": index, "artifact": "%064x" % index})
        evidence = store.put(json.dumps({"throughput": 1234.0}).encode())
        context = store.task("t")["context"]
        timings = []
        for index in range(reports):
            body = {"context": context, "status": "pass", "executed": 1,
                    "evidence": [evidence],
                    "claims": [{"id": "c" + str(index), "statement": "Throughput was 1234 tokens/s",
                                "stage": "environment_checked", "value": 1234.0,
                                "source": {"artifact": evidence, "path": ["throughput"]}}]}
            start = time.perf_counter()
            store.report("t", "environment", body)
            timings.append((time.perf_counter() - start) * 1000)
        timings.sort()
        pick = lambda q: timings[min(len(timings) - 1, int(len(timings) * q))]  # noqa: E731
        return {"reports": reports, "events": events, "p50_ms": round(pick(0.5), 2),
                "p95_ms": round(pick(0.95), 2), "max_ms": round(timings[-1], 2),
                "mean_ms": round(statistics.fmean(timings), 2)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports", type=int, default=200)
    parser.add_argument("--events", type=int, default=20000)
    args = parser.parse_args(argv)
    result = bench(args.reports, args.events)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
