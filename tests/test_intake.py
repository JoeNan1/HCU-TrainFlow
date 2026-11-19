"""The reusable intake expands into bundles and refuses to widen authority.

The example in examples/ is a template with placeholders, so these tests build
their own small document: one site, two tasks, contracts that only the full task
uses.
"""
import importlib.util
import json
from pathlib import Path

import pytest

from hcu_trainflow import flow, intake
from hcu_trainflow.core import FlowError, Store, validate_spec

ROOT = Path(__file__).resolve().parents[1]


def generator():
    spec = importlib.util.spec_from_file_location(
        'build_autonomous_task', ROOT / 'scripts' / 'build_autonomous_task.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def checker():
    spec = importlib.util.spec_from_file_location(
        'check_intake', ROOT / 'scripts' / 'check_intake.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def document():
    return {
        "schema_version": 1,
        "revision": "2026-11-19",
        "scope": {"site": "site-a", "engine": "megatron", "model_family": "llm",
                  "model": "model-8b"},
        "site": {
            "ssh_target": "site-a", "container": "train", "cwd": "/work/snapshot",
            "commands": {
                "environment": {"argv": ["bash", "env.sh"], "env": {},
                                "timeout_seconds": 600, "basis": "site script"},
                "train": {"argv": ["bash", "train.sh"], "env": {},
                          "timeout_seconds": 3600, "basis": "verified recipe"},
            },
            "devices": [{"node": "node-1", "device": 0, "identity": "0000:01",
                         "idle_memory_bytes": 0, "memory_tolerance_bytes": 0,
                         "max_utilization_pct": 2, "basis": "idle sample"}],
            "occupancy": {"max_age_seconds": 600, "min_observations": 3,
                          "quiet_period_seconds": 120, "max_sample_gap_seconds": 60,
                          "shared_resources": []},
            "leases": [{"resource": "node-1", "owner": "agent:coordinator", "ttl": 3600}],
        },
        "source": {"repository": "/work/source", "paths": ["train.py"]},
        "paths": {"project": "/work/source", "trace": "/work/trace.json",
                  "state_dir": "/work/observe"},
        "contracts": {
            "environment": {"context": "ctx", "required": []},
            "quality": {"atol": 0.001, "rtol": 0.001, "min_steps": 100,
                        "aggregation": "global-valid-token-mean",
                        "tolerance_basis": "measured spread"},
            "training": {"expected_steps": 100, "steady_start": 20},
        },
        "observation": {"manifest": {}, "policy": {}, "state_dir": "/work/observe"},
        "authority": {
            "permissions": ["execute"],
            "budget": {"max_operations": 240, "max_seconds": 259200},
            "autonomy": {"mode": "autonomous", "reviewers": ["agent:rev"],
                         "question_answers": [],
                         "escalation": {"acceptance_edit": "forbid"}},
        },
        "tasks": [
            {"task_id": "env-only", "mode": "environment",
             "objective": "只检查环境", "acceptance": {"environment": "设备与互联有证据"},
             "budget": {"max_operations": 40, "max_seconds": 21600},
             "use": {"contracts": ["environment"], "commands": ["environment"]}},
            {"task_id": "full-run", "mode": "full",
             "objective": "跑通并优化",
             "acceptance": {"environment": "设备与互联有证据", "quality": "loss 与梯度通过",
                            "performance": "热点与 profiler-off 收益", "scale": "逐级扩 DP"},
             "profile": {"id": "llm-megatron", "reason": "Megatron 完整流程"},
             "use": {"contracts": ["environment", "quality", "training"],
                     "commands": ["environment", "train"]}},
        ],
    }


def test_expand_keeps_only_the_declared_contracts_and_commands():
    bundles = intake.expand(document())
    assert [item["task"]["task_id"] for item in bundles] == ["env-only", "full-run"]
    light, full = bundles
    assert set(light["site"]["commands"]) == {"environment"}
    assert set(full["site"]["commands"]) == {"environment", "train"}
    assert set(light["contracts"]) == {"environment"}
    assert set(full["contracts"]) == {"environment", "quality", "training"}
    assert "profile" not in light["task"] and full["task"]["profile"]["id"] == "llm-megatron"


def test_expanded_task_is_accepted_by_the_runtime(tmp_path):
    bundle = intake.expand(document(), "full-run")[0]
    generated = generator().build(
        {"task": bundle["task"], "autonomy": bundle["autonomy"],
         "plan": bundle["plan"], "site": bundle["site"]}, require_autonomy=False)
    validate_spec(generated["task"])
    store = Store(tmp_path / "store")
    task = store.create(generated["task"])
    flow.start(store, task["id"], generated["plan"])
    assert store.task(task["id"])["state"] == "prepared"
    decision = flow.next_step(store, task["id"])
    assert decision["action"] == "work"
    assert decision["required_reports"] == ["environment"]


def test_task_budget_may_not_exceed_the_authority_envelope():
    value = document()
    value["tasks"][0]["budget"] = {"max_operations": 400, "max_seconds": 21600}
    result = intake.check(value)
    assert result["status"] == "attention"
    assert any("exceeds the authority envelope" in issue for issue in result["issues"])
    with pytest.raises(FlowError):
        intake.expand(value)


def test_a_partial_task_budget_keeps_the_envelope_dimensions():
    """Narrowing one dimension must not drop the other one to infinity."""

    value = document()
    value["tasks"][0]["budget"] = {"max_operations": 5}
    assert intake.check(value)["status"] == "pass"
    bundle = intake.expand(value, "env-only")[0]
    assert bundle["task"]["budget"] == {"max_operations": 5, "max_seconds": 259200}


def test_a_task_budget_field_outside_the_envelope_is_rejected():
    value = document()
    value["authority"]["budget"] = {"max_operations": 240}
    value["tasks"][0]["budget"] = {"max_seconds": 60}
    result = intake.check(value)
    assert any("does not define" in issue for issue in result["issues"])


def test_empty_leases_are_allowed_and_validated():
    value = document()
    value["site"]["leases"] = []
    assert intake.check(value)["status"] == "pass"
    assert intake.expand(value)[0]["lease_entries"] == []
    value["site"]["leases"] = [{"resource": "node-1", "owner": "", "ttl": 60}]
    assert any("owner" in issue for issue in intake.check(value)["issues"])


def test_a_command_name_cannot_escape_the_bundle_directory():
    value = document()
    value["site"]["commands"]["../../escaped"] = {"argv": ["bash", "x.sh"],
                                                  "timeout_seconds": 60, "basis": "b"}
    with pytest.raises(FlowError):
        intake.load(value)


@pytest.mark.parametrize("mutate,needle", [
    (lambda value: value["site"]["devices"][0].pop("idle_memory_bytes"), "idle_memory_bytes"),
    (lambda value: value["site"]["occupancy"].update({"bogus": 1}), "occupancy"),
    (lambda value: value["site"]["commands"]["train"].pop("argv"), "argv"),
])
def test_check_rejects_what_the_generator_would_reject(mutate, needle):
    """A document the checker passes must not fail later in the generator.

    Structural problems make the document malformed, so both the library and
    the checker refuse it rather than reporting a clean pass.
    """

    value = document()
    mutate(value)
    with pytest.raises(FlowError) as raised:
        intake.check(value)
    assert needle in str(raised.value)


def test_unknown_contract_or_command_is_rejected():
    value = document()
    value["tasks"][1]["use"] = {"contracts": ["proxy"], "commands": ["profile"]}
    result = intake.check(value)
    assert any("unknown contracts: proxy" in issue for issue in result["issues"])
    assert any("unknown commands: profile" in issue for issue in result["issues"])


def test_lease_must_match_an_admitted_device():
    value = document()
    value["site"]["leases"] = [{"resource": "node-9", "owner": "agent:a", "ttl": 60}]
    assert any("admitted device" in issue for issue in intake.check(value)["issues"])


def test_a_node_name_lease_resolves_only_when_the_node_is_unambiguous():
    value = document()
    assert intake.lease_resources(value["site"]["devices"], value["site"]["leases"]) == [
        "hcu:node-1:0000:01"]
    value["site"]["devices"].append({"node": "node-1", "device": 1, "identity": "0000:02",
                                     "idle_memory_bytes": 0, "memory_tolerance_bytes": 0,
                                     "max_utilization_pct": 2, "basis": "idle sample"})
    with pytest.raises(FlowError):
        intake.lease_resources(value["site"]["devices"], value["site"]["leases"])


def test_profile_must_agree_with_the_declared_scope():
    value = document()
    value["tasks"][1]["profile"] = {"id": "torch-native-vision", "reason": "视觉"}
    assert any("conflicts with context" in issue for issue in intake.check(value)["issues"])


def test_load_rejects_unknown_sections_and_bad_revision():
    value = document()
    value["surprise"] = 1
    with pytest.raises(FlowError):
        intake.load(value)
    value = document()
    value["revision"] = "19-11-2026"
    with pytest.raises(FlowError):
        intake.load(value)


def test_cli_writes_one_directory_per_task_and_refuses_to_overwrite(tmp_path):
    module = generator()
    source = tmp_path / "intake.json"
    source.write_text(json.dumps(document()), encoding="utf-8")
    output = tmp_path / "bundles"
    assert module.main(["--intake", str(source), "--output", str(output)]) == 0
    for task_id in ("env-only", "full-run"):
        for name in ("task.json", "plan.json", "admission.json"):
            assert (output / task_id / name).is_file()
    assert (output / "full-run" / "contracts" / "quality.json").is_file()
    assert not (output / "env-only" / "contracts" / "quality.json").exists()
    assert json.loads((output / "env-only" / "leases.json").read_text(encoding="utf-8"))[0][
        "ttl"] == 3600
    assert module.main(["--intake", str(source), "--output", str(output)]) == 1


def test_cli_expands_a_single_task_into_the_given_directory(tmp_path):
    module = generator()
    source = tmp_path / "intake.json"
    source.write_text(json.dumps(document()), encoding="utf-8")
    output = tmp_path / "one"
    assert module.main(["--intake", str(source), "--task", "full-run",
                        "--output", str(output)]) == 0
    assert (output / "task.json").is_file()
    assert json.loads((output / "task.json").read_text(encoding="utf-8"))["task_id"] == "full-run"


def test_check_cli_exit_codes(tmp_path, capsys):
    module = checker()
    good = tmp_path / "good.json"
    good.write_text(json.dumps(document()), encoding="utf-8")
    assert module.main([str(good)]) == 0
    bad = tmp_path / "bad.json"
    value = document()
    value["tasks"][0]["budget"] = {"max_operations": 999, "max_seconds": 10}
    bad.write_text(json.dumps(value), encoding="utf-8")
    assert module.main([str(bad)]) == 2
    broken = tmp_path / "broken.json"
    broken.write_text("{", encoding="utf-8")
    assert module.main([str(broken)]) == 1
    assert json.loads(capsys.readouterr().err)["status"] == "error"
