"""Capabilities for catalog modules that had no implementation yet.

Every class here is a thin, deterministic adapter: it consumes declared inputs
(or retained artifacts) and returns a structured result with the evidence it
actually retained.  None of them launches a model, invents measurements, or
turns a summary into a stage verdict; the Flow gates stay authoritative.
"""
from __future__ import annotations

import json
import math
import statistics

from ..core import FlowError, Store, fingerprint
from ..kernel.contracts import CapabilityContext, CapabilityRequest, CapabilityResult


def _required(request: CapabilityRequest, name: str):
    if name not in request.inputs:
        raise ValueError("Missing capability input: " + name)
    return request.inputs[name]


def _positive_seconds(values, name):
    if not isinstance(values, list) or not values:
        raise ValueError(name + " must be a nonempty array")
    numbers = []
    for value in values:
        if type(value) is bool or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(name + " must contain finite positive seconds")
        numbers.append(float(value))
    return numbers


def _relative_mad(values):
    median = statistics.median(values)
    return statistics.median(abs(value - median) for value in values) / median if median else None


def _retained_evidence(store, request):
    """Verify caller-named raw artifacts; a summary never becomes the evidence."""

    values = request.inputs.get("evidence") or []
    if not isinstance(values, list) or any(not isinstance(x, str) or not x for x in values):
        raise ValueError("evidence must be a list of retained artifact IDs")
    retained, gaps = [], []
    for sha in values:
        try:
            store.artifact(sha)
            retained.append(sha)
        except (FlowError, OSError):
            gaps.append("missing-or-corrupt-evidence:" + sha)
    return retained, gaps


def _union_seconds(spans):
    """Union length of ``[[start, end], ...]`` in seconds; intervals are ns."""

    merged, busy = [], 0
    for start, end in sorted(spans):
        if end < start:
            raise ValueError("Interval end precedes its start")
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    for start, end in merged:
        busy += end - start
    return busy / 1e9, merged


def _overlap_seconds(left, right):
    overlap, i, j = 0, 0, 0
    while i < len(left) and j < len(right):
        start = max(left[i][0], right[j][0])
        end = min(left[i][1], right[j][1])
        if end > start:
            overlap += end - start
        if left[i][1] < right[j][1]:
            i += 1
        else:
            j += 1
    return overlap / 1e9


class StdoutJsonCapability:
    """Interpret a retained stdout artifact as structured measurements."""

    name = "execution.stdout-json"

    def actions(self) -> tuple[str, ...]:
        return ("parse", "run")

    def run(self, context: CapabilityContext, request: CapabilityRequest) -> CapabilityResult:
        if request.action not in self.actions():
            raise ValueError("Unsupported action for " + self.name + ": " + request.action)
        sha = _required(request, "stdout_artifact")
        if not isinstance(sha, str) or not sha:
            raise ValueError("stdout_artifact must be a retained artifact ID")
        store = Store(context.workspace)
        raw = store.artifact(sha)
        try:
            document = json.loads(raw)
        except ValueError as exc:
            return CapabilityResult(self.name, request.action, "incomplete",
                                    outputs={"context": context.context, "status": "incomplete",
                                             "parsing_error": "stdout is not JSON: " + str(exc),
                                             "evidence": [sha]}, evidence=(sha,))
        if not isinstance(document, (dict, list)):
            return CapabilityResult(self.name, request.action, "incomplete",
                                    outputs={"context": context.context, "status": "incomplete",
                                             "parsing_error": "stdout JSON must be an object or array",
                                             "evidence": [sha]}, evidence=(sha,))
        return CapabilityResult(
            self.name, request.action, "complete",
            outputs={"context": context.context, "status": "complete", "document": document,
                     "source_artifact": sha, "evidence": [sha]}, evidence=(sha,),
            metadata={"context": context.context, "source_artifact": sha})


