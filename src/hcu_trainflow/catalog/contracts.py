"""Closed contracts for the module catalog.

A module is one deterministic, independently invocable unit of work with at
most one evidence product.  Gate reports are *derived* from modules and their
stages; they are never declared separately, so a sub-workflow cannot keep its
own copy of the report list and drift away from the Flow gates.

This package holds data only.  It does not import the Store, the Flow state
machine, or any HCU/tooling integration, so ``module-catalog`` stays cheap and
usable without a workspace.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping

# Closed vocabularies.  A new value needs a review, not a code edit only.
MODULE_ROLES = frozenset({"check", "collect", "execute", "analyze", "optimize",
                          "judge", "deliver", "infra"})
MODULE_ENGINES = frozenset({"any", "megatron", "torch"})
MODULE_FAMILIES = frozenset({"any", "llm", "vision", "video"})
MODULE_NEEDS = frozenset({"hardware", "lease", "task-bound"})
TAG_KEYS = frozenset({"engine", "model_family", "needs"})

# The seven Flow stage gates.  Only these kinds are ever demanded by a stage.
GATE_REPORTS = frozenset({"environment", "baseline", "analysis", "stage-quality",
                          "performance", "scale", "completion"})
# Evidence products that inform a decision but never open a stage gate.
EVIDENCE_REPORTS = frozenset({"baseline-qualification", "profile-summary",
                              "optimization-change", "diagnosis", "operations",
                              "adaptation-parity", "adaptation-diff",
                              "adaptation-numerics"})
REPORT_KINDS = GATE_REPORTS | EVIDENCE_REPORTS

# Flow stage vocabulary.  ``flow.NEXT`` owns the transitions; the catalog only
# names the stages, and a regression test keeps the two lists identical.
FLOW_STAGES = ("prepared", "environment_checked", "baseline_validated", "profiling",
               "optimizing", "scale_ready", "training", "completed")

# Reports that no module can produce: they are conclusions written by the
# candidate/review flow, so gate derivation must add them explicitly.
AGENT_AUTHORED = {
    "optimizing": ("stage-quality",),
    "scale_ready": ("stage-quality", "scale"),
    "training": ("completion",),
}

_ID = re.compile(r"^[a-z][a-z0-9]*(\.[a-z0-9]+(-[a-z0-9]+)*)+$")
_SLUG = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")


class ModuleContractError(ValueError):
    """A module/alias/preset/profile violates the closed catalog contract."""


@dataclass(frozen=True)
class Module:
    """One catalog entry.

    ``stage`` is the stage scope of the module.  For a module that produces a
    gate report it is exactly the set of *source* stages whose gate demands
    that report (a report demanded at two gates lists both).  For a module
    without a report it is the stages in which the module runs.
    """

    id: str
    summary: str
    actions: tuple[str, ...]
    requires: Mapping[str, str] = field(default_factory=dict)
    provides: Mapping[str, str] = field(default_factory=dict)
    report: str | None = None
    stage: tuple[str, ...] = ()
    role: str = "collect"
    tags: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    volatile: bool = False
    route: str = ""
    implementation: tuple[str, str] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not _ID.match(self.id):
            raise ModuleContractError("Module id must be dotted lowercase: " + repr(self.id))
        if not isinstance(self.summary, str) or not self.summary.strip():
            raise ModuleContractError("Module requires a summary: " + self.id)
        if self.role not in MODULE_ROLES:
            raise ModuleContractError("Unknown module role for " + self.id + ": " + str(self.role))
        if not isinstance(self.actions, tuple) or not self.actions or any(
                not isinstance(x, str) or not x for x in self.actions):
            raise ModuleContractError("Module requires nonempty actions: " + self.id)
        if len(set(self.actions)) != len(self.actions):
            raise ModuleContractError("Module actions must be unique: " + self.id)
        for key, value in self.requires.items():
            if not isinstance(key, str) or not key or not isinstance(value, str) or not value:
                raise ModuleContractError("Module requires must map input names to types: " + self.id)
        for key, value in self.provides.items():
            if not isinstance(key, str) or not key or not isinstance(value, str) or not value:
                raise ModuleContractError("Module provides must map output names to types: " + self.id)
        if self.report is not None and self.report not in REPORT_KINDS:
            raise ModuleContractError("Unknown report kind for " + self.id + ": " + str(self.report))
        if self.report is not None and not self.stage:
            raise ModuleContractError("A reporting module must declare its stages: " + self.id)
        unknown_stages = set(self.stage) - set(FLOW_STAGES)
        if unknown_stages:
            raise ModuleContractError("Unknown stages for " + self.id + ": " + ", ".join(sorted(unknown_stages)))
        unknown = set(self.tags) - TAG_KEYS
        if unknown:
            raise ModuleContractError("Unknown tag keys for " + self.id + ": " + ", ".join(sorted(unknown)))
        for key, values in self.tags.items():
            if not isinstance(values, tuple):
                raise ModuleContractError("Module tags must be tuples: " + self.id + "." + key)
            if not values and key != "needs":
                raise ModuleContractError("Module tags must be nonempty tuples: " + self.id + "." + key)
            allowed = {"engine": MODULE_ENGINES, "model_family": MODULE_FAMILIES,
                       "needs": MODULE_NEEDS}[key]
            bad = set(values) - allowed
            if bad:
                raise ModuleContractError("Unknown " + key + " tag for " + self.id + ": " + ", ".join(sorted(bad)))
        if type(self.volatile) is not bool:
            raise ModuleContractError("Module volatile must be boolean: " + self.id)
        if not isinstance(self.route, str) or not self.route.startswith("docs/"):
            raise ModuleContractError("Module route must be a docs page: " + self.id)
        if self.implementation is not None:
            capability, action = self.implementation
            if not isinstance(capability, str) or not capability or not isinstance(action, str) or not action:
                raise ModuleContractError("Module implementation must be capability and action: " + self.id)
            if action not in self.actions:
                raise ModuleContractError("Module implementation action must be declared: " + self.id)

    @property
    def executable(self) -> bool:
        return self.implementation is not None

    def accepts(self, key: str, kind: str) -> bool:
        """Whether a provided ``kind`` satisfies the declared requirement."""

        declared = self.requires.get(key)
        return declared is not None and kind in declared.split("|")

    def needs(self) -> tuple[str, ...]:
        return tuple(self.tags.get("needs", ()))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "summary": self.summary,
            "actions": list(self.actions),
            "requires": dict(self.requires),
            "provides": dict(self.provides),
            "report": self.report,
            "stage": list(self.stage),
            "role": self.role,
            "tags": {key: list(values) for key, values in self.tags.items()},
            "volatile": self.volatile,
            "route": self.route,
            "executable": self.executable,
            "implementation": None if self.implementation is None else {
                "capability": self.implementation[0], "action": self.implementation[1]},
        }


@dataclass(frozen=True)
class Subworkflow:
    """A functional composition of modules that does one job end to end.

    It is **not** a process: no stages, no gates, no routing.  ``composition``
    subworkflows are wired automatically from module contracts; ``template``
    subworkflows carry a fixed step list because the site shape matters (a live
    baseline run has a specific command/binding layout).
    """

    id: str
    summary: str
    modules: tuple[str, ...]
    kind: str = "composition"
    template: Mapping[str, Any] | None = None
    bundled: tuple[str, ...] = ()
    notes: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not _SLUG.match(self.id):
            raise ModuleContractError("Subworkflow id must be a hyphenated slug: " + repr(self.id))
        if not isinstance(self.summary, str) or not self.summary.strip():
            raise ModuleContractError("Subworkflow requires a summary: " + self.id)
        if not self.modules or len(set(self.modules)) != len(self.modules):
            raise ModuleContractError("Subworkflow modules must be nonempty and unique: " + self.id)
        if self.kind not in {"composition", "template"}:
            raise ModuleContractError("Subworkflow kind must be composition or template: " + self.id)
        if (self.kind == "template") != (self.template is not None):
            raise ModuleContractError("Only template subworkflows carry a step template: " + self.id)
        if set(self.bundled) - set(self.modules):
            raise ModuleContractError("Bundled modules must belong to the subworkflow: " + self.id)
        if self.template is not None:
            steps = self.template.get("steps")
            if not isinstance(steps, list) or not steps:
                raise ModuleContractError("Template subworkflow requires steps: " + self.id)
            for step in steps:
                if not isinstance(step, Mapping) or step.get("module") not in self.modules:
                    raise ModuleContractError(
                        "Template step uses a module outside the subworkflow: " + self.id)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "summary": self.summary, "modules": list(self.modules),
                "kind": self.kind, "bundled": list(self.bundled),
                "declarative": self.template is not None, "notes": self.notes}


@dataclass(frozen=True)
class Profile:
    """A process profile: modules (or functional subworkflows) + stage scope."""

    id: str
    applies_to: Mapping[str, tuple[str, ...]]
    stages: tuple[str, ...]
    modules: tuple[str, ...] = ()
    subworkflows: tuple[str, ...] = ()
    defaults: Mapping[str, Any] = field(default_factory=dict)
    notes: str = ""

    def module_ids(self) -> tuple[str, ...]:
        """Resolved module list: explicit modules, or the subworkflow union."""

        if self.modules:
            return tuple(self.modules)
        from . import registry
        seen: dict[str, None] = {}
        for name in self.subworkflows:
            for module_id in registry.subworkflow(name).modules:
                seen.setdefault(module_id, None)
        return tuple(seen)

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not _SLUG.match(self.id):
            raise ModuleContractError("Profile id must be a hyphenated slug: " + repr(self.id))
        unknown = set(self.applies_to) - {"engine", "model_family", "mode"}
        if unknown:
            raise ModuleContractError("Profile applies_to has unknown keys: " + ", ".join(sorted(unknown)))
        for key, values in self.applies_to.items():
            if not isinstance(values, tuple) or not values:
                raise ModuleContractError("Profile applies_to values must be nonempty tuples: " + self.id)
            allowed = {"engine": MODULE_ENGINES, "model_family": MODULE_FAMILIES, "mode": None}[key]
            if allowed is not None and set(values) - allowed:
                raise ModuleContractError("Profile applies_to has unknown values: " + self.id + "." + key)
        if bool(self.modules) == bool(self.subworkflows):
            raise ModuleContractError(
                "Profile declares modules or subworkflows, not both and not neither: " + self.id)
        if len(set(self.modules)) != len(self.modules):
            raise ModuleContractError("Profile modules must be unique: " + self.id)
        if len(set(self.subworkflows)) != len(self.subworkflows):
            raise ModuleContractError("Profile subworkflows must be unique: " + self.id)
        if not self.stages or len(set(self.stages)) != len(self.stages):
            raise ModuleContractError("Profile stages must be nonempty and unique: " + self.id)
        unknown_stages = set(self.stages) - set(FLOW_STAGES)
        if unknown_stages:
            raise ModuleContractError("Unknown profile stages for " + self.id + ": " + ", ".join(sorted(unknown_stages)))
        if not isinstance(self.defaults, Mapping):
            raise ModuleContractError("Profile defaults must be an object: " + self.id)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Profile":
        """Load a profile, refusing the fields that must stay derived."""

        if not isinstance(value, Mapping):
            raise ModuleContractError("Profile must be an object")
        derived = {"reports", "gates", "reading"} & set(value)
        if derived:
            raise ModuleContractError(
                "Profile must not declare " + ", ".join(sorted(derived))
                + ": reports and reading material are derived from its modules")
        allowed = {"id", "applies_to", "modules", "subworkflows", "stages", "defaults", "notes"}
        unknown = set(value) - allowed
        if unknown:
            raise ModuleContractError("Unknown profile fields: " + ", ".join(sorted(unknown)))
        applies_to, stages = value.get("applies_to"), value.get("stages")
        modules, subworkflows = value.get("modules") or [], value.get("subworkflows") or []
        if (not isinstance(applies_to, Mapping) or not isinstance(stages, list)
                or not isinstance(modules, list) or not isinstance(subworkflows, list)):
            raise ModuleContractError("Profile requires applies_to, stages and modules or subworkflows")
        return cls(
            id=value.get("id"),
            applies_to={key: tuple(values) if isinstance(values, (list, tuple)) else (values,)
                        for key, values in applies_to.items()},
            stages=tuple(stages), modules=tuple(modules), subworkflows=tuple(subworkflows),
            defaults=dict(value.get("defaults") or {}), notes=value.get("notes", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id,
                "applies_to": {key: list(values) for key, values in self.applies_to.items()},
                "modules": list(self.modules), "subworkflows": list(self.subworkflows),
                "stages": list(self.stages),
                "defaults": dict(self.defaults), "notes": self.notes}
