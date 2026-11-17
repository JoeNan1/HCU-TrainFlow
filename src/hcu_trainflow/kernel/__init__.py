"""Stable workflow kernel contracts.

The kernel deliberately contains no HCU, profiler, Wiki, or transport
implementation.  Existing ``core`` APIs remain the compatibility store while
new capabilities use these small contracts to communicate.
"""

from .contracts import (
    CAPABILITY_STATUSES,
    Capability,
    CapabilityContext,
    CapabilityRequest,
    CapabilityResult,
)
from .pipeline import PipelinePlan, PipelineResult, PipelineRunner, PipelineStep
from .flow_bridge import FlowPipelineBridge, pipeline_next
from .full_pipeline import FULL_STAGE_STEPS, full_pipeline_for_state

__all__ = [
    "CAPABILITY_STATUSES",
    "Capability",
    "CapabilityContext",
    "CapabilityRequest",
    "CapabilityResult",
    "PipelinePlan",
    "PipelineResult",
    "PipelineRunner",
    "PipelineStep",
    "FlowPipelineBridge",
    "pipeline_next",
    "FULL_STAGE_STEPS",
    "full_pipeline_for_state",
]