class SourceTransferCapability:
    """Source snapshot/materialize/bundle over the existing transfer helpers."""

    name = "source.transfer"

    def actions(self) -> tuple[str, ...]:
        return ("snapshot", "materialize", "bundle", "run")

    def run(self, context: CapabilityContext, request: CapabilityRequest) -> CapabilityResult:
        if request.action not in self.actions():
            raise ValueError("Unsupported action for " + self.name + ": " + request.action)
        from .. import execution
        store = Store(context.workspace)
        if request.action == "snapshot":
            paths = _required(request, "paths")
            if not isinstance(paths, list) or any(not isinstance(path, str) for path in paths):
                raise ValueError("paths must be a list of repository-relative paths")
            result = execution.snapshot(store, _required(request, "repository"), paths)
            evidence = tuple(sorted({info["sha256"] for info in result["files"].values()}))
            status = "complete"
        else:
            snapshot_id = _required(request, "snapshot_id")
            destination = _required(request, "destination")
            action = execution.materialize if request.action == "materialize" else execution.bundle
            result = action(store, snapshot_id, destination)
            result = dict(result, context=context.context)
            evidence = ()
            status = "complete"
        output = {"context": context.context, "status": status, **result,
                  "evidence": list(evidence)}
        return CapabilityResult(self.name, request.action, status, outputs=output,
                                evidence=evidence, metadata={"context": context.context})


class ResourceLeaseCapability:
    """Lease acquisition/renewal/release against the existing Store lease table."""

    name = "resource.lease"

    def actions(self) -> tuple[str, ...]:
        return ("acquire", "renew", "release", "run")

    def run(self, context: CapabilityContext, request: CapabilityRequest) -> CapabilityResult:
        if request.action not in self.actions():
            raise ValueError("Unsupported action for " + self.name + ": " + request.action)
        store = Store(context.workspace)
        if request.action in {"renew", "release"}:
            lease = _required(request, "lease")
            if not isinstance(lease, dict) or not {"resource", "owner", "token"} <= set(lease):
                raise ValueError("lease must carry resource, owner and token")
            result = store.renew(lease) if request.action == "renew" else store.release(lease)
            status = "complete"
        else:
            result = store.lease(_required(request, "resource"), _required(request, "owner"),
                                 request.inputs.get("ttl", 300))
            status = "complete"
        return CapabilityResult(self.name, request.action, status,
                                outputs={"context": context.context, "status": status,
                                         "lease": result},
                                metadata={"context": context.context})


class CommunicationCapability:
    """Expose communication/overlap accounting from declared intervals.

    The intervals must come from a profiler run (or an equivalent measured
    record); this capability only performs deterministic union maths.
    """

    name = "profiling.communication"

    def actions(self) -> tuple[str, ...]:
        return ("account", "run")

    def run(self, context: CapabilityContext, request: CapabilityRequest) -> CapabilityResult:
        if request.action not in self.actions():
            raise ValueError("Unsupported action for " + self.name + ": " + request.action)
        document = _required(request, "intervals")
        if isinstance(document, dict):
            devices = document.get("devices")
        else:
            devices = document
        if not isinstance(devices, list) or not devices:
            raise ValueError("intervals must contain a nonempty devices array")
        rows, reasons = [], []
        for entry in devices:
            if not isinstance(entry, dict):
                raise ValueError("Each device entry must be an object")
            compute = entry.get("compute") or []
            communication = entry.get("communication") or []
            for spans in (compute, communication):
                if not isinstance(spans, list):
                    raise ValueError("compute/communication must be interval arrays")
                for span in spans:
                    if (not isinstance(span, list) or len(span) != 2
                            or any(type(value) is not int for value in span)):
                        raise ValueError("Intervals must be [start_ns, end_ns] integers")
            if not communication:
                reasons.append("device-" + str(entry.get("device")) + "-has-no-communication-intervals")
                continue
            comm_seconds, comm_union = _union_seconds(communication)
            compute_seconds, compute_union = _union_seconds(compute) if compute else (0.0, [])
            overlap = _overlap_seconds(comm_union, compute_union) if compute_union else 0.0
            exposed = max(comm_seconds - overlap, 0.0)
            rows.append({"device": entry.get("device"),
                         "communication_union_seconds": comm_seconds,
                         "compute_union_seconds": compute_seconds,
                         "overlapped_seconds": overlap, "exposed_seconds": exposed,
                         "exposed_share_of_compute": (exposed / compute_seconds) if compute_seconds else None,
                         "declared_ranks": entry.get("ranks")})
        retained, gaps = _retained_evidence(Store(context.workspace), request)
        if not retained:
            reasons.append("raw-interval-evidence-required")
        reasons.extend(gaps)
        status = "incomplete" if reasons or not rows else "complete"
        output = {"schema_version": 1, "context": context.context, "status": status,
                  "scope": "declared-interval-accounting", "devices": rows,
                  "required_missing": reasons, "executed": len(rows),
                  "limits": ["Union maths over declared intervals only",
                             "Does not infer communication from kernels, tensor shapes or rank topology",
                             "No cross-rank bottleneck or overlap-efficiency conclusion"],
                  "evidence": retained}
        return CapabilityResult(self.name, request.action, status, outputs=output,
                                evidence=tuple(retained), metadata={"context": context.context})


