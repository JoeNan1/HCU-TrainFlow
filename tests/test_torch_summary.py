"""Generic torch logs must be parsed from a declared format, not guessed."""
import json

import pytest

from hcu_trainflow.capabilities import default_registry
from hcu_trainflow.core import Store
from hcu_trainflow.kernel import CapabilityContext, CapabilityRequest

CONTEXT = "torch-ctx"


def invoke(store, inputs, action="parse"):
    context = CapabilityContext("torch-task", CONTEXT, store.root)
    return default_registry().resolve("training.summarize-torch").run(
        context, CapabilityRequest("training.summarize-torch", action, inputs))


def contract(**overrides):
    value = {"context": CONTEXT, "expected_steps": 12, "steady_start": 3,
             "timing_groups": 3, "min_samples_per_group": 3,
             "log_format": {"kind": "jsonl"}}
    value.update(overrides)
    return value


def jsonl_log(steps=12, loss=2.0, seconds=0.01, meta=True, skip_steps=()):
    lines = []
    if meta:
        lines.append(json.dumps({"kind": "meta", "fresh": True, "profiler": False}))
    for step in range(1, steps + 1):
        if step in skip_steps:
            continue
        lines.append(json.dumps({"step": step, "loss": loss, "seconds": seconds,
                                 "skipped": 0, "nan": 0}))
    lines.append(json.dumps({"kind": "evaluation", "step": steps,
                             "split": "validation", "loss": 2.0}))
    return "\n".join(lines) + "\n"


def run(tmp_path, log, **overrides):
    store = Store(tmp_path / "store")
    sha = store.put(log.encode())
    inputs = {"contract": contract(**overrides), "log_artifact": sha}
    return invoke(store, inputs), sha


def test_jsonl_log_produces_the_short_baseline_summary(tmp_path):
    result, sha = run(tmp_path, jsonl_log(), required_evaluations=["validation"],
                      world_size=1, global_batch_size=2, seq_length=8)
    assert result.status == "pass", result.outputs["required_missing"]
    assert result.outputs["engine"] == "torch"
    assert result.outputs["scope"] == "fresh-short-baseline"
    assert result.outputs["executed"] == 12
    assert result.outputs["fresh_initialization"] is True
    assert result.outputs["profiler_off"] is True
    assert result.outputs["steady"]["samples"] == 10
    assert result.outputs["steady"]["tokens_per_second_per_gpu"] == pytest.approx(
        2 * 8 * 10 / (1 * 10 * 0.01))
    assert result.evidence == (sha,)


def test_pattern_mode_cannot_prove_fresh_or_profiler_state(tmp_path):
    log = "".join(f"iteration {step} loss 2.0 ms 10.0\n" for step in range(1, 13))
    result, _ = run(tmp_path, log, log_format={
        "kind": "pattern",
        "pattern": r"iteration (?P<step>\d+) loss (?P<loss>[0-9.]+) ms (?P<seconds>[0-9.]+)"})
    assert result.status == "incomplete"
    assert "fresh-initialization-not-proven" in result.outputs["required_missing"]
    assert "profiler-off-not-proven" in result.outputs["required_missing"]
    assert result.outputs["executed"] == 12
    assert result.outputs["fresh_initialization"] is False


def test_gaps_are_incomplete_and_bad_numbers_fail(tmp_path):
    missing, _ = run(tmp_path, jsonl_log(skip_steps=(5,)))
    assert missing.status == "incomplete"
    assert "expected-unique-contiguous-iteration-series" in missing.outputs["required_missing"]

    broken, _ = run(tmp_path, jsonl_log(loss=float("inf")))
    assert broken.status == "fail"
    assert "nonfinite-or-missing-loss" in broken.outputs["failures"]


def test_declared_but_unrecognised_lines_are_reported(tmp_path):
    log = jsonl_log() + "not json at all\n"
    result, _ = run(tmp_path, log)
    assert result.status == "incomplete"
    assert any(item.startswith("unparsable-log-lines:") for item in result.outputs["required_missing"])


def test_configuration_errors_are_rejected(tmp_path):
    with pytest.raises(ValueError):
        run(tmp_path, jsonl_log(), log_format={"kind": "csv"})
    with pytest.raises(ValueError):
        run(tmp_path, jsonl_log(), log_format={"kind": "pattern", "pattern": r"(?P<step>\d+)"})
    with pytest.raises(ValueError):
        run(tmp_path, jsonl_log(), context="another-context")


def test_custom_field_names_are_honoured(tmp_path):
    log = "\n".join([json.dumps({"kind": "meta", "fresh": True, "profiler": False})]
                    + [json.dumps({"iter": step, "lm_loss": 2.0, "sec": 0.01})
                       for step in range(1, 13)]) + "\n"
    result, _ = run(tmp_path, log, log_format={
        "kind": "jsonl", "step": "iter", "loss": "lm_loss", "seconds": "sec"})
    assert result.status == "pass", result.outputs["required_missing"]
    assert result.outputs["steady"]["samples"] == 10
