"""Small capability facades over existing deterministic analysis functions.

These are the first migration seam.  They do not duplicate the legacy logic;
they adapt its inputs and outputs to the new capability contract.
"""
from __future__ import annotations

from typing import Any

from ..kernel.contracts import CapabilityContext, CapabilityRequest, CapabilityResult


def _input(request: CapabilityRequest, name: str) -> Any:
    if name not in request.inputs:
        raise ValueError("Missing capability input: " + name)
    return request.inputs[name]


class EnvironmentCapability:
    name = "environment.check"

    def actions(self) -> tuple[str, ...]:
        return ("check", "collect", "run")

    def run(self, context: CapabilityContext, request: CapabilityRequest) -> CapabilityResult:
        if request.action not in self.actions():
            raise ValueError("Unsupported action for " + self.name + ": " + request.action)
        from ..environment import assess_health
        contract = _input(request, "contract")
        if not isinstance(contract, dict) or contract.get("context") != context.context:
            return CapabilityResult(self.name, request.action, "incomplete",
                                    outputs={"context": context.context, "status": "incomplete",
                                             "reasons": ["environment-contract-context-mismatch"]})
        if request.action == "collect":
            from .scenarios import collect_environment
            return collect_environment(context, request)
        observations = _input(request, "observations")
        result = assess_health(contract, observations)
        result["observations"] = observations
        return CapabilityResult(self.name, request.action, result["status"], outputs=result,
                                evidence=tuple(result.get("evidence", [])),
                                metadata={"context": context.context})


class ProfilingCapability:
    name = "profiling.analyze"

    def actions(self) -> tuple[str, ...]:
        return ("analyze", "summarize", "run")

    def run(self, context: CapabilityContext, request: CapabilityRequest) -> CapabilityResult:
        if request.action not in self.actions():
            raise ValueError("Unsupported action for " + self.name + ": " + request.action)
        if request.action == "summarize":
            from .baseline import summarize_hipprof
            return summarize_hipprof(context, request)
        from ..analysis import analyze_trace
        result = analyze_trace(_input(request, "trace"), _input(request, "window"),
                               request.inputs.get("models"), request.inputs.get("target", 0.9),
                               request.inputs.get("attribution"))
        return CapabilityResult(self.name, request.action, result["status"], outputs=result,
                                metadata={"context": context.context})


class QualityCapability:
    name = "quality.loss"

    def actions(self) -> tuple[str, ...]:
        return ("compare", "run")

    def run(self, context: CapabilityContext, request: CapabilityRequest) -> CapabilityResult:
        if request.action not in self.actions():
            raise ValueError("Unsupported action for " + self.name + ": " + request.action)
        from ..quality import compare_loss
        result = compare_loss(_input(request, "contract"), _input(request, "baseline"),
                              _input(request, "candidate"))
        return CapabilityResult(self.name, request.action, result["status"], outputs=result,
                                metadata={"context": context.context})


class OccupancyCapability:
    """Admission evidence check; collection remains an external adapter."""

    name = "environment.occupancy"

    def actions(self) -> tuple[str, ...]:
        return ("check", "run")

    def run(self, context: CapabilityContext, request: CapabilityRequest) -> CapabilityResult:
        if request.action not in self.actions():
            raise ValueError("Unsupported action for " + self.name + ": " + request.action)
        from ..admission import assess_occupancy
        kwargs = {}
        if "now" in request.inputs:
            kwargs["now"] = request.inputs["now"]
        result = assess_occupancy(_input(request, "contract"), _input(request, "observations"), **kwargs)
        return CapabilityResult(self.name, request.action, result["status"], outputs=result,
                                evidence=tuple(result.get("evidence", [])),
                                metadata={"context": context.context})


class ProfilingPlanCapability:
    name = "profiling.plan"

    def actions(self) -> tuple[str, ...]:
        return ("plan", "run")

    def run(self, context: CapabilityContext, request: CapabilityRequest) -> CapabilityResult:
        if request.action not in self.actions():
            raise ValueError("Unsupported action for " + self.name + ": " + request.action)
        from ..analysis import profile_plan
        result = profile_plan(_input(request, "groups"), _input(request, "available"))
        return CapabilityResult(self.name, request.action, result["status"], outputs=result,
                                metadata={"context": context.context})


class QualityProxyCapability:
    name = "quality.proxy"

    def actions(self) -> tuple[str, ...]:
        return ("check", "run")

    def run(self, context: CapabilityContext, request: CapabilityRequest) -> CapabilityResult:
        if request.action not in self.actions():
            raise ValueError("Unsupported action for " + self.name + ": " + request.action)
        from ..quality import proxy_contract
        result = proxy_contract(_input(request, "full"), _input(request, "candidate"),
                                request.inputs.get("authorization"))
        return CapabilityResult(self.name, request.action, result["status"], outputs=result,
                                metadata={"context": context.context})