class AdaptationParityCapability:
    """Check that every upstream launch element has a declared HCU counterpart.

    It never invents a mapping: a token or config key without a declared
    counterpart, an empty basis, or a duplicate mapping is reported.  The
    verdict says "the mapping is complete and traceable", not "the port works".
    """

    name = "adaptation.launch-parity"

    def actions(self) -> tuple[str, ...]:
        return ("compare", "run")

    def run(self, context: CapabilityContext, request: CapabilityRequest) -> CapabilityResult:
        if request.action not in self.actions():
            raise ValueError("Unsupported action for " + self.name + ": " + request.action)
        upstream = _required(request, "upstream")
        hcu = _required(request, "hcu")
        mapping = _required(request, "mapping")
        for name, value in (("upstream", upstream), ("hcu", hcu)):
            if not isinstance(value, dict):
                raise ValueError(name + " must be an object with argv/env/config")
        if not isinstance(mapping, list):
            raise ValueError("mapping must be an array of {upstream, hcu, basis}")
        upstream_tokens = _tokens(upstream)
        hcu_tokens = _tokens(hcu)
        paired_upstream, paired_hcu, rows, reasons = set(), set(), [], []
        for index, entry in enumerate(mapping):
            if not isinstance(entry, dict) or set(entry) < {"upstream", "hcu", "basis"}:
                raise ValueError("mapping entry requires upstream, hcu and basis")
            source, target = entry["upstream"], entry["hcu"]
            basis = entry["basis"]
            if not isinstance(source, str) or not isinstance(target, str) or not source or not target:
                raise ValueError("mapping entry upstream/hcu must be nonempty strings")
            if not isinstance(basis, str) or not basis.strip():
                reasons.append("mapping-without-basis:" + source)
            if source in paired_upstream:
                reasons.append("duplicate-upstream-mapping:" + source)
            if target in paired_hcu:
                reasons.append("duplicate-hcu-mapping:" + target)
            paired_upstream.add(source)
            paired_hcu.add(target)
            rows.append({"upstream": source, "hcu": target, "basis": basis,
                         "upstream_seen": source in upstream_tokens,
                         "hcu_seen": target in hcu_tokens})
            if upstream_tokens and source not in upstream_tokens:
                reasons.append("mapping-source-not-in-upstream:" + source)
            if hcu_tokens and target not in hcu_tokens:
                reasons.append("mapping-target-not-in-hcu:" + target)
        if not upstream_tokens:
            reasons.append("upstream-elements-required")
        unmatched_upstream = sorted(upstream_tokens - paired_upstream)
        for token in unmatched_upstream:
            reasons.append("upstream-element-without-mapping:" + token)
        extra_hcu = sorted(hcu_tokens - paired_hcu)
        retained, gaps = _retained_evidence(Store(context.workspace), request)
        reasons.extend(gaps)
        if not retained:
            reasons.append("raw-launch-evidence-required")
        status = "incomplete" if reasons else "complete"
        output = {"schema_version": 1, "context": context.context, "status": status,
                  "scope": "adaptation-launch-parity", "executed": len(rows),
                  "pairs": rows, "unmatched_upstream": unmatched_upstream,
                  "unmapped_hcu": extra_hcu, "required_missing": reasons,
                  "failures": [],
                  "limits": ["Checks declared parity only: a complete mapping is not a working port",
                             "Unmapped HCU elements are listed, never silently accepted",
                             "Does not execute either command"],
                  "evidence": retained}
        return CapabilityResult(self.name, request.action, status, outputs=output,
                                evidence=tuple(retained), metadata={"context": context.context})


