"""Executable, independently invocable analysis scenarios.

The facades reuse the established validators and execution controller. They do
not advance Flow or turn generated reports into training qualification.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..core import FlowError, Store, digest
from ..kernel.contracts import CapabilityContext, CapabilityRequest, CapabilityResult


def _required(request, name):
    if name not in request.inputs:
        raise ValueError("Missing capability input: " + name)
    return request.inputs[name]


def _evidence(*records):
    values = []
    for record in records:
        evidence = record.get("evidence", [])
        if not isinstance(evidence, list) or any(not isinstance(x, str) or not x for x in evidence):
            raise ValueError("Scenario evidence must be a list of artifact IDs")
        values.extend(evidence)
    return tuple(dict.fromkeys(values))


def collect_environment(context, request):
    """Collect observations through the existing Task/Lease/Operation guards."""
    if "spec" not in context.metadata:
        raise FlowError("Environment collection requires a task-bound execution context")
    store = Store(context.workspace)
    task = store.task(context.task_id)
    if task["context"] != context.context:
        raise FlowError("Environment collection context does not match the task")
    execution = _required(request, "execution")
    if not isinstance(execution, dict):
        raise ValueError("Environment execution must be an object")
    from ..adapters.execution import TrainFlowExecutionAdapter
    kwargs = {key: execution[key] for key in ("assignment", "owner", "token") if key in execution}
    result = TrainFlowExecutionAdapter().run(
        store, context.task_id, execution["operation"], execution["card"], execution["lease"],
        expected_context=context.context, expected_context_epoch=task["context_epoch"], **kwargs)
    evidence = tuple(result.get("evidence", []))
    if result.get("status") != "complete":
        status = {"failed": "fail", "unknown": "unknown", "blocked": "blocked"}.get(result.get("status"), "incomplete")
        return CapabilityResult("environment.check", request.action, status,
                                outputs={"context": context.context, "status": status,
                                         "execution": result, "evidence": list(evidence)}, evidence=evidence)
    try:
        document = json.loads(store.artifact(evidence[0]))
        observations = document.get("measurements") if isinstance(document, dict) else document
        if not isinstance(observations, list) or not observations or any(not isinstance(row, dict) for row in observations):
            raise ValueError("Collector must emit a nonempty measurements list")
        observations = [dict(row, evidence=list(dict.fromkeys([*_evidence(row), *evidence]))) for row in observations]
    except (ValueError, IndexError, TypeError) as exc:
        return CapabilityResult("environment.check", request.action, "incomplete",
                                outputs={"context": context.context, "status": "incomplete", "execution": result,
                                         "reasons": ["Collector stdout is not a valid measurements JSON document"],
                                         "evidence": list(evidence)}, evidence=evidence, message=str(exc))
    from ..environment import assess_health
    assessment = assess_health(_required(request, "contract"), observations)
    assessment.update(observations=observations, execution=result)
    return CapabilityResult("environment.check", request.action, assessment["status"], outputs=assessment,
                            evidence=_evidence(assessment), metadata={"context": context.context})


class TraceLensCapability:
    name = "profiling.tracelens"

    def actions(self):
        return ("analyze", "run")

    def run(self, context: CapabilityContext, request: CapabilityRequest) -> CapabilityResult:
        if request.action not in self.actions():
            raise ValueError("Unsupported action for " + self.name + ": " + request.action)
        store = Store(context.workspace)
        if request.inputs.get("mode") == "hipprof":
            from ..tracelens_features import run_feature
            from ..core import fingerprint, write_json
            native = {"mode": "hipprof"}
            if "trace_artifact" in request.inputs:
                sha = request.inputs["trace_artifact"]
                data = store.artifact(sha)
                suffix = request.inputs.get("trace_format", "json")
                if suffix not in {"json", "pftrace", "pftrace.gz"}:
                    raise ValueError("Unsupported hipprof trace_format")
                path = store.root / "analysis-inputs" / (sha + "." + suffix)
                path.parent.mkdir(parents=True, exist_ok=True)
                if not path.exists():
                    path.write_bytes(data)
                elif digest(path.read_bytes()) != sha:
                    raise FlowError("Materialized trace differs from retained evidence")
                native["trace"] = str(path)
            else:
                native["trace"] = str(_required(request, "trace"))
            if "traceconv_path" in request.inputs:
                native["traceconv_path"] = request.inputs["traceconv_path"]
            path = store.root / "analysis-inputs" / (fingerprint(native) + ".request.json")
            path.parent.mkdir(parents=True, exist_ok=True)
            write_json(path, native)
            report = run_feature(store, _required(request, "project"), path,
                                 timeout=request.inputs.get("timeout", 1800))
        else:
            from ..tracelens import run_report
            kwargs = {key: request.inputs[key] for key in (
                "trace", "trace_pattern", "world_size", "rank", "window", "gpu_arch_json", "timeout") if key in request.inputs}
            report = run_report(store, _required(request, "project"), **kwargs)
        # Preserve the native report and retain the exact raw evidence before
        # exposing a completed scenario result.
        directory = Path(report["output_directory"])
        paths = [Path(row["path"]) for row in report["inputs"]]
        if report.get("gpu_arch"):
            paths.append(Path(report["gpu_arch"]["path"]))
        paths.extend(path for path in directory.rglob("*") if path.is_file())
        expected = {str(Path(row["path"])): row["sha256"] for row in report["inputs"]}
        expected.update({str(Path(row["path"])): row["sha256"] for row in report.get("tables", []) if "sha256" in row})
        expected.update({str(directory / row["path"]): row["sha256"] for row in report.get("artifacts", [])})
        if report.get("gpu_arch"):
            expected[str(Path(report["gpu_arch"]["path"]))] = report["gpu_arch"]["sha256"]
        retained, retention_errors = [], []
        for path in dict.fromkeys(paths):
            try:
                data = path.read_bytes()
            except OSError as exc:
                retention_errors.append({"path": str(path), "reason": str(exc)})
                continue
            retained.append({"path": str(path), "artifact": store.put(data)})
            if str(path) in expected and digest(data) != expected[str(path)]:
                retention_errors.append({"path": str(path), "reason": "File changed before evidence retention"})
        status = {"generated": "complete", "failed": "fail", "incomplete": "incomplete"}.get(report["status"], "unknown")
        if retention_errors:
            status = "fail"
        output = dict(report, native_status=report["status"], status=status, context=context.context,
                      retained_files=retained, retention_errors=retention_errors,
                      evidence=list(dict.fromkeys(row["artifact"] for row in retained)))
        normalized = [row["artifact"] for row in retained if Path(row["path"]) == directory / "tables/normalized.json"]
        if normalized:
            output["normalized_artifact"] = normalized[0]
        return CapabilityResult(self.name, request.action, status, outputs=output,
                                evidence=tuple(output["evidence"]),
                                metadata={"context": context.context, "source_commit": report["source_commit"]})


class QualityAcceptanceCapability:
    name = "quality.accept"

    def actions(self):
        return ("assess", "qualify", "run")

    def run(self, context: CapabilityContext, request: CapabilityRequest) -> CapabilityResult:
        if request.action not in self.actions():
            raise ValueError("Unsupported action for " + self.name + ": " + request.action)
        if request.action == "qualify":
            from .baseline import qualify_baseline
            return qualify_baseline(context, request)
        from ..quality import assess_iteration, compare_loss
        contract = _required(request, "contract")
        baseline, candidate = _required(request, "baseline"), _required(request, "candidate")
        correctness = _required(request, "correctness")
        if not isinstance(contract, dict) or contract.get("context") != context.context:
            return CapabilityResult(self.name, request.action, "incomplete",
                                    outputs={"status": "incomplete", "context": context.context,
                                             "reasons": ["quality-contract-context-mismatch"]})
        provenance = {}
        from ..core import fingerprint
        for key in ("environment", "analysis"):
            if key not in request.inputs:
                continue
            source = request.inputs[key]
            if not isinstance(source, dict) or source.get("context") != context.context:
                return CapabilityResult(self.name, request.action, "incomplete",
                                        outputs={"status": "incomplete", "context": context.context,
                                                 "reasons": [key + "-provenance-context-mismatch"]})
            provenance[key] = {"context": source["context"], "status": source.get("status", "unknown"),
                               "fingerprint": fingerprint(source), "evidence": list(_evidence(source))}
        quality = compare_loss(contract, baseline, candidate)
        performance = assess_iteration(correctness, _required(request, "baseline_times"),
                                       _required(request, "candidate_times"), context.context,
                                       request.inputs.get("max_regression", 0.0))
        performance_status = {"iteration-kept": "pass", "rejected": "fail"}.get(performance["status"], "incomplete")
        statuses = (quality["status"], performance_status)
        status = "fail" if "fail" in statuses else "pass" if statuses == ("pass", "pass") else "incomplete"
        evidence = _evidence(baseline, candidate, correctness, *provenance.values())
        result = {"schema_version": 1, "context": context.context, "status": status,
                  "quality": quality, "performance": performance,
                  "executed": quality.get("executed", 0),
                  "failures": len(quality.get("failures", [])) + int(performance_status == "fail"),
                  "stage_eligible": status == "pass" and quality.get("stage_eligible", False),
                  "production_default": False, "evidence": list(evidence),
                  "provenance": provenance,
                  "limits": "Matched inputs and recorded measurement protocol only; Flow review and stage gates remain required."}
        return CapabilityResult(self.name, request.action, status, outputs=result, evidence=evidence,
                                metadata={"context": context.context})
