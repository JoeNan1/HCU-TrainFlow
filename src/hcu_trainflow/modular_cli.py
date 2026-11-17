"""CLI entrypoints for independent capabilities and declarative pipelines."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .capabilities import default_registry
from .services import RuntimeService
from .core import FlowError, Store, read_json
from .kernel import (
    CapabilityContext,
    CapabilityRequest,
    PipelinePlan,
    full_pipeline_for_state,
    pipeline_next as flow_pipeline_next,
)


def capability_list() -> dict[str, Any]:
    registry = default_registry()
    return {"status": "pass", "capabilities": list(registry.names()),
            "actions": {name: list(registry.resolve(name).actions()) for name in registry.names()}}


def _context(store: Store, document: dict[str, Any], task_id: str | None = None) -> CapabilityContext:
    if task_id:
        return CapabilityContext.from_task(store.task(task_id), store.root)
    context = document.get("context")
    if not isinstance(context, str) or not context.strip():
        raise FlowError("Standalone capability requests require a string context")
    return CapabilityContext(task_id=document.get("task_id", "standalone"), context=context,
                             workspace=store.root, mode=document.get("mode", "standalone"))


def capability_run(store: Store, capability: str, request_path: str) -> dict[str, Any]:
    document = read_json(request_path)
    if not isinstance(document, dict):
        raise FlowError("Capability request must be a JSON object")
    task_id = document.get("task_id")
    context = _context(store, document, task_id)
    payload = {key: value for key, value in document.items()
               if key not in {"task_id", "context", "mode"}}
    request = CapabilityRequest.from_dict(payload, capability=capability)
    return RuntimeService(store).run_capability(request, context)


def _pipeline_document(path: str) -> tuple[PipelinePlan, dict[str, Any], dict[str, Any]]:
    document = read_json(path)
    if not isinstance(document, dict):
        raise FlowError("Pipeline document must be a JSON object")
    raw_plan = document.get("pipeline", document)
    plan = PipelinePlan.from_dict(raw_plan)
    context = document.get("context", {})
    inputs = document.get("inputs", {})
    if not isinstance(context, dict) or not isinstance(inputs, dict):
        raise FlowError("Pipeline context and inputs must be objects")
    return plan, context, inputs


def pipeline_plan(path: str) -> dict[str, Any]:
    plan, _, _ = _pipeline_document(path)
    return {"status": "pass", "pipeline": plan.to_dict()}


def pipeline_run(store: Store, path: str, task_id: str | None = None,
                 resume_run_id: str | None = None) -> dict[str, Any]:
    plan, document_context, inputs = _pipeline_document(path)
    if task_id:
        context = CapabilityContext.from_task(store.task(task_id), store.root)
    else:
        value = document_context.get("context")
        if not isinstance(value, str) or not value.strip():
            raise FlowError("Standalone pipeline requires context.context")
        context = CapabilityContext(task_id=document_context.get("task_id", "pipeline"), context=value,
                                    workspace=store.root, mode=document_context.get("mode", "standalone"))
    return RuntimeService(store).run_pipeline(plan, context, inputs, resume_run_id=resume_run_id)


def pipeline_next(store: Store, task_id: str) -> dict[str, Any]:
    """Project the existing Flow decision into the modular Pipeline surface."""

    return flow_pipeline_next(store, task_id)


def module_catalog() -> dict[str, Any]:
    from . import catalog
    catalog.validate_catalog()
    subworkflows = {}
    for name, entry in catalog.subworkflows().items():
        subworkflows[name] = {**entry.to_dict(),
                              "interface": catalog.interface(entry.modules)}
    return {"status": "pass",
            "modules": [module.to_dict() for module in catalog.modules()],
            "aliases": dict(catalog.aliases()),
            "subworkflows": subworkflows,
            "subworkflow_aliases": dict(catalog.SUBWORKFLOW_ALIASES),
            # Compatibility key: the functional layer used to be called presets.
            "presets": subworkflows}


def subworkflow_list() -> dict[str, Any]:
    from . import catalog
    return {"status": "pass", "subworkflows": [
        {**entry.to_dict(), "interface": catalog.interface(entry.modules)}
        for entry in catalog.subworkflows().values()]}


def profile_list() -> dict[str, Any]:
    from . import catalog
    return {"status": "pass", "profiles": [
        {**entry.to_dict(), "resolved_modules": list(entry.module_ids()),
         "gates": catalog.derived_gates(entry),
         "reading": catalog.route_surface(entry.module_ids())}
        for entry in catalog.profiles().values()]}


def profile_resolve(path: str) -> dict[str, Any]:
    from . import catalog
    document = read_json(path)
    if not isinstance(document, dict):
        raise FlowError("Profile context must be a JSON object")
    requested = document.get("requested")
    context = document.get("context", document)
    if not isinstance(context, dict):
        raise FlowError("Profile context must be an object")
    if requested is not None and not isinstance(requested, str):
        raise FlowError("Requested profile must be a profile id")
    return catalog.resolve_profile(context, requested)


def module_plan(document: dict[str, Any], stage: str | None = None) -> dict[str, Any]:
    from . import catalog
    if stage is not None:
        if document.get("stage") not in (None, stage):
            raise FlowError("Stage declared twice with different values")
        document = {**document, "stage": stage}
    built = catalog.build_plan(document=document)
    if built["gates"] is not None:
        built["flow_gates"] = catalog.compare_to_flow(built["gates"])
    return built


def module_run(store: Store, document: dict[str, Any], task_id: str | None = None,
               resume_run_id: str | None = None) -> dict[str, Any]:
    from . import catalog
    document = dict(document)
    # Binding a Task is what makes task-bound modules (evidence registration,
    # execution cards) legitimate; hardware/lease must still be declared.
    capabilities = set(document.get("capabilities") or ())
    if task_id:
        capabilities.add("task-bound")
    built = catalog.build_plan(document={**document, "capabilities": sorted(capabilities)})
    if built["status"] != "pass":
        raise FlowError("Module set cannot run: " + ", ".join(
            sorted({problem["kind"] for problem in built["problems"]})))
    if task_id:
        context = CapabilityContext.from_task(store.task(task_id), store.root)
    else:
        value = (document.get("context") or {})
        if not isinstance(value, dict) or not isinstance(value.get("context"), str):
            raise FlowError("Standalone module run requires context.context")
        context = CapabilityContext(task_id=value.get("task_id", "modules"), context=value["context"],
                                    workspace=store.root, mode=value.get("mode", "standalone"))
    plan = PipelinePlan.from_dict({key: built["plan"][key] for key in ("schema_version", "name", "steps")})
    result = RuntimeService(store).run_pipeline(plan, context, document.get("inputs") or {},
                                               resume_run_id=resume_run_id,
                                               volatile_steps=built["volatile"])
    return {**result, "modules": built["modules"], "gates": built["gates"]}


def pipeline_default(store: Store, task_id: str) -> dict[str, Any]:
    """Return the current gated stage of the default full workflow."""

    projected = flow_pipeline_next(store, task_id)
    if projected["state"] not in {"prepared", "environment_checked", "baseline_validated",
                                  "profiling", "optimizing", "scale_ready", "training"}:
        return {"status": projected["gate"]["status"], "flow": projected}
    return {"status": "pass" if projected["action"] in {"work", "repair"} else projected["gate"]["status"],
            "flow": projected, "pipeline": full_pipeline_for_state(projected["state"]).to_dict()}