class AdaptationDiffCapability:
    """Record the effective config difference of an adaptation.

    Every changed key must carry a declared basis; the unexplained ones are
    listed so a reviewer can see what was changed without being told why.
    """

    name = "adaptation.config-diff"

    def actions(self) -> tuple[str, ...]:
        return ("compare", "run")

    def run(self, context: CapabilityContext, request: CapabilityRequest) -> CapabilityResult:
        if request.action not in self.actions():
            raise ValueError("Unsupported action for " + self.name + ": " + request.action)
        baseline = _required(request, "baseline")
        adapted = _required(request, "adapted")
        basis = request.inputs.get("basis") or {}
        if not isinstance(baseline, dict) or not isinstance(adapted, dict):
            raise ValueError("baseline/adapted must be configuration objects")
        if not isinstance(basis, dict):
            raise ValueError("basis must map changed keys to a reason")
        added = sorted(set(adapted) - set(baseline))
        removed = sorted(set(baseline) - set(adapted))
        changed = sorted(key for key in set(baseline) & set(adapted)
                         if baseline[key] != adapted[key])
        touched = added + removed + changed
        for key in sorted(basis):
            if key not in touched:
                raise ValueError("basis mentions a key that did not change: " + key)
        unexplained = sorted(key for key in touched
                             if not isinstance(basis.get(key), str) or not basis[key].strip())
        status = "incomplete" if unexplained or not touched else "complete"
        required_missing = (["unexplained-change:" + key for key in unexplained]
                            or (["empty-diff"] if not touched else []))
        record = {"schema_version": 1, "context": context.context, "status": status,
                  "scope": "adaptation-config-diff", "executed": len(touched),
                  "added": added, "removed": removed,
                  "changed": {key: {"baseline": baseline[key], "adapted": adapted[key],
                                    "basis": basis.get(key)} for key in changed},
                  "unexplained": unexplained, "required_missing": required_missing,
                  "failures": [],
                  "fingerprint": fingerprint({"baseline": baseline, "adapted": adapted}),
                  "limits": ["Records what changed and why it was declared",
                             "It does not judge whether the change is the right adaptation",
                             "Effective values must come from the runtime dump, not the launch script"],
                  "evidence": []}
        art = Store(context.workspace).put(
            json.dumps(record, sort_keys=True, ensure_ascii=False, allow_nan=False).encode())
        record["evidence"] = [art]
        return CapabilityResult(self.name, request.action, status, outputs=record,
                                evidence=(art,), metadata={"context": context.context})


