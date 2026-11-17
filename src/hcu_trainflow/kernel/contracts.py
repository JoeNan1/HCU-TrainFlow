"""Small, dependency-free contracts shared by workflow capabilities.

These contracts are intentionally independent from the legacy SQLite Store and
from any execution backend.  They describe the boundary between a capability
and an orchestrator; artifact persistence and task gates remain owned by the
existing workflow control plane until the migration is complete.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol


CAPABILITY_STATUSES = frozenset({
    "pass", "complete", "fail", "incomplete", "unknown", "blocked",
})


def _mapping(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TypeError("Expected a mapping")
    return dict(value)


@dataclass(frozen=True)
class CapabilityContext:
    """Execution identity passed to every capability invocation."""

    task_id: str
    context: str
    workspace: Path
    mode: str = "standalone"
    state: str = "prepared"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.task_id, str) or not self.task_id.strip():
            raise ValueError("Capability context requires task_id")
        if not isinstance(self.context, str) or not self.context.strip():
            raise ValueError("Capability context requires context")
        if not isinstance(self.workspace, Path):
            raise TypeError("Capability workspace must be a pathlib.Path")
        if not isinstance(self.metadata, Mapping):
            raise TypeError("Capability metadata must be a mapping")

    @classmethod
    def from_task(cls, task: Mapping[str, Any], workspace: str | Path) -> "CapabilityContext":
        if not isinstance(task, Mapping):
            raise TypeError("Task must be a mapping")
        spec = task.get("spec", {})
        if not isinstance(spec, Mapping):
            raise ValueError("Task spec must be a mapping")
        return cls(
            task_id=str(task["id"]),
            context=str(task["context"]),
            workspace=Path(workspace).resolve(),
            mode=str(spec.get("mode", "standalone")),
            state=str(task.get("state", "prepared")),
            metadata={"spec": dict(spec), "revision": task.get("revision", 0),
                      "context_epoch": task.get("context_epoch", 0)},
        )


@dataclass(frozen=True)
class CapabilityRequest:
    """Validated request sent from a pipeline or an independent entrypoint."""

    capability: str
    action: str
    inputs: Mapping[str, Any] = field(default_factory=dict)
    config: Mapping[str, Any] = field(default_factory=dict)
    request_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.capability, str) or not self.capability.strip():
            raise ValueError("Capability request requires capability")
        if not isinstance(self.action, str) or not self.action.strip():
            raise ValueError("Capability request requires action")
        if not isinstance(self.inputs, Mapping) or not isinstance(self.config, Mapping):
            raise TypeError("Capability inputs and config must be mappings")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any], *, capability: str | None = None) -> "CapabilityRequest":
        if not isinstance(value, Mapping):
            raise TypeError("Capability request must be an object")
        allowed = {"capability", "action", "inputs", "config", "request_id"}
        unknown = set(value) - allowed
        if unknown:
            raise ValueError("Unknown capability request fields: " + ", ".join(sorted(unknown)))
        selected = capability or value.get("capability")
        return cls(
            capability=selected,
            action=value.get("action", "run"),
            inputs=_mapping(value.get("inputs")),
            config=_mapping(value.get("config")),
            request_id=value.get("request_id"),
        )


@dataclass(frozen=True)
class CapabilityResult:
    """Structured result returned by a capability.

    ``status`` is an observation of the capability invocation.  It does not by
    itself advance a training task; the existing report and review gates remain
    authoritative for task transitions.
    """

    capability: str
    action: str
    status: str
    outputs: Mapping[str, Any] = field(default_factory=dict)
    evidence: tuple[str, ...] = ()
    message: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in CAPABILITY_STATUSES:
            raise ValueError("Unsupported capability status: " + str(self.status))
        if not isinstance(self.outputs, Mapping) or not isinstance(self.metadata, Mapping):
            raise TypeError("Capability outputs and metadata must be mappings")
        if not isinstance(self.evidence, tuple) or any(not isinstance(x, str) or not x for x in self.evidence):
            raise TypeError("Capability evidence must be a tuple of nonempty strings")

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "action": self.action,
            "status": self.status,
            "outputs": dict(self.outputs),
            "evidence": list(self.evidence),
            "message": self.message,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CapabilityResult":
        """Rehydrate a retained result for Pipeline resume.

        Only the result contract is restored; persisted artifacts and reports
        are still verified by the Store before they are used as evidence.
        """

        if not isinstance(value, Mapping):
            raise TypeError("Capability result must be an object")
        evidence = value.get("evidence", [])
        if not isinstance(evidence, list):
            raise TypeError("Capability result evidence must be a list")
        return cls(
            capability=value.get("capability"),
            action=value.get("action"),
            status=value.get("status"),
            outputs=_mapping(value.get("outputs")),
            evidence=tuple(evidence),
            message=value.get("message", ""),
            metadata=_mapping(value.get("metadata")),
        )


class Capability(Protocol):
    """Runtime protocol implemented by an independently invocable capability."""

    name: str

    def actions(self) -> tuple[str, ...]:
        ...

    def run(self, context: CapabilityContext, request: CapabilityRequest) -> CapabilityResult:
        ...
