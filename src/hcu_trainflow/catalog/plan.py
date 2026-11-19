"""Turn a module set into a validated, auto-wired Pipeline plan.

Wiring rule: an input is bound automatically only when exactly one other module
in the set provides the *same key with the same type*.  Anything else (no
provider, several providers) is reported, never guessed, and the caller must
either supply the value as a run input, write an explicit binding, or use a
curated preset.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from ..kernel import PipelinePlan
from .contracts import Module, ModuleContractError
from . import registry
from .gates import derive, evidence_reports, missing_producers, stage_scope


def _module_list(names: Iterable[str]) -> list[Module]:
    resolved = []
    for name in names:
        module = registry.resolve(name)
        if module.id in {m.id for m in resolved}:
            raise ModuleContractError("Module appears twice: " + module.id)
        resolved.append(module)
    reports = [module.report for module in resolved if module.report]
    duplicates = sorted({kind for kind in reports if reports.count(kind) > 1})
    if duplicates:
        raise ModuleContractError("Module set has conflicting report producers: "
                                  + ", ".join(duplicates))
    return resolved


def select(*, profile: str | None = None, subworkflow: str | None = None,
           preset: str | None = None, modules: Sequence[str] | None = None,
           stages: Sequence[str] | None = None) -> dict[str, Any]:
    """Resolve a document's module source into modules plus a stage scope.

    ``preset`` is the legacy spelling of ``subworkflow``; both name the same
    functional compositions.
    """

    subworkflow = subworkflow or preset
    chosen = [value for value in (profile, subworkflow, modules) if value is not None]
    if len(chosen) != 1:
        raise ModuleContractError("Declare exactly one of profile, subworkflow or modules")
    if stages is not None and not stages:
        # An empty scope used to collapse to ``None`` and silently disable the
        # stage-evidence check; ask for what was meant instead.
        raise ModuleContractError("Stage scope must be nonempty")
    if profile is not None:
        from .profiles import profile as get_profile
        entry = get_profile(profile)
        if stages is not None and not set(stages) <= set(entry.stages):
            # A caller may narrow a profile's scope, never widen it.
            raise ModuleContractError(
                "Stages outside the declared profile scope: "
                + ", ".join(sorted(set(stages) - set(entry.stages))))
        resolved = _module_list(entry.module_ids())
        name, scope = "profile:" + entry.id, tuple(stages or entry.stages)
    elif subworkflow is not None:
        entry = registry.subworkflow(subworkflow)
        resolved = _module_list(entry.modules)
        name, scope = "subworkflow:" + entry.id, (tuple(stages) if stages else None)
    else:
        resolved = _module_list(modules or ())
        name, scope = "modules", (tuple(stages) if stages else None)
    return {"name": name, "modules": resolved, "stages": scope}


def interface(modules: Iterable[Module | str]) -> dict[str, Any]:
    """External inputs/outputs of a module set.

    ``requires`` is every member requirement that no other member satisfies
    under the auto-wiring rule (same key, compatible type), so it is exactly
    what a caller has to provide.  ``provides`` unions member outputs. Both are
    canonicalised (members in id order, alternative types sorted) because the
    surface describes a *set*: the same members in another order used to
    produce a different string.
    """

    entries = sorted(_entries(modules), key=lambda module: module.id)
    requires: dict[str, str] = {}
    provided: dict[str, set] = {}
    for module in entries:
        for key, kind in module.provides.items():
            provided.setdefault(key, set()).update(kind.split("|"))
    for module in entries:
        for key, kind in module.requires.items():
            wanted = set(kind.split("|"))
            satisfied = any(other.id != module.id
                            and wanted & {other.provides.get(key), other.provides.get("*")}
                            for other in entries)
            if satisfied:
                continue
            merged = set(requires.get(key, "").split("|")) - {""}
            requires[key] = "|".join(sorted(merged | wanted))
    reports = sorted({module.report for module in entries if module.report})
    return {"requires": requires,
            "provides": {key: "|".join(sorted(types)) for key, types in sorted(provided.items())},
            "reports": reports,
            "evidence": sorted(module.id for module in entries if module.report)}


def _entries(modules: Iterable[Module | str]) -> list[Module]:
    return [registry.resolve(item) if isinstance(item, str) else item for item in modules]


def build(*, document: Mapping[str, Any] | None = None, profile: str | None = None,
          subworkflow: str | None = None, preset: str | None = None,
          modules: Sequence[str] | None = None,
          stages: Sequence[str] | None = None, stage: str | None = None,
          inputs: Mapping[str, Any] | None = None,
          step_inputs: Mapping[str, Any] | None = None,
          bindings: Mapping[str, Any] | None = None,
          capabilities: Iterable[str] | None = None,
          allow_unimplemented: bool = False) -> dict[str, Any]:
    """Validate a module set and return an executable Pipeline description.

    ``status`` is ``pass`` only when the set can actually be wired and run with
    the declared capabilities; every blocker is listed under ``problems`` with
    a machine-readable ``kind``.
    """

    if document is not None:
        if not isinstance(document, Mapping):
            raise ModuleContractError("Module plan document must be an object")
        unknown = set(document) - {"schema_version", "profile", "subworkflow", "preset",
                                   "modules", "stages", "stage", "inputs", "step_inputs",
                                   "bindings", "capabilities", "name"}
        if unknown:
            raise ModuleContractError("Unknown module plan fields: " + ", ".join(sorted(unknown)))
        if document.get("schema_version", 1) != 1:
            raise ModuleContractError("Unsupported module plan schema version")
        if any(value is not None for value in (profile, subworkflow, preset, modules,
                                               inputs, step_inputs, bindings, stages, stage)):
            raise ModuleContractError("Pass either a document or explicit arguments")
        if document.get("subworkflow") and document.get("preset"):
            raise ModuleContractError("Declare subworkflow or preset, not both")
        profile, modules = document.get("profile"), document.get("modules")
        subworkflow = document.get("subworkflow") or document.get("preset")
        stages, inputs = document.get("stages"), document.get("inputs") or {}
        stage = document.get("stage")
        bindings = document.get("bindings") or {}
        step_inputs = document.get("step_inputs") or {}
        if capabilities is None:
            capabilities = document.get("capabilities")
    inputs = dict(inputs or {})
    # Per-step literals: the runner shares run inputs with every step, so two
    # modules needing the same key with different values must seed it here.
    literals: dict[tuple[str, str], Any] = {}
    for key, value in dict(step_inputs or {}).items():
        if not isinstance(key, str) or "." not in key:
            raise ModuleContractError("step_inputs keys must be <module>.<input>: " + str(key))
        module_id, input_name = key.rsplit(".", 1)
        if not module_id or not input_name:
            raise ModuleContractError("step_inputs keys must be <module>.<input>: " + str(key))
        literals[(module_id, input_name)] = value
    explicit = {key: dict(value) for key, value in dict(bindings or {}).items()}
    for target, binding in explicit.items():
        if (not isinstance(binding, Mapping) or set(binding) != {"step", "path"}
                or not isinstance(binding["path"], list)):
            raise ModuleContractError("Explicit binding requires step and path: " + str(target))

    selection = select(profile=profile, subworkflow=subworkflow, preset=preset,
                       modules=modules, stages=stages)
    entries, scope = selection["modules"], selection["stages"]
    if stage is not None:
        entries, scope = _stage_slice(entries, stage, scope)
    by_id = {module.id: module for module in entries}
    problems: list[dict[str, Any]] = []

    # Capability preconditions: a module that needs hardware/lease/task binding
    # cannot silently run as a standalone analysis.
    available = set(capabilities or ())
    for module in entries:
        lacking = sorted(set(module.needs()) - available)
        if lacking:
            problems.append({"kind": "unsatisfied-need", "module": module.id,
                             "needs": lacking})
        if module.implementation is None and not allow_unimplemented:
            problems.append({"kind": "module-not-implemented", "module": module.id})

    # Pass 1: choose providers for every requirement.
    wires: dict[str, dict[str, dict[str, Any]]] = {module.id: {} for module in entries}
    for module in entries:
        for key, kind in module.requires.items():
            binding = explicit.get(key) if module.id == _sole_consumer(entries, key) else None
            if binding is None:
                binding = explicit.get(module.id + "." + key)
            if binding is not None:
                if binding["step"] not in by_id:
                    problems.append({"kind": "binding-outside-set", "module": module.id,
                                     "input": key, "step": binding["step"]})
                    continue
                wires[module.id][key] = {**binding, "type": kind}
                continue
            wanted = set(kind.split("|"))
            providers = [other.id for other in entries
                         if other.id != module.id and other.provides.get(key) in wanted]
            if len(providers) == 1:
                wires[module.id][key] = {"step": providers[0], "path": [key], "type": kind}
                continue
            if len(providers) > 1:
                problems.append({"kind": "ambiguous-input", "module": module.id, "input": key,
                                 "candidates": sorted(providers),
                                 "next": "Write an explicit binding as <module>.<input>"})
                continue
            # No keyed provider: a module may declare ``"*": "type"`` when its
            # whole result is the value a consumer wants (the execution result
            # a log summariser parses).  Still needs a unique provider.
            whole = [other.id for other in entries
                     if other.id != module.id and other.provides.get("*") in wanted]
            if len(whole) == 1:
                wires[module.id][key] = {"step": whole[0], "path": [], "type": kind}
            elif len(whole) > 1:
                problems.append({"kind": "ambiguous-input", "module": module.id,
                                 "input": key, "candidates": sorted(whole),
                                 "next": "Write an explicit binding as <module>.<input>"})
            elif key in inputs or (module.id, key) in literals:
                continue  # supplied directly by the caller for this run
            else:
                problems.append({"kind": "missing-input", "module": module.id, "input": key,
                                 "type": kind, "next": "Provide it as a run input or binding"})

    # Pass 2: dependency order.  Edges only point from providers to consumers.
    depends = {module.id: sorted({binding["step"] for binding in wires[module.id].values()})
               for module in entries}

    # A stage whose gate needs a report this set cannot produce means the
    # sub-workflow was thinned into a weaker gate.
    if scope is not None:
        for gap in missing_producers(entries, scope):
            stage, kind = gap.split(":", 1)
            problems.append({"kind": "stage-evidence-dropped", "stage": stage, "report": kind})

    def public(bindings: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
        return {name: {"step": binding["step"], "path": list(binding["path"])}
                for name, binding in bindings.items()}

    steps = [{"id": module.id,
              "capability": module.implementation[0] if module.implementation else None,
              "action": module.implementation[1] if module.implementation else None,
              "depends_on": depends[module.id],
              "inputs": {name: value for (owner, name), value in literals.items()
                         if owner == module.id},
              "config": {"report_kind": module.report} if module.report else {},
              **({"bindings": public(wires[module.id])} if wires[module.id] else {})}
             for module in entries]
    plan = {"schema_version": 1, "name": selection["name"], "steps": steps}
    if all(step["capability"] for step in steps):
        try:
            PipelinePlan.from_dict({key: plan[key] for key in ("schema_version", "name", "steps")})
        except ValueError as exc:  # pragma: no cover - defensive, wiring bugs only
            problems.append({"kind": "invalid-wiring", "detail": str(exc)})

    gates = derive(entries, scope) if scope is not None else None
    return {
        "status": "incomplete" if problems else "pass",
        "name": selection["name"] + ("" if stage is None else ":stage-" + stage),
        "modules": [module.id for module in entries],
        "stage": stage,
        "stages": list(scope) if scope is not None else list(stage_scope(entries)),
        "stage_scope_declared": scope is not None,
        "gates": gates,
        "evidence_reports": evidence_reports(entries),
        "volatile": sorted(module.id for module in entries if module.volatile),
        "implementation": {module.id: (None if module.implementation is None else
                                       {"capability": module.implementation[0],
                                        "action": module.implementation[1]})
                           for module in entries},
        "plan": plan,
        "problems": problems,
    }


def _stage_slice(entries: list[Module], stage: str, scope: Sequence[str] | None):
    """Keep only the modules that serve one stage, so a stage plan is runnable."""

    if stage not in _flow_stages():
        raise ModuleContractError("Unknown stage: " + str(stage))
    if scope is not None and stage not in scope:
        raise ModuleContractError("Stage " + stage + " is outside the declared stage scope")
    kept = [module for module in entries if stage in module.stage]
    if not kept:
        raise ModuleContractError("No module serves stage: " + stage)
    return kept, (stage,)


def _flow_stages():
    from ..catalog.contracts import FLOW_STAGES
    return tuple(x for x in FLOW_STAGES if x != "completed")


def _sole_consumer(entries: Sequence[Module], key: str) -> str | None:
    consumers = [module.id for module in entries if key in module.requires]
    return consumers[0] if len(consumers) == 1 else None


def _substitute(value: Any, inputs: Mapping[str, Any]) -> Any:
    if isinstance(value, str) and value.startswith("$"):
        name = value[1:]
        if name not in inputs:
            raise ModuleContractError("Subworkflow requires run input: " + name)
        return inputs[name]
    if isinstance(value, Mapping):
        return {key: _substitute(item, inputs) for key, item in value.items()}
    if isinstance(value, list):
        return [_substitute(item, inputs) for item in value]
    return value


def subworkflow_plan(name: str, inputs: Mapping[str, Any] | None = None) -> PipelinePlan:
    """Build the declarative Pipeline of a template subworkflow."""

    entry = registry.subworkflow(name)
    if entry.template is None:
        raise ModuleContractError("Subworkflow has no declarative steps: " + name)
    document = _substitute(entry.template, dict(inputs or {}))
    steps = []
    for step in document["steps"]:
        module = registry.module(step["module"])
        if module.implementation is None:
            raise ModuleContractError("Subworkflow step has no implementation: " + module.id)
        action = step.get("action", module.implementation[1])
        if action not in module.actions:
            raise ModuleContractError("Subworkflow step action is not declared by the module: "
                                      + module.id + "." + action)
        steps.append({"id": step["id"], "capability": module.implementation[0], "action": action,
                      "depends_on": list(step.get("depends_on", [])),
                      "inputs": dict(step.get("inputs", {})),
                      "config": dict(step.get("config", {})),
                      **({"bindings": dict(step["bindings"])} if step.get("bindings") else {})})
    return PipelinePlan.from_dict({"name": document["name"], "steps": steps})


preset_plan = subworkflow_plan
