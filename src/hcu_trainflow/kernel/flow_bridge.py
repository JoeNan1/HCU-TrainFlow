"""Compatibility bridge from the persistent Flow state machine to Pipeline clients.

The legacy :mod:`hcu_trainflow.flow` module remains the single owner of task
transitions, review gates, leases and reconciliation.  This bridge only
projects its next decision into the small shape consumed by modular Pipeline
and Agent entrypoints; it never advances a task or implements another state
machine.
"""
from __future__ import annotations

from typing import Any


class FlowPipelineBridge:
    """Expose a Flow decision as a read-only modular Pipeline decision."""

    def __init__(self, store: Any):
        self.store = store

    def next(self, task_id: str) -> dict[str, Any]:
        # Import lazily so standalone capability and plan commands remain free
        # of the legacy Flow/knowledge import graph.
        from .. import flow

        decision = flow.next_step(self.store, task_id)
        return self._project(decision)

    @staticmethod
    def _project(decision: dict[str, Any]) -> dict[str, Any]:
        action = decision.get("action")
        reasons = list(decision.get("reasons") or [])
        operations = list(decision.get("operations") or [])
        blocked_by = reasons + [f"operation:{value}" for value in operations]

        if action in {"completed", "cancelled"}:
            gate_status = "complete"
        elif blocked_by or action in {"human", "reconcile", "coordinate"}:
            gate_status = "blocked"
        elif action in {"review", "advance"}:
            gate_status = "awaiting-review" if action == "review" else "ready-to-advance"
        else:
            gate_status = "pending"

        return {
            "task": decision.get("task"),
            "state": decision.get("state"),
            "context": decision.get("context"),
            "goal": decision.get("goal"),
            "action": action,
            "current": {
                "action": action,
                "skill": decision.get("skill"),
                "target": decision.get("target"),
            },
            "skill": decision.get("skill"),
            "gate": {
                "status": gate_status,
                "blocked_by": blocked_by,
                "reasons": reasons,
                "required_reports": list(decision.get("required_reports") or []),
            },
            "flow_decision": decision,
        }


def pipeline_next(store: Any, task_id: str) -> dict[str, Any]:
    """Return the modular projection for ``task_id`` without advancing it."""

    return FlowPipelineBridge(store).next(task_id)

