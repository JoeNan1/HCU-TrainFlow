"""Default gated Pipeline slices for the legacy full training workflow.

The full workflow is intentionally represented as one stage plan at a time.
Review, report gates and state transitions stay in ``flow.py``; exposing all
stages as one eager DAG would allow a caller to skip those decisions.
"""
from __future__ import annotations

from .pipeline import PipelinePlan, PipelineStep


FULL_STAGE_STEPS: dict[str, tuple[PipelineStep, ...]] = {
    "prepared": (
        PipelineStep("environment", "environment.check", "check",
                     config={"flow_state": "prepared", "flow_target": "environment_checked"}),
    ),
    "environment_checked": (
        PipelineStep("adaptation", "adaptation.proxy", "check",
                     config={"flow_state": "environment_checked", "flow_target": "baseline_validated"}),
    ),
    "baseline_validated": (
        PipelineStep("profile-plan", "profiling.plan", "plan",
                     config={"flow_state": "baseline_validated", "flow_target": "profiling"}),
        PipelineStep("profile", "profiling.analyze", "analyze", ("profile-plan",),
                     config={"flow_state": "baseline_validated", "flow_target": "profiling"}),
    ),
    "profiling": (
        PipelineStep("optimization", "optimization.iteration", "assess",
                     config={"flow_state": "profiling", "flow_target": "optimizing"}),
    ),
    "optimizing": (
        PipelineStep("scale-admission", "scale.admission", "check",
                     config={"flow_state": "optimizing", "flow_target": "scale_ready"}),
    ),
    "scale_ready": (
        PipelineStep("observation", "observation.collect", "collect",
                     config={"flow_state": "scale_ready", "flow_target": "training"}),
    ),
    "training": (
        PipelineStep("observation", "observation.collect", "collect",
                     config={"flow_state": "training", "flow_target": "completed"}),
    ),
}


def full_pipeline_for_state(state: str) -> PipelinePlan:
    """Build the current gated stage plan for a full-mode task."""

    try:
        steps = FULL_STAGE_STEPS[state]
    except KeyError:
        raise ValueError("No executable full Pipeline stage for state: " + str(state)) from None
    return PipelinePlan(name="full:" + state, steps=steps)

