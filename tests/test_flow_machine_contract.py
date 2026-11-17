"""The stage graph and gates are a published contract; lock them.

History replay (`scripts/replay_flow_decisions.py`) can only prove that the
machine still accepts a real store. This test proves the stronger, cheaper
part on every commit: the graph, the gate list and the derived gates of the
full profile are exactly the ones already shipped.
"""
from hcu_trainflow import catalog, flow
from hcu_trainflow.core import GATES, PIPELINE
from hcu_trainflow.catalog import contracts

NEXT_GOLDEN = {
    "prepared": "environment_checked",
    "environment_checked": "baseline_validated",
    "baseline_validated": "profiling",
    "profiling": "optimizing",
    "optimizing": "scale_ready",
    "scale_ready": "training",
    "training": "completed",
}

GATES_GOLDEN = {
    "environment_checked": ["environment"],
    "baseline_validated": ["baseline"],
    "profiling": ["baseline"],
    "optimizing": ["analysis"],
    "scale_ready": ["stage-quality", "performance"],
    "training": ["environment", "stage-quality", "scale"],
    "completed": ["completion"],
}

PIPELINE_GOLDEN = ["draft", "prepared", "environment_checked", "baseline_validated",
                   "profiling", "optimizing", "scale_ready", "training", "completed"]


def test_the_stage_graph_is_unchanged():
    assert flow.NEXT == NEXT_GOLDEN
    assert PIPELINE == PIPELINE_GOLDEN
    # Every step of the graph is adjacent in the linear order the store enforces.
    for source, destination in NEXT_GOLDEN.items():
        assert PIPELINE.index(destination) == PIPELINE.index(source) + 1


def test_the_gate_list_is_unchanged():
    assert {stage: list(kinds) for stage, kinds in GATES.items()} == GATES_GOLDEN


def test_the_full_profile_still_derives_exactly_the_shipped_gates():
    derived = catalog.derived_gates("llm-megatron")
    assert {stage: sorted(kinds) for stage, kinds in derived.items()} == \
        {stage: sorted(kinds) for stage, kinds in GATES_GOLDEN.items()}


def test_agent_authored_gates_are_only_the_three_named_ones():
    assert contracts.AGENT_AUTHORED == {"optimizing": ("stage-quality",),
                                        "scale_ready": ("stage-quality", "scale"),
                                        "training": ("completion",)}