class AdaptationNumericsCapability:
    """Component-level numeric equivalence for an adaptation.

    Compares declared components (forward, backward, gradient, update) under a
    frozen contract.  This is local evidence: it never claims step-level or
    long-run equivalence, which still needs the quality gates.
    """

    name = "adaptation.numeric-equivalence"

    def actions(self) -> tuple[str, ...]:
        return ("compare", "run")

    def run(self, context: CapabilityContext, request: CapabilityRequest) -> CapabilityResult:
        if request.action not in self.actions():
            raise ValueError("Unsupported action for " + self.name + ": " + request.action)
        contract = _required(request, "contract")
        if not isinstance(contract, dict) or contract.get("context") != context.context:
            raise ValueError("Adaptation numerics contract context mismatch")
        declared = contract.get("components")
        if not isinstance(declared, list) or not declared:
            raise ValueError("components must be a nonempty array of {name, tolerance}")
        tolerances = {}
        for entry in declared:
            if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
                raise ValueError("Each component requires a name")
            tolerance = entry.get("tolerance")
            if (type(tolerance) is bool or not isinstance(tolerance, (int, float))
                    or not math.isfinite(tolerance) or tolerance < 0):
                raise ValueError("Component tolerance must be a finite nonnegative number")
            tolerances[entry["name"]] = float(tolerance)
        rows, failures, missing = [], [], []
        for label in ("baseline", "candidate"):
            record = _required(request, label)
            if not isinstance(record, dict) or not isinstance(record.get("components"), dict):
                raise ValueError(label + " must carry a components object")
        for name, tolerance in tolerances.items():
            sources = {label: request.inputs[label]["components"].get(name)
                       for label in ("baseline", "candidate")}
            if any(value is None for value in sources.values()):
                missing.append(name + "-component-absent")
                continue
            series = {}
            for label, values in sources.items():
                if not isinstance(values, list) or not values:
                    missing.append(name + "-" + label + "-empty")
                    break
                if any(type(v) is bool or not isinstance(v, (int, float)) or not math.isfinite(v)
                       for v in values):
                    missing.append(name + "-" + label + "-nonfinite")
                    break
                series[label] = [float(v) for v in values]
            if len(series) != 2:
                continue
            if len(series["baseline"]) != len(series["candidate"]):
                missing.append(name + "-length-mismatch")
                continue
            differences = [abs(a - b) for a, b in zip(series["baseline"], series["candidate"])]
            scale = max(max(abs(v) for v in series["baseline"]) or 0.0, 1e-12)
            worst = max(differences)
            row = {"component": name, "samples": len(differences), "max_abs_diff": worst,
                   "max_rel_diff": worst / scale, "tolerance": tolerance,
                   "within_tolerance": worst <= tolerance}
            rows.append(row)
            if not row["within_tolerance"]:
                failures.append(name + "-differs-beyond-tolerance")
        retained, gaps = _retained_evidence(Store(context.workspace), request)
        missing.extend(gaps)
        if not retained:
            missing.append("raw-tensor-evidence-required")
        status = "fail" if failures else "incomplete" if missing or not rows else "pass"
        output = {"schema_version": 1, "context": context.context, "status": status,
                  "scope": "adaptation-component-numerics", "executed": len(rows),
                  "components": rows, "failures": failures, "required_missing": missing,
                  "stage_equivalent": False,
                  "limits": ["Local component comparison under a frozen contract only",
                             "Does not prove stage loss, convergence or long-run equivalence",
                             "A within-tolerance result is not an acceptance decision"],
                  "evidence": retained}
        return CapabilityResult(self.name, request.action, status, outputs=output,
                                evidence=tuple(retained), metadata={"context": context.context})


def _tokens(document):
    """Flatten argv/env/config keys so mappings can point at real elements."""

    tokens = set()
    argv = document.get("argv")
    if isinstance(argv, list):
        for value in argv:
            if isinstance(value, str):
                tokens.add(value)
                if value.startswith("-") and "=" in value:
                    tokens.add(value.split("=", 1)[0])
    for key in ("env", "config"):
        section = document.get(key)
        if isinstance(section, dict):
            tokens.update(str(name) for name in section)
    return tokens


