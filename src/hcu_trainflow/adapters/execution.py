"""Adapter boundary for the legacy command execution implementation."""
from __future__ import annotations

from typing import Any, Mapping


class TrainFlowExecutionAdapter:
    """Expose command planning/execution without coupling capabilities to it."""

    name = "trainflow.execution"

    def plan(self, card: Mapping[str, Any]) -> dict[str, Any]:
        from ..execution import command_plan
        return command_plan(dict(card))

    def run(self, store: Any, task: str, operation: str, card: Mapping[str, Any], lease: Mapping[str, Any], **kwargs: Any) -> dict[str, Any]:
        from ..execution import run_command
        return run_command(store, task, operation, dict(card), dict(lease), **kwargs)
