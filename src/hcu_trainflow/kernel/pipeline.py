"""Declarative capability pipeline execution.

The runner is deliberately small: it orders independent capability calls and
propagates results. Task-bound persistence and evidence registration are
optional callbacks owned by the public runtime service; review and stage
transitions remain in the existing flow control plane.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Callable
from typing import Any, Mapping

from .contracts import CapabilityContext, CapabilityRequest, CapabilityResult


@dataclass(frozen=True)
class PipelineStep:
    id: str
    capability: str
    action: str = "run"
    depends_on: tuple[str, ...] = ()
    inputs: Mapping[str, Any] = field(default_factory=dict)
    config: Mapping[str, Any] = field(default_factory=dict)
    required: bool = True
    bindings: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PipelineStep":
        if not isinstance(value, Mapping):
            raise ValueError("Pipeline step must be an object")
        allowed = {"id", "capability", "action", "depends_on", "inputs", "config", "required", "bindings"}
        unknown = set(value) - allowed
        if unknown:
            raise ValueError("Unknown pipeline step fields: " + ", ".join(sorted(unknown)))
        step_id, capability = value.get("id"), value.get("capability")
        if not isinstance(step_id, str) or not step_id.strip():
            raise ValueError("Pipeline step requires id")
        if not isinstance(capability, str) or not capability.strip():
            raise ValueError("Pipeline step requires capability")
        depends = value.get("depends_on", [])
        if not isinstance(depends, list) or any(not isinstance(x, str) or not x.strip() for x in depends):
            raise ValueError("Pipeline depends_on must be a list of step IDs")
        if len(set(depends)) != len(depends):
            raise ValueError("Pipeline dependencies must be unique")
        inputs, config = value.get("inputs", {}), value.get("config", {})
        if not isinstance(inputs, Mapping) or not isinstance(config, Mapping):
            raise ValueError("Pipeline step inputs/config must be objects")
        required = value.get("required", True)
        if type(required) is not bool:
            raise ValueError("Pipeline step required must be boolean")
        bindings = value.get("bindings", {})
        if not isinstance(bindings, Mapping):
            raise ValueError("Pipeline bindings must be an object")
        for target, binding in bindings.items():
            if not isinstance(target, str) or not target or target == "dependencies":
                raise ValueError("Binding requires a nonempty input field other than dependencies")
            if not isinstance(binding, Mapping) or set(binding) != {"step", "path"}:
                raise ValueError("Binding requires step and path")
            if binding["step"] not in depends:
                raise ValueError("Binding must reference a direct dependency")
            path = binding["path"]
            if not isinstance(path, list) or any(not isinstance(p, str) or not p for p in path):
                raise ValueError("Binding path must be a list of output object keys")
        return cls(step_id, capability, value.get("action", "run"), tuple(depends), dict(inputs), dict(config), required, dict(bindings))


@dataclass(frozen=True)
class PipelinePlan:
    name: str
    steps: tuple[PipelineStep, ...]
    schema_version: int = 1

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PipelinePlan":
        if not isinstance(value, Mapping):
            raise ValueError("Pipeline plan must be an object")
        allowed = {"schema_version", "name", "steps"}
        unknown = set(value) - allowed
        if unknown:
            raise ValueError("Unknown pipeline plan fields: " + ", ".join(sorted(unknown)))
        if value.get("schema_version", 1) != 1:
            raise ValueError("Unsupported pipeline schema version")
        name, raw_steps = value.get("name"), value.get("steps")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Pipeline plan requires name")
        if not isinstance(raw_steps, list) or not raw_steps:
            raise ValueError("Pipeline plan requires nonempty steps")
        steps = tuple(PipelineStep.from_dict(row) for row in raw_steps)
        ids = [step.id for step in steps]
        if len(set(ids)) != len(ids):
            raise ValueError("Pipeline step IDs must be unique")
        known = set(ids)
        for step in steps:
            missing = set(step.depends_on) - known
            if missing:
                raise ValueError("Pipeline step has unknown dependencies: " + ", ".join(sorted(missing)))
        # Validate acyclicity once at the plan boundary.
        visiting, visited = set(), set()
        by_id = {step.id: step for step in steps}

        def visit(step_id: str) -> None:
            if step_id in visiting:
                raise ValueError("Pipeline contains a dependency cycle")
            if step_id in visited:
                return
            visiting.add(step_id)
            for dependency in by_id[step_id].depends_on:
                visit(dependency)
            visiting.remove(step_id)
            visited.add(step_id)

        for step_id in ids:
            visit(step_id)
        return cls(name=name, steps=steps)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "name": self.name,
            "steps": [
                {"id": step.id, "capability": step.capability, "action": step.action,
                 "depends_on": list(step.depends_on), "inputs": dict(step.inputs),
                 "config": dict(step.config), "required": step.required,
                 **({"bindings": dict(step.bindings)} if step.bindings else {})}
                for step in self.steps
            ],
        }

    def ordered_steps(self) -> tuple[PipelineStep, ...]:
        """Return a stable topological order independent of file ordering."""

        by_id = {step.id: step for step in self.steps}
        pending = {step.id: set(step.depends_on) for step in self.steps}
        order: list[PipelineStep] = []
        while pending:
            ready = [step for step in self.steps if step.id in pending and not pending[step.id]]
            if not ready:
                # ``from_dict`` already checks this, but retain a defensive
                # guard for plans constructed directly by Python callers.
                raise ValueError("Pipeline contains a dependency cycle")
            for step in ready:
                order.append(step)
                pending.pop(step.id)
                for dependencies in pending.values():
                    dependencies.discard(step.id)
        return tuple(order)


@dataclass(frozen=True)
class PipelineResult:
    name: str
    status: str
    steps: Mapping[str, CapabilityResult]

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "status": self.status,
                "steps": {key: value.to_dict() for key, value in self.steps.items()}}


class PipelineRunner:
    def __init__(self, registry: Any):
        self.registry = registry

    def run(self, plan: PipelinePlan, context: CapabilityContext,
            initial_inputs: Mapping[str, Any] | None = None,
            prior_results: Mapping[str, CapabilityResult] | None = None,
            on_result: Callable[[PipelineStep, CapabilityResult], None] | None = None,
            on_start: Callable[[PipelineStep], None] | None = None,
            invoke: Callable[[CapabilityContext, CapabilityRequest], CapabilityResult] | None = None) -> PipelineResult:
        results: dict[str, CapabilityResult] = dict(prior_results or {})
        initial = dict(initial_inputs or {})
        known = {step.id for step in plan.steps}
        unknown_prior = set(results) - known
        if unknown_prior:
            raise ValueError("Prior Pipeline results contain unknown steps: " + ", ".join(sorted(unknown_prior)))
        for step in plan.ordered_steps():
            if step.id in results and results[step.id].status in {"pass", "complete"}:
                continue
            # A failed or blocked retained step is deliberately re-executed;
            # the successful dependency results above it remain reusable.
            dependency_results = {name: results[name].to_dict() for name in step.depends_on}
            failed_dependencies = [name for name, result in dependency_results.items()
                                   if result["status"] in {"fail", "unknown", "blocked"}
                                   or (step.required and result["status"] == "incomplete")]
            if failed_dependencies:
                results[step.id] = CapabilityResult(
                    step.capability, step.action, "blocked",
                    message="Dependencies did not pass: " + ", ".join(failed_dependencies),
                    metadata={"blocked_by": failed_dependencies})
                if on_result is not None:
                    on_result(step, results[step.id])
                continue
            if on_start is not None:
                on_start(step)
            try:
                capability = self.registry.resolve(step.capability)
                inputs = {**initial, **dict(step.inputs), "dependencies": dependency_results}
                for target, binding in step.bindings.items():
                    value = dependency_results[binding["step"]]["outputs"]
                    for key in binding["path"]:
                        if not isinstance(value, Mapping) or key not in value:
                            raise ValueError("Missing dependency output for binding: " + target)
                        value = value[key]
                    inputs[target] = value
                request = CapabilityRequest(step.capability, step.action, inputs, step.config)
                result = invoke(context, request) if invoke else capability.run(context, request)
                if not isinstance(result, CapabilityResult):
                    raise TypeError("Capability returned an invalid result")
                results[step.id] = result
            except Exception as exc:  # Capability failures are retained as workflow facts.
                results[step.id] = CapabilityResult(
                    step.capability, step.action, "fail",
                    message=type(exc).__name__ + ": " + str(exc))
            if on_result is not None:
                on_result(step, results[step.id])
        statuses = [result.status for result in results.values()]
        status = "fail" if any(value in {"fail", "unknown", "blocked"} for value in statuses) else \
            "incomplete" if any(value == "incomplete" for value in statuses) else "complete"
        return PipelineResult(plan.name, status, results)
