"""Module catalog, sub-workflow profiles and derived stage gates.

Importing this package is cheap: it holds catalog data and pure helpers, and
never touches the Store, the Flow state machine or an execution backend.  The
Flow remains the only state machine; a profile only selects modules.
"""

from .contracts import (
    AGENT_AUTHORED,
    EVIDENCE_REPORTS,
    FLOW_STAGES,
    GATE_REPORTS,
    REPORT_KINDS,
    Module,
    ModuleContractError,
    Profile,
    Subworkflow,
)
from .gates import compare_to_flow, derive, evidence_reports, flow_gates, missing_producers, stage_scope
from .plan import build as build_plan, interface, preset_plan, select, subworkflow_plan
from .profiles import (PROFILES, derived_gates, profile, profiles, resolve as resolve_profile,
                       route_surface, validate_scope)
from .registry import (ALIASES, MODULES, SUBWORKFLOW_ALIASES, SUBWORKFLOWS, aliases, module,
                       modules, preset, presets,
                       resolve, subworkflow, subworkflows, validate_catalog, validate_subworkflow)

__all__ = [
    "AGENT_AUTHORED", "ALIASES", "EVIDENCE_REPORTS", "FLOW_STAGES", "GATE_REPORTS",
    "MODULES", "Module", "ModuleContractError", "PROFILES", "Profile", "REPORT_KINDS",
    "SUBWORKFLOW_ALIASES", "SUBWORKFLOWS", "Subworkflow", "aliases", "build_plan", "compare_to_flow",
    "derived_gates", "derive", "evidence_reports", "flow_gates", "interface",
    "missing_producers", "module", "modules", "preset", "preset_plan", "presets",
    "profile", "profiles", "resolve", "resolve_profile", "route_surface", "select",
    "stage_scope", "subworkflow", "subworkflow_plan", "subworkflows",
    "validate_catalog", "validate_scope", "validate_subworkflow",
]