class OptimizationChangeCapability:
    """Record the semantics of one change; it never decides whether to do it."""

    name = "optimization.change"

    def actions(self) -> tuple[str, ...]:
        return ("record", "run")

    def run(self, context: CapabilityContext, request: CapabilityRequest) -> CapabilityResult:
        if request.action not in self.actions():
            raise ValueError("Unsupported action for " + self.name + ": " + request.action)
        before, after = _required(request, "before"), _required(request, "after")
        if not isinstance(before, dict) or not isinstance(after, dict):
            raise ValueError("before/after must be configuration objects")
        added = sorted(set(after) - set(before))
        removed = sorted(set(before) - set(after))
        changed = sorted(key for key in set(before) & set(after) if before[key] != after[key])
        if not (added or removed or changed):
            return CapabilityResult(self.name, request.action, "incomplete",
                                    outputs={"context": context.context, "status": "incomplete",
                                             "reasons": ["empty-change"], "evidence": []})
        record = {"schema_version": 1, "context": context.context, "status": "complete",
                  "scope": "change-record", "added": added, "removed": removed,
                  "changed": {key: {"before": before[key], "after": after[key]} for key in changed},
                  "basis": request.inputs.get("basis"), "patch_hash": request.inputs.get("patch_hash"),
                  "rollback": request.inputs.get("rollback"),
                  "fingerprint": fingerprint({"before": before, "after": after}),
                  "limits": ["Records what changed, not whether it should be merged",
                             "A claimed gain still needs matched measurement evidence"]}
        store = Store(context.workspace)
        artifact = store.put(json.dumps(record, sort_keys=True, ensure_ascii=False,
                                        allow_nan=False).encode())
        record["evidence"] = [artifact]
        return CapabilityResult(self.name, request.action, "complete", outputs=record,
                                evidence=(artifact,), metadata={"context": context.context})


class OptimizationBenchmarkCapability:
    """Isolated same-shape comparison; reporting only, no merge decision."""

    name = "optimization.benchmark"

    def actions(self) -> tuple[str, ...]:
        return ("compare", "run")

    def run(self, context: CapabilityContext, request: CapabilityRequest) -> CapabilityResult:
        if request.action not in self.actions():
            raise ValueError("Unsupported action for " + self.name + ": " + request.action)
        baseline = _positive_seconds(_required(request, "baseline_times"), "baseline_times")
        candidate = _positive_seconds(_required(request, "candidate_times"), "candidate_times")
        shape = request.inputs.get("shape")
        ceiling = request.inputs.get("ceiling_seconds")
        failures, missing = [], []
        if len(baseline) < 3 or len(candidate) != len(baseline):
            missing.append("need-at-least-three-matched-repetitions")
        if not isinstance(shape, dict) or not shape:
            missing.append("shape-required-for-isolated-comparison")
        if ceiling is not None and (type(ceiling) is bool or not isinstance(ceiling, (int, float))
                                    or not math.isfinite(ceiling) or ceiling <= 0):
            raise ValueError("ceiling_seconds must be a finite positive number")
        medians = [statistics.median(series) for series in (baseline, candidate)]
        ratio = medians[1] / medians[0]
        best = min(baseline) / min(candidate)
        spreads = [_relative_mad(baseline), _relative_mad(candidate)]
        protocol = request.inputs.get("max_relative_mad")
        if protocol is not None:
            if type(protocol) is bool or not isinstance(protocol, (int, float)) or protocol < 0:
                raise ValueError("max_relative_mad must be a nonnegative number")
            if max(spreads) > protocol:
                missing.append("repetitions-unstable")
        efficiency = None
        if isinstance(ceiling, (int, float)):
            efficiency = {"ceiling_seconds": float(ceiling), "median_seconds": medians[1],
                          "ceiling_efficiency": float(ceiling) / medians[1],
                          "remaining_headroom_seconds": medians[1] - float(ceiling)}
        if ratio > 1.0:
            failures.append("median-regression")
        retained, gaps = _retained_evidence(Store(context.workspace), request)
        if not retained:
            missing.append("raw-timing-evidence-required")
        missing.extend(gaps)
        status = "fail" if failures else "incomplete" if missing else "pass"
        output = {"schema_version": 1, "context": context.context, "status": status,
                  "scope": "isolated-benchmark", "executed": len(baseline),
                  "failures": failures, "required_missing": missing,
                  "shape": shape, "dtype": request.inputs.get("dtype"),
                  "time_ratio": ratio, "best_case_ratio": best,
                  "paired_ratios": [y / x for x, y in zip(baseline, candidate)],
                  "median_seconds": {"baseline": medians[0], "candidate": medians[1]},
                  "relative_mad": spreads, "efficiency": efficiency,
                  "limits": ["Isolated same-shape comparison only",
                             "Not a full-training net gain; use optimization.netgain for that",
                             "Median comparison is not statistical significance"],
                  "evidence": retained}
        return CapabilityResult(self.name, request.action, status, outputs=output,
                                evidence=tuple(retained), metadata={"context": context.context})


