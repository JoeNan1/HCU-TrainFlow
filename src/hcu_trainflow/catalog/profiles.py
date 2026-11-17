"""Sub-workflow profiles and deterministic routing.

A profile declares only *which* catalog modules a scenario needs and which
stages it keeps.  Reports, gates and reading material are derived from those
modules, so a profile can never become a second copy of the gate list.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from .contracts import ModuleContractError, Profile
from . import registry
from .gates import derive

# Every module id, in catalog order.
_ALL = tuple(module.id for module in registry.modules())

PROFILES: dict[str, Profile] = {}


def _profile(name: str, **kwargs: Any) -> None:
    PROFILES[name] = Profile(name, **kwargs)


_FULL_STAGES = ("prepared", "environment_checked", "baseline_validated", "profiling",
                "optimizing", "scale_ready", "training")

_COMMON = ("environment-readiness", "environment-collect", "source-handoff",
           "quality-accept", "training-observation")

_profile(
    "llm-megatron",
    applies_to={"engine": ("megatron",), "model_family": ("llm",)},
    subworkflows=(*_COMMON, "baseline-megatron", "baseline-qualification",
                  "adaptation", "adaptation-proxy", "hipprof-summary",
                  "trace-attribution", "optimization-netgain", "optimization-benchmark"),
    stages=_FULL_STAGES,
    defaults={"budget": {"max_operations": 240, "max_seconds": 259200}},
    notes="完整流程：环境、执行、短基线与质量、性能分析、优化与扩容全部保留；日志按 Megatron 格式解析",
)

_profile(
    "torch-native-llm",
    applies_to={"engine": ("torch",), "model_family": ("llm",)},
    subworkflows=(*_COMMON, "baseline-torch", "baseline-qualification",
                  "adaptation", "adaptation-proxy", "hipprof-summary",
                  "trace-attribution", "optimization-netgain", "optimization-benchmark"),
    stages=_FULL_STAGES,
    defaults={"budget": {"max_operations": 200, "max_seconds": 172800}},
    notes="torchtitan/nanotron 等纯 torch 大模型：只换日志摘要子工作流，其余与 llm-megatron 相同，门禁一项不减",
)

_profile(
    "torch-native-vision",
    applies_to={"engine": ("torch",), "model_family": ("vision", "video")},
    subworkflows=(*_COMMON, "baseline-torch", "adaptation",
                  "trace-attribution", "optimization-netgain"),
    stages=_FULL_STAGES,
    defaults={"budget": {"max_operations": 120, "max_seconds": 86400}},
    notes="单机 CNN/视频模型：不装代理配置、短基线资格、隔离基准与 hipprof 摘要，门禁一项不减",
)

_profile(
    "analysis-only",
    applies_to={"mode": ("analyze", "diagnose")},
    modules=("environment.probe", "execution.command", "execution.stdout-json",
             "artifact.collect", "source.transfer",
             "profiling.trace", "profiling.analyze"),
    stages=("profiling",),
    defaults={"budget": {"max_operations": 40, "max_seconds": 21600}},
    notes="只读分析：不给任何 optimization.* 与日志摘要，不推进阶段，只产 analysis 门禁；与引擎无关",
)


def profiles() -> dict[str, Profile]:
    return dict(PROFILES)


def profile(name: str) -> Profile:
    try:
        return PROFILES[name]
    except KeyError:
        raise ModuleContractError("Unknown profile: " + name) from None


def _matches(profile: Profile, context: Mapping[str, Any]) -> bool:
    for key, allowed in profile.applies_to.items():
        value = context.get(key)
        if value is None:
            return False
        values = (value,) if isinstance(value, str) else tuple(value)
        if not set(values) & set(allowed):
            return False
    return True


def _conflicts(profile: Profile, context: Mapping[str, Any]) -> list[str]:
    reasons = []
    for key, allowed in profile.applies_to.items():
        value = context.get(key)
        if value is None:
            continue
        values = (value,) if isinstance(value, str) else tuple(value)
        if not set(values) & set(allowed):
            reasons.append(key + ": context=" + ",".join(map(str, values))
                           + " profile=" + ",".join(allowed))
    return reasons


def resolve(context: Mapping[str, Any], requested: str | None = None) -> dict[str, Any]:
    """Deterministically map a task context to candidate profiles.

    Routing never advances a stage: it answers "which module set applies" and,
    when more than one does, leaves the choice (and its justification) to the
    Agent instead of guessing.
    """

    if not isinstance(context, Mapping):
        raise ValueError("Profile context must be an object")
    if requested is not None:
        selected = profile(requested)
        conflicts = _conflicts(selected, context)
        if conflicts:
            raise ModuleContractError("Requested profile conflicts with context: "
                                      + "; ".join(conflicts))
        return {"status": "pass", "profile": selected.id, "candidates": [selected.id],
                "selection_required": False, "reason": "explicit",
                "context": dict(context), "stages": list(selected.stages)}
    candidates = [p.id for p in PROFILES.values() if _matches(p, context)]
    if len(candidates) == 1:
        return {"status": "pass", "profile": candidates[0], "candidates": candidates,
                "selection_required": False, "reason": "unique-match",
                "context": dict(context), "stages": list(PROFILES[candidates[0]].stages)}
    if candidates:
        return {"status": "select", "profile": None, "candidates": candidates,
                "selection_required": True, "reason": "multiple-match",
                "context": dict(context),
                "next": "Choose one candidate, record the reason, then pass it as requested profile"}
    return {"status": "halt", "halt_reason": "profile-unknown", "profile": None,
            "candidates": [], "selection_required": False, "reason": "no-match",
            "context": dict(context),
            "next": "Declare engine/model_family/mode in the task context, or add a reviewed profile"}


def route_surface(modules: Iterable[str]) -> dict[str, Any]:
    """Reading surface of a module subset, and its share of the full surface."""

    def pages(ids: Iterable[str]) -> list[str]:
        return sorted({registry.module(module_id).route for module_id in ids})

    subset = pages(modules)
    full = pages(_ALL)
    return {"routes": subset, "count": len(subset), "full_count": len(full),
            "share": round(len(subset) / len(full), 3) if full else 0.0}


def derived_gates(selected: Profile | str) -> dict[str, list[str]]:
    chosen = profile(selected) if isinstance(selected, str) else selected
    return derive([registry.module(module_id) for module_id in chosen.module_ids()], chosen.stages)
