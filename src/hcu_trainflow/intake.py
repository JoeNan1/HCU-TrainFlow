"""One reusable intake document: validate it, or expand it into task bundles.

A site is stated once (devices, launch commands, contracts, observation policy,
authority envelope) and each request only carries what changes: mode, objective,
acceptance, budget, which contracts and commands it uses. ``check`` answers
"is this still a coherent, authorised document"; ``expand`` turns one entry of
``tasks`` into the bundle the generator writes out.

Neither function executes anything, contacts a site, or decides acceptance on
the human's behalf: the budget a task may use can only narrow the envelope, and
a required profile must still agree with the declared engine/model family.
"""
from __future__ import annotations

import re

from .core import FlowError

INTAKE_KEYS = {"schema_version", "revision", "scope", "site", "source", "paths",
               "contracts", "observation", "authority", "tasks"}
SCOPE_KEYS = {"site", "engine", "model_family", "model"}
SITE_KEYS = {"ssh_target", "container", "cwd", "commands", "devices", "occupancy", "leases"}
SOURCE_KEYS = {"repository", "paths"}
PATHS_KEYS = {"project", "trace", "state_dir"}
CONTRACT_KEYS = {"environment", "quality", "training", "adaptation", "proxy"}
OBSERVATION_KEYS = {"manifest", "policy", "state_dir"}
AUTHORITY_KEYS = {"permissions", "budget", "autonomy"}
TASK_KEYS = {"task_id", "mode", "objective", "acceptance", "plan", "profile",
             "budget", "use", "recovery_owner", "external_job"}
USE_KEYS = {"contracts", "commands"}
PLAN_KEYS = {"max_rounds", "max_stalled_rounds", "full_review_every",
             "max_review_failures", "poll_seconds"}
LEASE_KEYS = {"resource", "owner", "ttl"}

DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _object(value, name, allowed, *, required=()):
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise FlowError(name + " must be an object")
    unknown = set(value) - allowed
    if unknown:
        raise FlowError(name + " has unknown fields: " + ", ".join(sorted(unknown)))
    missing = set(required) - set(value)
    if missing:
        raise FlowError(name + " is missing fields: " + ", ".join(sorted(missing)))
    return value


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise FlowError(name + " must be a nonempty string")
    return value


def load(document):
    """Structural validation; returns the document unchanged."""

    doc = _object(document, "intake", INTAKE_KEYS, required={"schema_version", "scope", "site", "tasks"})
    if doc["schema_version"] != 1:
        raise FlowError("Unsupported intake schema version")
    if not DATE.match(_text(doc.get("revision"), "revision")):
        raise FlowError("revision must be an ISO date (YYYY-MM-DD)")
    scope = _object(doc.get("scope"), "scope", SCOPE_KEYS, required={"engine", "model_family"})
    for key, value in scope.items():
        _text(value, "scope." + key)

    site = _object(doc.get("site"), "site", SITE_KEYS, required={"commands", "devices"})
    commands = _object(site.get("commands"), "site.commands", set(site.get("commands") or {}))
    for name, command in commands.items():
        _object(command, "site.commands." + str(name),
                {"argv", "env", "timeout_seconds", "basis", "cwd", "activation"})
    devices = site.get("devices")
    if not isinstance(devices, list) or not devices:
        raise FlowError("At least one admitted device is required")
    for device in devices:
        _object(device, "device", {"node", "device", "identity", "idle_memory_bytes",
                                   "memory_tolerance_bytes", "max_utilization_pct", "basis"})

    for name in ("source", "paths"):
        if name in doc:
            _object(doc[name], name, {"source": SOURCE_KEYS, "paths": PATHS_KEYS}[name])
    _object(doc.get("contracts"), "contracts", CONTRACT_KEYS)
    _object(doc.get("observation"), "observation", OBSERVATION_KEYS)
    _object(doc.get("authority"), "authority", AUTHORITY_KEYS)

    tasks = doc.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise FlowError("intake needs at least one task")
    for task in tasks:
        _object(task, "task", TASK_KEYS, required={"task_id", "mode", "objective", "acceptance"})
        _object(task.get("plan"), "task.plan", PLAN_KEYS)
        _object(task.get("use"), "task.use", USE_KEYS)
    return doc