class OptimizationNetgainCapability:
    """Wall-clock net gain including startup, with an explicit noise judgement."""

    name = "optimization.netgain"

    def actions(self) -> tuple[str, ...]:
        return ("assess", "run")

    def run(self, context: CapabilityContext, request: CapabilityRequest) -> CapabilityResult:
        if request.action not in self.actions():
            raise ValueError("Unsupported action for " + self.name + ": " + request.action)
        baseline, candidate = _required(request, "baseline"), _required(request, "candidate")
        rows, missing, failures = {}, [], []
        for key, record in (("baseline", baseline), ("candidate", candidate)):
            if not isinstance(record, dict):
                raise ValueError(key + " must be a measurement object")
            series = _positive_seconds(record.get("step_seconds"), key + ".step_seconds")
            startup = record.get("startup_seconds") or []
            if startup:
                startup = _positive_seconds(startup, key + ".startup_seconds")
            rows[key] = {"median_seconds": statistics.median(series),
                         "startup_seconds": sum(startup), "samples": len(series),
                         "relative_mad": _relative_mad(series)}
            if len(series) < 3:
                missing.append(key + "-needs-three-steady-samples")
        if rows["baseline"]["samples"] != rows["candidate"]["samples"]:
            missing.append("sample-counts-differ")
        totals = {key: row["median_seconds"] * row["samples"] + row["startup_seconds"]
                  for key, row in rows.items()}
        gain = (totals["baseline"] - totals["candidate"]) / totals["baseline"]
        noise = max(rows["baseline"]["relative_mad"] or 0.0, rows["candidate"]["relative_mad"] or 0.0)
        paired = [b / c for b, c in zip(baseline.get("step_seconds", []),
                                        candidate.get("step_seconds", []))]
        if gain < 0:
            failures.append("net-regression")
        retained, gaps = _retained_evidence(Store(context.workspace), request)
        if not retained:
            missing.append("raw-measurement-evidence-required")
        missing.extend(gaps)
        status = "fail" if failures else "incomplete" if missing or gain <= noise else "pass"
        output = {"schema_version": 1, "context": context.context, "status": status,
                  "scope": "net-gain", "executed": rows["candidate"]["samples"],
                  "failures": failures, "required_missing": missing,
                  "net_gain": gain, "noise_threshold": noise,
                  "within_noise": gain <= noise,
                  "totals_seconds": totals, "steps": rows,
                  "paired_ratios": paired,
                  "measurement_basis": "steady median x samples plus startup, profiler off",
                  "limits": ["Net gain above noise is evidence, not an acceptance decision",
                             "Checkpoint/evaluation costs must be inside the declared samples"],
                  "evidence": retained}
        return CapabilityResult(self.name, request.action, status, outputs=output,
                                evidence=tuple(retained), metadata={"context": context.context})
