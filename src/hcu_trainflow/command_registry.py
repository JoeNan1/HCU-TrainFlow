"""Command registration for the modular capability/Pipeline surface.

The legacy CLI remains compatible, but its modular commands are registered and
dispatched through this small dependency-free boundary.  Importing it does not
load Wiki, TraceLens, or execution integrations.
"""
from __future__ import annotations

from typing import Any, Callable

from .core import Store, read_json


MODULAR_COMMANDS = frozenset({
    "capability-list",
    "capability-run",
    "pipeline-plan",
    "pipeline-run",
    "pipeline-next",
    "pipeline-default",
    "module-catalog",
    "subworkflow-list",
    "module-plan",
    "module-run",
    "profile-list",
    "profile-resolve",
})


def register_modular_commands(subparsers: Any, command: Callable[..., Any]) -> None:
    """Register all independent capability, module and Pipeline entrypoints."""

    command("capability-list")
    command("capability-run", "capability", "file")
    command("pipeline-plan", "file")
    pipeline = command("pipeline-run", "file")
    pipeline.add_argument("--task")
    pipeline.add_argument("--resume", help="Resume only if inputs, context and retained evidence still match")
    command("pipeline-next", "task")
    command("pipeline-default", "task")
    command("module-catalog")
    command("subworkflow-list")
    plan = command("module-plan", "file")
    plan.add_argument("--stage", help="Plan only the modules that serve one flow stage")
    modules = command("module-run", "file")
    modules.add_argument("--task")
    modules.add_argument("--resume", help="Resume only if inputs, context and retained evidence still match")
    command("profile-list")
    command("profile-resolve", "file")


def execute_modular(store: Store, args: Any) -> dict[str, Any] | None:
    """Dispatch one modular command, or return ``None`` for legacy commands."""

    if args.command not in MODULAR_COMMANDS:
        return None
    from . import modular_cli

    if args.command == "capability-list":
        return modular_cli.capability_list()
    if args.command == "capability-run":
        return modular_cli.capability_run(store, args.capability, args.file)
    if args.command == "pipeline-plan":
        return modular_cli.pipeline_plan(args.file)
    if args.command == "pipeline-next":
        return modular_cli.pipeline_next(store, args.task)
    if args.command == "pipeline-default":
        return modular_cli.pipeline_default(store, args.task)
    if args.command == "module-catalog":
        return modular_cli.module_catalog()
    if args.command == "subworkflow-list":
        return modular_cli.subworkflow_list()
    if args.command == "profile-list":
        return modular_cli.profile_list()
    if args.command == "profile-resolve":
        return modular_cli.profile_resolve(args.file)
    if args.command == "module-plan":
        return modular_cli.module_plan(read_json(args.file), getattr(args, "stage", None))
    if args.command == "module-run":
        return modular_cli.module_run(store, read_json(args.file), args.task,
                                      getattr(args, "resume", None))
    return modular_cli.pipeline_run(store, args.file, args.task, getattr(args, "resume", None))