def _expected_leases(devices):
    return {"hcu:" + str(device.get("node")) + ":" + str(device.get("identity")) for device in devices}


def lease_resources(devices, entries):
    """Resolve ``{resource, owner, ttl}`` entries to admitted lease resources.

    A bare node name is accepted only when exactly one admitted device sits on
    it, so an ambiguous shorthand cannot silently widen the reservation.
    """

    admitted = _expected_leases(devices)
    by_node = {}
    for device in devices:
        by_node.setdefault(device.get("node"), []).append(device)
    resolved = []
    for entry in entries:
        entry = _object(entry, "lease", LEASE_KEYS, required=LEASE_KEYS)
        resource = _text(entry["resource"], "lease.resource")
        owner = _text(entry["owner"], "lease.owner")
        ttl = entry["ttl"]
        if isinstance(ttl, bool) or not isinstance(ttl, int) or ttl <= 0:
            raise FlowError("lease.ttl must be a positive integer number of seconds")
        if resource in admitted:
            resolved.append(resource)
            continue
        match = by_node.get(resource) or []
        if len(match) == 1:
            resolved.append("hcu:" + str(match[0].get("node")) + ":" + str(match[0].get("identity")))
            continue
        raise FlowError("Lease resource must match an admitted device: " + resource)
    if len(set(resolved)) != len(resolved):
        raise FlowError("Lease resources must be unique")
    if not owner:  # pragma: no cover - _text already rejects empty owners
        raise FlowError("Lease owner must be nonempty")
    return resolved


def _task_context(scope, source):
    context = {key: value for key, value in scope.items()}
    if source.get("repository"):
        context["source"] = source["repository"]
    return context


def _plan(task):
    from . import flow

    document = dict(task.get("plan") or {})
    document["acceptance"] = task["acceptance"]
    return flow.validate_plan(document)


def _spec(document, task, autonomy):
    scope = document["scope"]
    spec = {
        "schema_version": 1,
        "task_id": task["task_id"],
        "mode": task["mode"],
        "objective": task["objective"],
        "context": _task_context(scope, document.get("source") or {}),
        "permissions": list((document.get("authority") or {}).get("permissions") or []),
        "budget": dict(task.get("budget") or (document.get("authority") or {}).get("budget") or {}),
    }
    for key in ("recovery_owner", "external_job", "profile"):
        if key in task:
            spec[key] = task[key]
    if autonomy is not None:
        spec["autonomy"] = autonomy
    return spec


def _uses(document, task):
    """Which contracts and commands this task claims to use (default: all)."""

    use = task.get("use") or {}
    for key in ("contracts", "commands"):
        if key in use and (not isinstance(use[key], list)
                           or any(not isinstance(name, str) or not name.strip() for name in use[key])):
            raise FlowError("task.use." + key + " must be a list of names")
    contracts = use.get("contracts")
    if contracts is None:
        contracts = sorted((document.get("contracts") or {}).keys())
    commands = use.get("commands")
    if commands is None:
        commands = sorted((document.get("site") or {}).get("commands") or {})
    return {"contracts": list(contracts), "commands": list(commands)}


