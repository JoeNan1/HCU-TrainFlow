"""Evidence adapters for a fresh baseline, without inventing a candidate."""
from __future__ import annotations

import json
import math
from pathlib import Path
import re
import statistics

from ..core import Store, digest, fingerprint
from ..kernel.contracts import CapabilityResult
from .scenarios import _evidence, _required


class ArtifactCollectionCapability:
    """Seal declared command outputs before downstream analysis uses them."""

    name = "artifact.collect"

    def actions(self):
        return ("retain", "run")

    def run(self, context, request):
        if request.action not in self.actions():
            raise ValueError("Unsupported artifact collection action")
        files = _required(request, "files")
        if not isinstance(files, dict) or not files:
            raise ValueError("files must map output names to path/sha256 receipts")
        store, retained, errors = Store(context.workspace), {}, []
        for name, receipt in files.items():
            if (not isinstance(name, str) or not isinstance(receipt, dict)
                    or not isinstance(receipt.get("sha256"), str)
                    or not re.fullmatch(r"[0-9a-f]{64}", receipt["sha256"])):
                raise ValueError("Output receipt requires a name, path and sha256")
            try:
                path = Path(receipt["path"])
                if not path.is_absolute():
                    raise ValueError("Collected output paths must be absolute")
                data = path.read_bytes()
                if digest(data) != receipt["sha256"]:
                    raise ValueError("Collected output hash differs from producer receipt")
                retained[name] = {"artifact": store.put(data), "bytes": len(data), "path": str(path)}
            except (OSError, ValueError) as exc:
                errors.append({"name": name, "reason": str(exc)})
        status = "incomplete" if errors else "complete"
        evidence = tuple(row["artifact"] for row in retained.values())
        return CapabilityResult(self.name, request.action, status, outputs={
            "context": context.context, "status": status, "files": retained,
            "errors": errors, "evidence": list(evidence)}, evidence=evidence)


def _positive_integer(contract, key):
    value = contract.get(key)
    if type(value) is not int or value <= 0:
        raise ValueError(key + " must be a positive integer")
    return value


def _stats(values):
    return {"mean": statistics.mean(values), "median": statistics.median(values),
            "min": min(values), "max": max(values)} if values else {}