class QualityIterationCapability:
    name = "quality.iteration"

    def actions(self) -> tuple[str, ...]:
        return ("assess", "run")

    def run(self, context: CapabilityContext, request: CapabilityRequest) -> CapabilityResult:
        if request.action not in self.actions():
            raise ValueError("Unsupported action for " + self.name + ": " + request.action)
        from ..quality import assess_iteration
        result = assess_iteration(
            correctness=_input(request, "correctness"),
            baseline_times=_input(request, "baseline_times"),
            candidate_times=_input(request, "candidate_times"),
            context=request.inputs.get("context", context.context),
            max_regression=request.inputs.get("max_regression", 0.0),
        )
        status = {"iteration-kept": "pass", "rejected": "fail"}.get(result["status"], "incomplete")
        return CapabilityResult(self.name, request.action, status, outputs=result,
                                metadata={"context": context.context})


class AdaptationCapability(QualityProxyCapability):
    """Model adaptation contract under its domain-facing capability name."""

    name = "adaptation.proxy"


class OptimizationCapability(QualityIterationCapability):
    """A reusable local optimization acceptance check."""

    name = "optimization.iteration"


class ScaleAdmissionCapability(OccupancyCapability):
    """Scale admission reuses the conservative occupancy contract."""

    name = "scale.admission"


class ObservationCapability:
    name = "observation.collect"

    def actions(self) -> tuple[str, ...]:
        return ("collect", "run")

    def run(self, context: CapabilityContext, request: CapabilityRequest) -> CapabilityResult:
        if request.action not in self.actions():
            raise ValueError("Unsupported action for " + self.name + ": " + request.action)
        from ..training_logs import observe_once
        result = observe_once(
            context.workspace,
            context.task_id,
            _input(request, "manifest"),
            _input(request, "policy"),
            _input(request, "state_dir"),
            request.inputs.get("exit_receipt"),
        )
        status = result.get("status", "unknown")
        if status not in {"pass", "complete", "fail", "incomplete", "unknown", "blocked"}:
            status = "unknown"
        return CapabilityResult(self.name, request.action, status, outputs=result,
                                evidence=tuple(result.get("evidence", [])) if isinstance(result.get("evidence"), list) else (),
                                metadata={"context": context.context})


class DeliveryCapability:
    name = "delivery.monitor-report"

    def actions(self) -> tuple[str, ...]:
        return ("render", "run")

    def run(self, context: CapabilityContext, request: CapabilityRequest) -> CapabilityResult:
        if request.action not in self.actions():
            raise ValueError("Unsupported action for " + self.name + ": " + request.action)
        from ..core import Store
        from ..delivery import monitor_report
        result = monitor_report(
            Store(context.workspace), context.task_id, _input(request, "output"),
            attempt=request.inputs.get("attempt"), context=request.inputs.get("context", context.context),
        )
        return CapabilityResult(self.name, request.action, "complete", outputs=result,
                                metadata={"context": context.context})


class ExecutionCapability:
    """Command-card adapter; execution still passes the legacy Flow guards."""

    name = "execution.command"

    def actions(self) -> tuple[str, ...]:
        return ("plan", "run")

    def run(self, context: CapabilityContext, request: CapabilityRequest) -> CapabilityResult:
        if request.action not in self.actions():
            raise ValueError("Unsupported action for " + self.name + ": " + request.action)
        from ..adapters.execution import TrainFlowExecutionAdapter
        if type(request.config.get("stdout_json", False)) is not bool:
            raise ValueError("stdout_json must be boolean")
        adapter = TrainFlowExecutionAdapter()
        card = _input(request, "card")
        if request.action == "plan":
            result = adapter.plan(card)
            return CapabilityResult(self.name, request.action, "complete", outputs=result,
                                    metadata={"context": context.context})
        from ..core import Store
        store = Store(context.workspace)
        task = store.task(context.task_id)
        if task["context"] != context.context:
            raise ValueError("Execution capability context does not match the task")
        result = adapter.run(
            store, context.task_id, _input(request, "operation"), card,
            _input(request, "lease"), assignment=request.inputs.get("assignment"),
            owner=request.inputs.get("owner"), token=request.inputs.get("token"),
            expected_context=context.context, expected_context_epoch=task["context_epoch"],
        )
        status = result.get("status", "unknown")
        if status == "failed":
            status = "fail"
        elif status == "complete":
            status = "complete"
        elif status not in {"pass", "incomplete", "unknown", "blocked"}:
            status = "unknown"
        if request.config.get("stdout_json") and status == "complete":
            import json
            try:
                document = json.loads(store.artifact(result["evidence"][0]))
                # Retain the command's raw stdout/stderr/plan as evidence of
                # explicitly named measurement records. Never invent executed
                # coverage, context, dispatch confirmation or profiler state.
                if isinstance(document, dict):
                    from .scenarios import _evidence
                    document = dict(document)
                    for key in ("baseline", "candidate", "correctness"):
                        if isinstance(document.get(key), dict):
                            record = document[key]
                            document[key] = dict(record, evidence=list(dict.fromkeys(
                                [*_evidence(record), *result["evidence"]])))
                result = dict(result, document=document)
            except (ValueError, KeyError, IndexError, TypeError) as exc:
                status = "incomplete"
                result = dict(result, execution_status=result["status"], status=status,
                              parsing_error="Completed stdout is not valid measurement JSON: " + str(exc))
        return CapabilityResult(self.name, request.action, status, outputs=result,
                                evidence=tuple(result.get("evidence", [])),
                                metadata={"context": context.context})
