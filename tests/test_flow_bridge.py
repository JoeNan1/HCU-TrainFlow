import json

from hcu_trainflow.core import Store
from hcu_trainflow.kernel import full_pipeline_for_state, pipeline_next
from hcu_trainflow.modular_cli import pipeline_default
from hcu_trainflow import flow


def _task(store, task_id="bridge-task"):
    return store.create({
        "schema_version": 1,
        "task_id": task_id,
        "objective": "bridge smoke",
        "context": {"model": "toy", "revision": "r1"},
        "mode": "full",
        "budget": {"max_operations": 4, "max_seconds": 60},
    })


def test_pipeline_next_projects_flow_without_advancing(tmp_path):
    store = Store(tmp_path)
    _task(store)
    flow.start(store, "bridge-task", {"acceptance": {"result": "pass"}})

    before = store.task("bridge-task")
    projected = pipeline_next(store, "bridge-task")
    after = store.task("bridge-task")

    assert projected["task"] == "bridge-task"
    assert projected["action"] == "work"
    assert projected["skill"]
    assert projected["current"]["skill"] == projected["skill"]
    assert projected["gate"]["status"] == "pending"
    assert projected["flow_decision"]["action"] == "work"
    assert after["state"] == before["state"]
    assert after["revision"] == before["revision"]
    json.dumps(projected, ensure_ascii=False)


def test_pipeline_next_preserves_flow_blockers(tmp_path):
    store = Store(tmp_path)
    _task(store, "blocked-task")
    flow.start(store, "blocked-task", {"acceptance": {"result": "pass"}})
    flow.question(store, "blocked-task", {
        "id": "need-human",
        "title": "Need a decision",
        "body": "Choose the baseline.",
        "blocking": True,
    })

    projected = pipeline_next(store, "blocked-task")

    assert projected["action"] == "human"
    assert projected["gate"]["status"] == "blocked"
    assert "blocking-human-question" in projected["gate"]["blocked_by"]


def test_default_full_pipeline_is_one_gated_stage(tmp_path):
    store = Store(tmp_path)
    _task(store, "default-task")
    flow.start(store, "default-task", {"acceptance": {"result": "pass"}})

    projected = pipeline_default(store, "default-task")

    assert projected["status"] == "pass"
    assert projected["pipeline"]["name"] == "full:prepared"
    assert projected["pipeline"]["steps"][0]["capability"] == "environment.check"
    assert full_pipeline_for_state("prepared").to_dict() == projected["pipeline"]