class TrainingSummaryCapability:
    name = "training.summarize"

    def actions(self):
        return ("parse", "run")

    def run(self, context, request):
        if request.action not in self.actions():
            raise ValueError("Unsupported training summary action")
        from ..training_logs import parse_megatron_line
        store = Store(context.workspace)
        contract = _required(request, "contract")
        if contract.get("context") != context.context:
            raise ValueError("Training contract context mismatch")
        expected = _positive_integer(contract, "expected_steps")
        steady_start = _positive_integer(contract, "steady_start")
        world = _positive_integer(contract, "world_size")
        batch = _positive_integer(contract, "global_batch_size")
        seq = _positive_integer(contract, "seq_length")
        execution = request.inputs.get("execution", {})
        # ``execution`` may be a bound capability result or the retained
        # artifact ID of the training stdout it produced.
        log_sha = request.inputs.get("log_artifact")
        if not log_sha and isinstance(execution, str):
            log_sha, execution = execution, {}
        if not log_sha:
            if not isinstance(execution, dict):
                raise ValueError("execution must be a capability result or an artifact ID")
            log_sha = execution["evidence"][0]
        raw = store.artifact(log_sha).decode("utf-8")
        records, fatal, warnings, evaluations = [], [], [], []
        for line in raw.splitlines():
            parsed = parse_megatron_line(line, log_timezone=contract.get("log_timezone", "UTC"), observed_at=0)
            if parsed and parsed["kind"] == "iteration":
                records.append(parsed)
            elif parsed and parsed["kind"] == "fatal":
                fatal.append(parsed["fatal"])
            elif parsed and parsed.get("warning"):
                warnings.append(parsed["warning"])
            match = re.search(r"validation loss at iteration (\d+) on (validation|test) set.*?lm loss value:\s*(\S+)", line)
            if match:
                value = float(match[3])
                evaluations.append({"step": int(match[1]), "split": match[2],
                                    "loss": value if math.isfinite(value) else str(value)})
        failures, missing = list(fatal), []
        steps = [r["step"] for r in records]
        if steps != list(range(1, expected + 1)) or any(r["total_steps"] != expected for r in records):
            missing.append("expected-unique-contiguous-iteration-series")
        if execution and execution.get("status") != "complete":
            failures.append("training-execution-not-complete")
        for r in records:
            metrics = r["metrics"]
            if (r.get("nonfinite") or not isinstance(r.get("loss"), (float, int))
                    or not math.isfinite(r["loss"])):
                failures.append("nonfinite-or-missing-loss")
            for key in ("number of skipped iterations", "number of nan iterations"):
                if key not in metrics:
                    missing.append("missing-" + key)
                elif metrics[key] != 0:
                    failures.append(key)
            if r.get("warning"):
                missing.append(r["warning"])
        # Inspect the effective argument dump, rather than trusting a launcher flag.
        def argument(name):
            matches = re.findall(r"^\s*" + re.escape(name) + r"\s+\.+\s+(.*?)\s*$", raw, re.M)
            return matches[-1] if matches else None
        fresh = argument("load") == "None" and argument("load_weights") == "False"
        profiler_off = argument("profile") == "False"
        if not fresh:
            missing.append("fresh-initialization-not-proven")
        if not profiler_off:
            missing.append("profiler-off-not-proven")
        for name, value in contract.get("effective_arguments", {}).items():
            observed = argument(name)
            if observed is None:
                missing.append("missing-effective-argument:" + name)
            elif observed != str(value):
                failures.append("effective-argument-mismatch:" + name)
        steady = [r for r in records if steady_start <= r["step"] <= expected]
        times = [r["step_seconds_reported"] for r in steady if "step_seconds_reported" in r]
        if len(times) != len(steady) or not steady:
            missing.append("missing-steady-timing")
        for split in contract.get("required_evaluations", ["validation", "test"]):
            rows = [r for r in evaluations if r["split"] == split and r["step"] == expected]
            if len(rows) != 1:
                missing.append("missing-final-" + split + "-loss")
            elif not isinstance(rows[0]["loss"], (float, int)):
                failures.append("nonfinite-" + split + "-loss")
        groups = _positive_integer(contract, "timing_groups")
        minimum = _positive_integer(contract, "min_samples_per_group")
        windows = []
        if len(times) < groups * minimum:
            missing.append("insufficient-steady-timing-groups")
        else:
            for i in range(groups):
                values = times[i * len(times) // groups:(i + 1) * len(times) // groups]
                windows.append({"samples": len(values), "mean_seconds": statistics.mean(values)})
        relative_spread = ((max(r["mean_seconds"] for r in windows) / min(r["mean_seconds"] for r in windows)) - 1
                           if windows else None)
        threshold = contract.get("max_group_relative_spread", 0.1)
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not math.isfinite(threshold) or threshold < 0:
            raise ValueError("max_group_relative_spread must be finite and nonnegative")
        if relative_spread is not None and relative_spread > threshold:
            missing.append("steady-timing-groups-unstable")
        tflops = [r["metrics"]["throughput per gpu (tflop/s/gpu)"] for r in steady
                  if isinstance(r["metrics"].get("throughput per gpu (tflop/s/gpu)"), (float, int))]
        evidence = tuple(dict.fromkeys([log_sha, *_evidence(execution)]))
        status = "fail" if failures else "incomplete" if missing else "pass"
        output = {"schema_version": 1, "context": context.context, "status": status,
                  "scope": "fresh-short-baseline", "contract_fingerprint": fingerprint(contract),
                  "executed": len(records), "failures": list(dict.fromkeys(failures)),
                  "required_missing": list(dict.fromkeys(missing)), "warnings": sorted(set(warnings)),
                  "fresh_initialization": fresh, "profiler_off": profiler_off,
                  "steps": steps, "loss": [r.get("loss") for r in records], "evaluations": evaluations,
                  "startup": [r for r in records if r["step"] < steady_start],
                  "steady": {"start": steady_start, "end": expected, "samples": len(times),
                             "step_seconds": _stats(times), "timing_groups": windows,
                             "group_relative_spread": relative_spread,
                             "tokens_per_second_per_gpu": batch * seq * len(times) / (world * sum(times)) if times else None,
                             "reported_tflops_per_gpu": _stats(tflops)},
                  "measurement_basis": "sum of profiler-off reported iteration wall times; startup excluded; contiguous groups are not independent launches",
                  "evidence": list(evidence)}
        return CapabilityResult(self.name, request.action, status, outputs=output, evidence=evidence)


class TorchTrainingSummaryCapability:
    """Generic torch training log → the same short-baseline summary contract.

    Torch-native models have no shared log format, so the site declares one:
    ``jsonl`` (one object per line, optional ``meta``/``evaluation`` records)
    or an explicit ``pattern`` with named groups.  Only what the log actually
    shows is reported; a log without a ``meta`` record cannot prove
    fresh-initialization or profiler-off, and that stays a missing requirement
    instead of an assumed pass.
    """

    name = "training.summarize-torch"

    def actions(self):
        return ("parse", "run")

    _FIELDS = {"step": "step", "loss": "loss", "seconds": "seconds"}

    def _format(self, contract):
        log_format = contract.get("log_format")
        if not isinstance(log_format, dict):
            raise ValueError("log_format must be an object")
        kind = log_format.get("kind")
        if kind not in {"jsonl", "pattern"}:
            raise ValueError("log_format.kind must be jsonl or pattern")
        fields = {key: log_format.get(key, default) for key, default in self._FIELDS.items()}
        for key, name in fields.items():
            if not isinstance(name, str) or not name:
                raise ValueError("log_format." + key + " must be a field name")
        if kind == "pattern":
            pattern = log_format.get("pattern")
            if not isinstance(pattern, str) or not pattern.strip():
                raise ValueError("log_format.pattern is required for pattern mode")
            compiled = re.compile(pattern)
            if "step" not in compiled.groupindex or "loss" not in compiled.groupindex:
                raise ValueError("pattern requires named groups step and loss")
        return {"kind": kind, "fields": fields,
                "pattern": compiled if kind == "pattern" else None}

    def _parse(self, raw, spec):
        records, evaluations, meta, unparsable = [], [], {}, 0
        iterations = spec["fields"]
        for line in raw.splitlines():
            if not line.strip():
                continue
            if spec["kind"] == "jsonl":
                try:
                    row = json.loads(line)
                except ValueError:
                    unparsable += 1
                    continue
                if not isinstance(row, dict):
                    unparsable += 1
                    continue
                kind = row.get("kind")
                if kind == "meta":
                    meta.update({key: row[key] for key in ("fresh", "profiler") if key in row})
                    continue
                if kind == "evaluation":
                    evaluations.append({"step": row.get("step"), "split": row.get("split"),
                                        "loss": row.get("loss")})
                    continue
                try:
                    step = int(row[iterations["step"]])
                    loss = row[iterations["loss"]]
                    seconds = row.get(iterations["seconds"])
                except (KeyError, TypeError, ValueError):
                    unparsable += 1
                    continue
                record = {"step": step, "loss": loss, "seconds": seconds,
                          "total_steps": row.get("total_steps"),
                          "skipped": row.get("skipped"), "nan": row.get("nan")}
            else:
                match = spec["pattern"].search(line)
                if not match:
                    unparsable += 1
                    continue
                try:
                    step = int(match.group("step"))
                    loss = float(match.group("loss"))
                except (TypeError, ValueError):
                    unparsable += 1
                    continue
                seconds = None
                if "seconds" in spec["pattern"].groupindex:
                    try:
                        seconds = float(match.group("seconds"))
                    except (TypeError, ValueError):
                        unparsable += 1
                        continue
                record = {"step": step, "loss": loss, "seconds": seconds,
                          "total_steps": None, "skipped": None, "nan": None}
            if record["seconds"] is not None:
                try:
                    record["seconds"] = float(record["seconds"])
                except (TypeError, ValueError):
                    record["seconds"] = "not-a-number"
            records.append(record)
        return records, evaluations, meta, unparsable

    def run(self, context, request):
        if request.action not in self.actions():
            raise ValueError("Unsupported training summary action: " + request.action)
        store = Store(context.workspace)
        contract = _required(request, "contract")
        if contract.get("context") != context.context:
            raise ValueError("Training contract context mismatch")
        expected = _positive_integer(contract, "expected_steps")
        steady_start = _positive_integer(contract, "steady_start")
        groups = _positive_integer(contract, "timing_groups")
        minimum = _positive_integer(contract, "min_samples_per_group")
        spec = self._format(contract)
        execution = request.inputs.get("execution", {})
        log_sha = request.inputs.get("log_artifact")
        if not log_sha and isinstance(execution, str):
            log_sha, execution = execution, {}
        if not log_sha:
            if not isinstance(execution, dict):
                raise ValueError("execution must be a capability result or an artifact ID")
            log_sha = execution["evidence"][0]
        raw = store.artifact(log_sha).decode("utf-8")
        records, evaluations, meta, unparsable = self._parse(raw, spec)

        failures, missing = [], []
        if unparsable:
            missing.append("unparsable-log-lines:" + str(unparsable))
        steps = [record["step"] for record in records]
        if steps != list(range(1, expected + 1)):
            missing.append("expected-unique-contiguous-iteration-series")
        if any(record["total_steps"] not in (None, expected) for record in records):
            missing.append("log-total-steps-disagree-with-contract")
        if execution and execution.get("status") != "complete":
            failures.append("training-execution-not-complete")
        for record in records:
            loss = record["loss"]
            if isinstance(loss, bool) or not isinstance(loss, (int, float)) or not math.isfinite(loss):
                failures.append("nonfinite-or-missing-loss")
            for key, label in (("skipped", "skipped-iterations"), ("nan", "nan-iterations")):
                if record[key] is not None and record[key] != 0:
                    failures.append(label)
        fresh = meta.get("fresh") is True
        profiler_off = meta.get("profiler") is False
        if not fresh:
            missing.append("fresh-initialization-not-proven")
        if not profiler_off:
            missing.append("profiler-off-not-proven")
        steady = [record for record in records if steady_start <= record["step"] <= expected]
        times = [record["seconds"] for record in steady
                 if isinstance(record.get("seconds"), float) and math.isfinite(record["seconds"])]
        if len(times) != len(steady) or not steady:
            missing.append("missing-steady-timing")
        for split in contract.get("required_evaluations", []):
            rows = [row for row in evaluations if row["split"] == split and row["step"] == expected]
            if len(rows) != 1:
                missing.append("missing-final-" + split + "-loss")
            elif isinstance(rows[0]["loss"], bool) or not isinstance(rows[0]["loss"], (int, float)) \
                    or not math.isfinite(rows[0]["loss"]):
                failures.append("nonfinite-" + split + "-loss")
        windows = []
        if len(times) < groups * minimum:
            missing.append("insufficient-steady-timing-groups")
        else:
            for index in range(groups):
                values = times[index * len(times) // groups:(index + 1) * len(times) // groups]
                windows.append({"samples": len(values), "mean_seconds": statistics.mean(values)})
        relative_spread = ((max(row["mean_seconds"] for row in windows)
                            / min(row["mean_seconds"] for row in windows)) - 1) if windows else None
        threshold = contract.get("max_group_relative_spread", 0.1)
        if (isinstance(threshold, bool) or not isinstance(threshold, (int, float))
                or not math.isfinite(threshold) or threshold < 0):
            raise ValueError("max_group_relative_spread must be finite and nonnegative")
        if relative_spread is not None and relative_spread > threshold:
            missing.append("steady-timing-groups-unstable")
        tokens = None
        world = contract.get("world_size")
        batch = contract.get("global_batch_size")
        seq = contract.get("seq_length")
        if all(type(value) is int and value > 0 for value in (world, batch, seq)) and times:
            tokens = batch * seq * len(times) / (world * sum(times))
        evidence = tuple(dict.fromkeys([log_sha, *_evidence(execution)]))
        status = "fail" if failures else "incomplete" if missing else "pass"
        output = {"schema_version": 1, "context": context.context, "status": status,
                  "scope": "fresh-short-baseline", "engine": "torch",
                  "contract_fingerprint": fingerprint(contract),
                  "log_format": {"kind": spec["kind"], **spec["fields"]},
                  "executed": len(records), "failures": list(dict.fromkeys(failures)),
                  "required_missing": list(dict.fromkeys(missing)),
                  "fresh_initialization": fresh, "profiler_off": profiler_off,
                  "steps": steps, "loss": [record["loss"] for record in records],
                  "evaluations": evaluations,
                  "startup": [record for record in records if record["step"] < steady_start],
                  "steady": {"start": steady_start, "end": expected, "samples": len(times),
                             "step_seconds": _stats(times), "timing_groups": windows,
                             "group_relative_spread": relative_spread,
                             "tokens_per_second_per_gpu": tokens},
                  "measurement_basis": "sum of profiler-off reported iteration wall times; startup excluded",
                  "limits": ["Declared log format only; unrecognised lines are reported, not skipped silently",
                             "A missing meta record leaves fresh/profiler state unproven",
                             "Contiguous timing groups are not independent launches"],
                  "evidence": list(evidence)}
        return CapabilityResult(self.name, request.action, status, outputs=output, evidence=evidence)


def qualify_baseline(context, request):
    training = _required(request, "training")
    environment = _required(request, "environment")
    analysis = _required(request, "analysis")
    reasons = []
    for key, value in (("training", training), ("environment", environment), ("analysis", analysis)):
        if value.get("context") != context.context or value.get("status") not in {"pass", "complete"} or not _evidence(value):
            reasons.append(key + "-not-qualified")
    if training.get("scope") != "fresh-short-baseline" or not training.get("fresh_initialization") or not training.get("profiler_off"):
        reasons.append("fresh-profiler-off-baseline-not-proven")
    if type(training.get("executed")) is not int or training["executed"] <= 0 or training.get("failures") or training.get("required_missing"):
        reasons.append("training-coverage-not-proven")
    scope = request.inputs.get("analysis_scope", "hipprof-summary")
    if analysis.get("scope") != scope:
        reasons.append("analysis-scope-mismatch")
    status = "fail" if any(x.get("status") == "fail" for x in (training, environment, analysis)) else "incomplete" if reasons else "pass"
    evidence = _evidence(training, environment, analysis)
    output = {"schema_version": 1, "context": context.context, "status": status,
              "scope": "baseline-qualification", "executed": training.get("executed", 0),
              "failures": int(status == "fail"), "required_missing": reasons,
              "baseline_qualified": status == "pass", "stage_eligible": False,
              "optimization_validated": False, "model_diagnosis": analysis.get("model_diagnosis", "incomplete"),
              "analysis_scope": scope, "performance": training.get("steady", {}),
              "provenance": {key: fingerprint(val) for key, val in (("training", training), ("environment", environment), ("analysis", analysis))},
              "limits": ["Short baseline only; no candidate comparison, checkpoint recovery or long-run validation",
                         "Flow review and advancement remain separate gates"], "evidence": list(evidence)}
    return CapabilityResult("quality.accept", request.action, status, outputs=output, evidence=evidence)


def summarize_hipprof(context, request):
    """Use exact native timestamps; summed kernels are not a wall-time fraction."""
    source = _required(request, "profile")
    if source.get("context") != context.context or source.get("status") != "complete" or source.get("mode") != "hipprof":
        raise ValueError("A completed hipprof capability result in the same context is required")
    sha = _required(request, "normalized_artifact")
    if sha not in _evidence(source):
        raise ValueError("Normalized trace must belong to the bound profiler evidence")
    data = json.loads(Store(context.workspace).artifact(sha))
    kernels = [e for e in data["traceEvents"] if e.get("cat") == "kernel_dispatch"]
    by_name, intervals = {}, {}
    for event in kernels:
        args = event["args"]
        begin, end, duration = (args[k] for k in ("begin_ns", "end_ns", "delta_ns"))
        if any(type(v) is not int for v in (begin, end, duration)) or end - begin != duration or duration < 0:
            raise ValueError("Invalid exact hipprof timestamps")
        group = by_name.setdefault(event["name"], {"name": event["name"], "count": 0, "duration_ns": 0})
        group["count"] += 1
        group["duration_ns"] += duration
        intervals.setdefault((event["pid"], args["device_id"]), []).append((begin, end))
    devices = []
    for (pid, device), spans in sorted(intervals.items()):
        spans.sort()
        start, end = spans[0]
        first, last, busy = start, max(x[1] for x in spans), 0
        for left, right in spans[1:]:
            if left > end:
                busy += end - start
                start, end = left, right
            else:
                end = max(end, right)
        busy += end - start
        devices.append({"pid": pid, "device": device, "observed_span_seconds": (last - first) / 1e9,
                        "kernel_union_seconds": busy / 1e9})
    total = sum(g["duration_ns"] for g in by_name.values())
    top = sorted(by_name.values(), key=lambda r: r["duration_ns"], reverse=True)[:20]
    for row in top:
        row["total_seconds"] = row["duration_ns"] / 1e9
        row["summed_kernel_share"] = row["duration_ns"] / total if total else 0
    evidence = _evidence(source)
    status = "complete" if kernels else "incomplete"
    output = {"context": context.context, "status": status, "scope": "hipprof-summary",
              "model_diagnosis": "incomplete", "kernel_dispatches": len(kernels),
              "top_kernels": top, "devices": devices,
              "limits": ["Observed trace span includes startup/evaluation unless an explicit window is selected",
                         "Kernel share uses summed exact dispatch durations, not training wall time",
                         "No tensor shapes, model phases, ceilings or cross-rank bottleneck conclusion"],
              "evidence": list(evidence)}
    return CapabilityResult("profiling.analyze", request.action, status, outputs=output, evidence=evidence)
