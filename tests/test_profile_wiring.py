"""A declared sub-workflow narrows work; it may never narrow a stage gate."""
import json

import pytest

from hcu_trainflow import catalog, flow
from hcu_trainflow.catalog.contracts import Profile
from hcu_trainflow.core import GATES, FlowError, Store

PROFILE = {"id": "llm-megatron", "reason": "megatron recipe with the standard gates"}


def setup(tmp_path, *, profile=PROFILE, mode="full", context=None, task_id="p"):
    store = Store(tmp_path / "workspace")
    spec = {"schema_version": 1, "task_id": task_id, "mode": mode,
            "objective": "Profile wiring fixture",
            "context": context or {"source": "fixture", "engine": "megatron",
                                   "model_family": "llm"},
            "permissions": ["execute"]}
    if profile is not None:
        spec["profile"] = profile
    store.create(spec)
    flow.start(store, task_id, {"acceptance": {"result": "Deliver evidence in scope"}})
    return store


def test_task_profile_requires_an_id_and_a_reason(tmp_path):
    store = Store(tmp_path / "w")
    base = {"schema_version": 1, "task_id": "t", "mode": "full", "objective": "x",
            "context": {"source": "f"}, "permissions": []}
    with pytest.raises(FlowError):
        store.create({**base, "profile": {"id": "llm-megatron"}})
    with pytest.raises(FlowError):
        store.create({**base, "profile": {"id": "llm-megatron", "reason": "   "}})
    with pytest.raises(FlowError):
        store.create({**base, "profile": {"id": "LLM Megatron", "reason": "x"}})
    with pytest.raises(FlowError):
        store.create({**base, "profile": {"id": "llm-megatron", "reason": "x", "extra": 1}})
    assert store.create({**base, "profile": PROFILE})["spec"]["profile"] == PROFILE


def test_start_rejects_an_unknown_or_conflicting_profile(tmp_path):
    store = Store(tmp_path / "w")
    spec = {"schema_version": 1, "task_id": "t", "mode": "full", "objective": "x",
            "context": {"source": "f", "engine": "megatron", "model_family": "llm"},
            "permissions": []}
    store.create({**spec, "profile": {"id": "ghost-profile", "reason": "x"}})
    with pytest.raises(FlowError):
        flow.start(store, "t", {"acceptance": {"result": "x"}})

    store.create({**spec, "task_id": "t2", "profile": PROFILE})
    store.change_context("t2", {"source": "f", "engine": "torch", "model_family": "vision"})
    with pytest.raises(FlowError):
        flow.start(store, "t2", {"acceptance": {"result": "x"}})


def test_megatron_profile_keeps_the_exact_full_gates(tmp_path):
    store = setup(tmp_path)
    task = store.task("p")
    for destination, kinds in GATES.items():
        assert sorted(flow.required_reports(task, destination)) == sorted(kinds), destination
    decision = flow.next_step(store, "p")
    assert decision["profile"] == PROFILE
    assert sorted(decision["required_reports"]) == sorted(GATES["environment_checked"])


def test_adaptation_evidence_is_expected_but_never_a_gate(tmp_path):
    store = setup(tmp_path)
    task = store.task("p")
    expected = flow.expected_evidence(task, "environment_checked")
    assert expected == ["adaptation-diff", "adaptation-numerics", "adaptation-parity"]
    assert not set(expected) & set(flow.required_reports(task, "environment_checked"))
    # Advancing to profiling expects the short-baseline qualification record.
    assert flow.expected_evidence(task, "profiling") == ["baseline-qualification"]
    # Advancing to baseline_validated expects no extra evidence product.
    assert flow.expected_evidence(task, "baseline_validated") == []


def test_a_narrower_profile_narrows_only_the_stages_it_keeps(tmp_path, monkeypatch):
    narrow = Profile("narrow-fixture", {"engine": ("megatron",)}, stages=("prepared",),
                     modules=("environment.probe",))
    monkeypatch.setitem(catalog.PROFILES, narrow.id, narrow)
    store = setup(tmp_path, profile={"id": narrow.id, "reason": "fixture"})
    task = store.task("p")
    # Kept stage: exactly what the module set produces.
    assert flow.required_reports(task, "environment_checked") == ["environment"]
    # Stage outside the profile scope keeps the full gate instead of vanishing.
    assert flow.required_reports(task, "baseline_validated") == GATES["baseline_validated"]
    assert flow.required_reports(task, "completed") == GATES["completed"]


def test_a_profile_that_would_widen_a_gate_is_rejected(tmp_path, monkeypatch):
    store = setup(tmp_path)
    task = store.task("p")
    monkeypatch.setattr(flow, "profile_gates",
                        lambda _task: {"environment_checked": ["environment", "baseline"]})
    with pytest.raises(FlowError):
        flow.required_reports(task, "environment_checked")


def test_stage_plan_selects_the_modules_that_serve_it():
    built = catalog.build_plan(profile="llm-megatron", stage="prepared")
    assert built["stage"] == "prepared"
    assert {
        "environment.probe", "resource.admission", "resource.lease",
        "execution.command", "execution.stdout-json", "source.transfer",
        "adaptation.launch-parity", "adaptation.config-diff",
        "adaptation.numeric-equivalence",
    } == set(built["modules"])
    assert built["gates"] == {"environment_checked": ["environment"]}
    assert built["evidence_reports"] == ["adaptation-diff", "adaptation-numerics",
                                        "adaptation-parity"]
    assert built["name"].endswith(":stage-prepared")


def test_stage_plan_rejects_unknown_or_out_of_scope_stages():
    with pytest.raises(catalog.ModuleContractError):
        catalog.build_plan(profile="llm-megatron", stage="nonsense")
    with pytest.raises(catalog.ModuleContractError):
        catalog.build_plan(profile="analysis-only", stage="prepared")
    with pytest.raises(catalog.ModuleContractError):
        catalog.build_plan(modules=["quality.loss"], stage="prepared")


def test_module_plan_cli_accepts_stage(tmp_path):
    from hcu_trainflow.cli import main
    document = tmp_path / "plan.json"
    document.write_text(json.dumps({"profile": "llm-megatron",
                                    "capabilities": ["hardware", "lease", "task-bound"]}))
    assert main(["--workspace", str(tmp_path / "store"), "module-plan", str(document),
                 "--stage", "prepared"]) == 2  # planned, but inputs still come from the site
    assert main(["--workspace", str(tmp_path / "store"), "module-plan", str(document),
                 "--stage", "nonsense"]) == 1
