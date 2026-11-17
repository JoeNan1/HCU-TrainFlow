"""The report path must not degrade with history size.

The ownership check looks an object up by task; if the lookup ever falls back
to scanning the event log, a long-running store becomes unusable. Comparing a
small store with a ten-times larger one catches that without depending on the
speed of the machine.
"""
import json
import time

from hcu_trainflow.core import Store

CONTEXT = {"source": "perf", "engine": "megatron", "model_family": "llm"}


def _store(tmp_path, name, events):
    store = Store(tmp_path / name)
    store.create({"schema_version": 1, "task_id": "t", "mode": "full", "objective": "perf",
                  "context": dict(CONTEXT), "permissions": ["execute"]})
    with store.db() as db:
        db.execute("BEGIN IMMEDIATE")
        for index in range(events):
            store.event(db, "t", "filler", {"index": index})
    return store


def _mean_report_ms(store, count=30):
    evidence = store.put(json.dumps({"throughput": 1234.0}).encode())
    context = store.task("t")["context"]
    start = time.perf_counter()
    for index in range(count):
        store.report("t", "environment", {
            "context": context, "status": "pass", "executed": 1, "evidence": [evidence],
            "claims": [{"id": "c" + str(index), "statement": "Throughput was 1234",
                        "stage": "environment_checked", "value": 1234.0,
                        "source": {"artifact": evidence, "path": ["throughput"]}}]})
    return (time.perf_counter() - start) * 1000 / count


def test_report_cost_does_not_grow_with_the_event_log(tmp_path):
    small = _mean_report_ms(_store(tmp_path, "small", 500))
    large = _mean_report_ms(_store(tmp_path, "large", 5000))
    # A full scan would make this ten times worse; the indexes keep it flat.
    assert large < small * 3, (small, large)