def check(document):
    """Return blocking issues and advisory warnings; never mutates anything."""

    from . import flow
    from .core import validate_spec

    doc = load(document)
    issues, warnings = [], []
    authority = doc.get("authority") or {}
    ceiling = authority.get("budget") or {}
    contracts = doc.get("contracts") or {}
    site = doc["site"]
    commands = site.get("commands") or {}
    devices = site.get("devices") or []
    if not isinstance(authority.get("autonomy"), (dict, type(None))):
        issues.append("authority.autonomy must be an object when present")

    identities = [str(device.get("identity")) for device in devices]
    if len(set(identities)) != len(identities):
        issues.append("devices must have unique identities")
    for device in devices:
        missing = {"node", "device", "identity", "basis"} - set(device)
        if missing:
            issues.append("device is missing fields: " + ", ".join(sorted(missing)))

    if not ceiling:
        warnings.append("authority.budget is absent; each task must carry its own ceiling")

    seen = set()
    for task in doc["tasks"]:
        name = str(task.get("task_id"))
        if name in seen:
            issues.append("duplicate task id: " + name)
        seen.add(name)
        try:
            spec = _spec(doc, task, authority.get("autonomy"))
            validate_spec(spec)
            _plan(task)
            use = _uses(doc, task)
        except FlowError as exc:
            issues.append(name + ": " + str(exc))
            continue

        budget = spec.get("budget") or {}
        for key, value in (ceiling or {}).items():
            if key in budget and budget[key] > value:
                issues.append(name + ": budget." + key + " exceeds the authority envelope")
        unknown = sorted(set(use["contracts"]) - set(contracts))
        if unknown:
            issues.append(name + ": uses unknown contracts: " + ", ".join(unknown))
        unknown = sorted(set(use["commands"]) - set(commands))
        if unknown:
            issues.append(name + ": uses unknown commands: " + ", ".join(unknown))
        try:
            lease_resources(devices, site.get("leases") or [])
        except FlowError as exc:
            issues.append(name + ": " + str(exc))
        if task.get("profile"):
            from . import catalog
            try:
                catalog.resolve_profile({**spec["context"], "mode": spec["mode"]},
                                        requested=task["profile"]["id"])
            except Exception as exc:  # ModuleContractError carries the conflict
                issues.append(name + ": " + str(exc))

    for name, contract in contracts.items():
        if not isinstance(contract, dict):
            issues.append("contracts." + name + " must be an object")
            continue
        required = {"quality": {"atol", "rtol", "min_steps", "aggregation", "tolerance_basis"},
                    "training": {"expected_steps", "steady_start"},
                    "adaptation": {"components", "atol"},
                    "proxy": {"full", "candidate"}}.get(name)
        missing = sorted((required or set()) - set(contract))
        if missing:
            warnings.append("contracts." + name + " is missing: " + ", ".join(missing))

    if site.get("leases"):
        warnings.append("leases are reservations, not permanent grants: re-acquire them per run")
    return {"status": "attention" if issues else "pass", "issues": issues,
            "warnings": warnings, "revision": doc["revision"],
            "tasks": [str(task["task_id"]) for task in doc["tasks"]],
            "contracts": sorted(contracts), "commands": sorted(commands)}


def expand(document, task_id=None):
    """Turn one task entry into generator inputs; raises on any issue."""

    result = check(document)
    if result["issues"]:
        raise FlowError(result["issues"][0])
    doc = load(document)
    authority = doc.get("authority") or {}
    autonomy = authority.get("autonomy")
    site = doc["site"]
    wanted = [task for task in doc["tasks"]
              if task_id is None or str(task["task_id"]) == str(task_id)]
    if not wanted:
        raise FlowError("Unknown task id: " + str(task_id))
    leases = site.get("leases") or []
    resources = lease_resources(site.get("devices") or [], leases)
    bundles = []
    for task in wanted:
        use = _uses(doc, task)
        block = {key: site.get(key) for key in ("ssh_target", "container", "cwd", "occupancy")}
        block["commands"] = {name: site["commands"][name] for name in use["commands"]}
        block["devices"] = site.get("devices")
        block["leases"] = resources
        spec = _spec(doc, task, autonomy)
        bundles.append({
            # The payload omits schema_version and autonomy: the generator adds
            # both back, exactly as it does for a site contract.
            "task": {key: value for key, value in spec.items()
                     if key not in {"schema_version", "autonomy"}},
            "autonomy": autonomy,
            "plan": _plan(task),
            "site": block,
            "contracts": {name: (doc.get("contracts") or {}).get(name) for name in use["contracts"]},
            "lease_entries": [dict(entry) for entry in leases],
            "observation": dict(doc.get("observation") or {}),
            "paths": dict(doc.get("paths") or {}),
            "source": dict(doc.get("source") or {}),
        })
    return bundles
