"""Persistent capability execution without a dependency on command parsing."""
from __future__ import annotations

from dataclasses import replace
from collections.abc import Iterable
import glob
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from ..capabilities import default_registry
from ..core import FlowError, PipelineContextConflict, Store, fingerprint
from ..kernel import CapabilityContext, CapabilityRequest, CapabilityResult, PipelinePlan, PipelineRunner


def _evidence(value):
    """Find declared evidence in nested comparison records, not arbitrary strings."""
    found = set()
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key == "evidence":
                if not isinstance(item, (list, tuple)) or any(not isinstance(x, str) or not x for x in item):
                    raise FlowError("Evidence must contain retained artifact IDs")
                found.update(item)
            else:
                found.update(_evidence(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            found.update(_evidence(item))
    return found


def _file_hash(path):
    hasher = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


class RuntimeService:
    """Run standalone or task-bound requests with identical evidence rules.

    Task binding is explicit in ``CapabilityContext.from_task`` metadata. A
    standalone context's task_id is only a caller label, never a synthetic Task.
    ``run_capability`` returns its result fields plus run_id/artifacts/reports.
    """

    def __init__(self, store: Store, registry=None):
        self.store = store
        self.registry = registry if registry is not None else default_registry()

    def _task(self, context):
        if context.workspace.resolve() != self.store.root.resolve():
            raise FlowError("Capability workspace must match the service Store")
        if "spec" not in context.metadata:
            # Full-task callers must use from_task, rather than drop their gates.
            if context.mode == "full":
                raise FlowError("Full-task execution requires a task-bound context")
            return None
        task = self.store.task(context.task_id)
        if (task["context"] != context.context or
                task["revision"] != context.metadata.get("revision", task["revision"])):
            raise PipelineContextConflict("Task context or revision changed before Pipeline")
        if task["state"] in {"completed", "cancelled", "paused", "blocked", "failed"}:
            raise FlowError("Current Flow decision does not permit Pipeline execution: " + task["state"])
        with self.store.db() as db:
            has_flow = db.execute("SELECT 1 FROM flows WHERE task=?", (task["id"],)).fetchone()
        # Standalone environment/analysis Tasks may use the existing execution
        # controller without creating a full collaborative training Flow.
        if not has_flow and task["spec"]["mode"] != "full":
            return task
        from ..kernel.flow_bridge import pipeline_next
        projected = pipeline_next(self.store, task["id"])
        if projected["action"] not in {"work", "repair"}:
            raise FlowError("Current Flow decision does not permit Pipeline execution: " + projected["action"])
        return task

    def _check_context(self, task):
        if task:
            current = self.store.task(task["id"])
            if (current["context"], current["revision"]) != (task["context"], task["revision"]):
                raise PipelineContextConflict("Task context or revision changed while running Pipeline")

    def _identity(self, plan, context, inputs, task):
        files = {}
        def visit(value):
            if isinstance(value, Mapping):
                for key, item in value.items():
                    if key == "trace_pattern" and isinstance(item, str):
                        for path in sorted(glob.glob(item)):
                            if Path(path).is_file():
                                files[str(Path(path).resolve())] = _file_hash(path)
                    visit(item)
            elif isinstance(value, (list, tuple)):
                for item in value:
                    visit(item)
            elif isinstance(value, (str, Path)):
                # Hash file-backed inputs even when the pathname is unchanged.
                try:
                    path = Path(value)
                    if path.is_file():
                        files[str(path.resolve())] = _file_hash(path)
                except (OSError, ValueError):
                    pass
        visit(inputs)
        visit(plan.to_dict())
        versions = {}
        for step in plan.steps:
            capability = self.registry.resolve(step.capability)
            module = __import__(type(capability).__module__, fromlist=["__file__"])
            source = getattr(module, "__file__", None)
            versions[step.capability] = {"version": getattr(capability, "version", "1"),
                                         "implementation": _file_hash(source) if source else None}
        from .. import __version__
        package_root = Path(__file__).resolve().parents[1]
        implementation = {str(p.relative_to(package_root)): _file_hash(p)
                          for p in sorted(package_root.rglob("*.py"))}
        # Include reviewed tool revisions/local bindings, without reading Git
        # credentials or hashing private repository configuration.
        tool_bindings = {}
        if any(step.capability == "profiling.tracelens" for step in plan.steps):
            from ..dependencies import require_checkout
            projects = [inputs.get("project")]
            projects += [step.inputs.get("project", step.config.get("project")) for step in plan.steps
                         if step.capability == "profiling.tracelens"]
            for project in projects:
                if project:
                    checkout, dependency = require_checkout(project, "tracelens")
                    tool_bindings[str(Path(project).resolve())] = {"path": str(checkout), "commit": dependency["commit"]}
        return fingerprint({"runtime": 2, "package": __version__, "plan": plan.to_dict(),
                            "inputs": inputs, "files": files, "capabilities": versions,
                            "implementation": implementation, "tools": tool_bindings,
                            "caller": context.task_id, "context": context.context,
                            "mode": context.mode, "task": task["id"] if task else None,
                            "revision": task["revision"] if task else 0})

    def _invoke(self, context, request):
        capability = self.registry.resolve(request.capability)
        if request.action not in capability.actions():
            raise FlowError("Unsupported action for " + request.capability + ": " + request.action)
        result = capability.run(context, request)
        if not isinstance(result, CapabilityResult) or (result.capability, result.action) != (request.capability, request.action):
            raise FlowError("Capability returned an invalid result identity")
        outputs = dict(result.outputs)
        if outputs.get("context", context.context) != context.context:
            raise FlowError("Capability result belongs to another context")
        evidence = set(result.evidence) | _evidence(outputs) | _evidence(request.inputs)
        gaps = []
        verified = []
        for sha in sorted(evidence):
            try:
                self.store.artifact(sha)
                verified.append(sha)
            except (FlowError, OSError):
                gaps.append("missing-or-corrupt-evidence:" + sha)
        required_evidence = request.capability in {
            "environment.check", "profiling.tracelens", "quality.loss", "quality.iteration", "quality.accept",
            "artifact.collect", "training.summarize",
        }
        if required_evidence and not verified:
            gaps.append("missing-raw-evidence")
        status = result.status
        if gaps and status in {"pass", "complete"}:
            status = "incomplete"
        outputs.setdefault("context", context.context)
        # Keep native reports' statuses (e.g. iteration-kept) for consumers.
        if gaps:
            outputs["evidence_gaps"] = gaps
            if outputs.get("status") in {"pass", "complete"}:
                outputs["status"] = status
        return replace(result, status=status, outputs=outputs, evidence=tuple(verified))

    @staticmethod
    def _volatile(step):
        return (step.capability in {"environment.occupancy", "scale.admission", "observation.collect"}
                or (step.capability == "execution.command" and step.action == "run")
                or (step.capability == "environment.check" and step.action == "collect"))

    def run_capability(self, request: CapabilityRequest, context: CapabilityContext,
                       resume_run_id: str | None = None) -> dict[str, Any]:
        plan = PipelinePlan.from_dict({"name": "capability:" + request.capability, "steps": [{
            "id": "result", "capability": request.capability, "action": request.action,
            "inputs": dict(request.inputs), "config": dict(request.config),
        }]})
        output = self.run_pipeline(plan, context, {}, resume_run_id=resume_run_id)
        result = dict(output["steps"]["result"])
        result.update({key: output[key] for key in ("run_id", "request_artifact", "artifacts", "reports", "resumed")})
        return result

    def run_pipeline(self, plan: PipelinePlan, context: CapabilityContext,
                     inputs: Mapping[str, Any] | None = None,
                     resume_run_id: str | None = None,
                     volatile_steps: Iterable[str] | None = None) -> dict[str, Any]:
        # Validate Python-constructed plans as strictly as JSON plans.
        plan = PipelinePlan.from_dict(plan.to_dict())
        inputs = dict(inputs or {})
        task = self._task(context)
        identity = self._identity(plan, context, inputs, task)
        run_id = "pipeline-" + identity
        if resume_run_id is not None:
            old = self.store.pipeline_state(resume_run_id)
            if old.get("input_identity") != identity or resume_run_id != run_id:
                raise FlowError("Pipeline resume identity changed or legacy run lacks an input fingerprint; create a new run")
        # OS lock is released on controller death; unlike a TTL it cannot expire
        # during a long capability. Execution retains its own Operation lock.
        from ..command_group import _controller_lock
        with _controller_lock(self.store, "runtime-" + identity):
            task = self._task(context)
            if self._identity(plan, context, inputs, task) != identity:
                raise PipelineContextConflict("Pipeline input identity changed before dispatch")
            request_artifact = self.store.put(json.dumps({
                "schema_version": 1, "kind": "pipeline-request", "pipeline": plan.to_dict(),
                "inputs": inputs, "context": context.context, "caller": context.task_id,
                "task": task["id"] if task else None, "revision": task["revision"] if task else 0,
                "input_identity": identity,
            }, sort_keys=True, ensure_ascii=False, allow_nan=False).encode())
            self.store.pipeline_start(task["id"] if task else None, run_id, plan.name,
                                      plan.to_dict(), context.context,
                                      task["revision"] if task else 0, input_identity=identity)
            state = self.store.pipeline_state(run_id)
            # A declared module contract can replace the legacy whitelist for
            # the steps it names; the legacy rule stays for older plans.
            declared = set(volatile_steps or ()) & {step.id for step in plan.steps}
            volatile = {step.id for step in plan.steps if self._volatile(step)} | declared
            for step in plan.ordered_steps():
                if volatile.intersection(step.depends_on):
                    volatile.add(step.id)
            prior = {}
            for row in state["steps"]:
                # Verify cached evidence, including report and result envelopes.
                if row["status"] in {"pass", "complete"}:
                    for sha in [row["artifact"], row["report"], *row["result"].get("evidence", [])]:
                        if sha:
                            self.store.artifact(sha)
                    if row["step"] not in volatile:
                        prior[row["step"]] = CapabilityResult.from_dict(row["result"])
            for step in plan.ordered_steps():
                if any(dependency not in prior for dependency in step.depends_on):
                    prior.pop(step.id, None)
            if state["status"] == "complete" and len(prior) == len(plan.steps):
                return {**state["result"], **self._view(state), "resumed": True}
            self.store.pipeline_reopen(run_id)

            def persist(step, result):
                self._check_context(task)
                if self._identity(plan, context, inputs, task) != identity:
                    raise PipelineContextConflict("Pipeline input files changed during execution")
                envelope = {"schema_version": 1, "kind": "pipeline-step", "run": run_id,
                            "task": task["id"] if task else None, "step": step.id,
                            "context": context.context, "revision": task["revision"] if task else 0,
                            "request_artifact": request_artifact,
                            "result": result.to_dict()}
                artifact = self.store.put(json.dumps(envelope, sort_keys=True, ensure_ascii=False, allow_nan=False).encode())
                self.store.pipeline_step(run_id, step.id, step.capability, step.action, result.status,
                                         result.to_dict(), artifact)

            def register_reports(results):
                for step in plan.ordered_steps():
                    result = results[step.id]
                    kind = step.config.get("report_kind")
                    if kind is None or result.status == "blocked" or not task:
                        continue
                    if not isinstance(kind, str) or not kind.strip():
                        raise FlowError("Pipeline report_kind must be a nonempty string")
                    self._check_context(task)
                    if self._identity(plan, context, inputs, task) != identity:
                        raise PipelineContextConflict("Pipeline input files changed before report registration")
                    body = dict(result.outputs)
                    if body.get("context") != context.context or body.get("status") != result.status:
                        raise FlowError("Pipeline report context/status does not match capability result")
                    # Evidence gaps are retained as results; they cannot grant a
                    # report by substituting the generated summary as raw data.
                    if body.get("evidence_gaps"):
                        continue
                    evidence = body.get("evidence")
                    if not isinstance(evidence, list) or not evidence:
                        # A step that produced no evidence cannot grant a report.
                        # Retain the incomplete step and record why registration
                        # was skipped instead of aborting the whole run.
                        with self.store.db() as db:
                            self.store.event(db, task["id"], "pipeline-report-skipped",
                                             {"run": run_id, "step": step.id, "kind": kind,
                                              "reason": "no-retained-evidence"})
                        continue
                    for sha in evidence:
                        self.store.artifact(sha)
                    rows = {r["step"]: r for r in self.store.pipeline_state(run_id)["steps"]}
                    artifact = rows[step.id]["artifact"]
                    body["evidence"] = list(dict.fromkeys([*evidence, artifact]))
                    report = self.store.report(task["id"], kind, body,
                                               expected_revision=task["revision"],
                                               agent_authored=False)["artifact"]
                    self.store.pipeline_step(run_id, step.id, step.capability, step.action, result.status,
                                             result.to_dict(), artifact, report)

            def start(step):
                persist(step, CapabilityResult(step.capability, step.action, "incomplete",
                        message="Step started; reconcile any original Operation before retrying an interrupted execution",
                        metadata={"pending": True}))

            try:
                result = PipelineRunner(self.registry).run(plan, context, inputs, prior_results=prior,
                        on_start=start, on_result=persist, invoke=self._invoke)
                self._check_context(task)
                if self._identity(plan, context, inputs, task) != identity:
                    raise PipelineContextConflict("Pipeline input files changed during execution")
                register_reports(result.steps)
                finish = {"complete": "complete", "incomplete": "incomplete", "fail": "failed"}[result.status]
                result_document = {**result.to_dict(), "request_artifact": request_artifact}
                self.store.pipeline_finish(run_id, finish, result_document)
            except PipelineContextConflict as exc:
                self.store.pipeline_finish(run_id, "conflicted", {"status": "conflicted", "message": str(exc)})
                raise
            except BaseException as exc:
                try:
                    self.store.pipeline_finish(run_id, "interrupted" if not isinstance(exc, Exception) else "failed",
                                               {"status": "interrupted" if not isinstance(exc, Exception) else "failed", "message": str(exc)})
                except PipelineContextConflict:
                    self.store.pipeline_finish(run_id, "conflicted", {"status": "conflicted", "message": str(exc)})
                raise
            return {**result_document, **self._view(self.store.pipeline_state(run_id)),
                    "resumed": bool(state["steps"])}

    @staticmethod
    def _view(state):
        return {"run_id": state["id"],
                "artifacts": {row["step"]: row["artifact"] for row in state["steps"] if row["artifact"]},
                "reports": {row["step"]: row["report"] for row in state["steps"] if row["report"]}}
