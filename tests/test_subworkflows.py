"""Functional subworkflows are module combinations, not shortened processes."""
import pytest

from hcu_trainflow import catalog
from hcu_trainflow.catalog.contracts import ModuleContractError, Profile, Subworkflow


def test_subworkflows_declare_no_stages_and_no_gates():
    for entry in catalog.subworkflows().values():
        payload = entry.to_dict()
        assert set(payload) == {"id", "summary", "modules", "kind", "bundled",
                                "declarative", "notes"}
        assert "stages" not in payload and "gates" not in payload


def test_interface_is_the_external_surface_of_the_composition():
    baseline = catalog.interface(catalog.subworkflow("baseline-megatron").modules)
    # The execution result is consumed internally: training.summarize binds the
    # whole execution.command result, so it is not an external input.
    assert "execution" not in baseline["requires"]
    assert set(baseline["requires"]) == {"card", "operation", "lease", "contract", "files"}
    assert baseline["reports"] == ["baseline"]
    assert baseline["evidence"] == ["training.summarize"]


def test_alternative_types_of_the_same_input_are_reported_together():
    readiness = catalog.interface(catalog.subworkflow("environment-readiness").modules)
    assert readiness["requires"]["contract"] == "occupancy-contract|environment-contract"
    assert set(readiness["requires"]) == {"contract", "observations", "resource", "owner", "ttl"}


def test_composition_subworkflow_auto_wires_and_runs_as_a_plan():
    built = catalog.build_plan(subworkflow="baseline-megatron",
                               capabilities=["hardware", "lease", "task-bound"],
                               inputs={"card": {}, "operation": "op", "lease": {},
                                       "contract": {"context": "c"}, "files": {}})
    assert built["status"] == "pass", built["problems"]
    assert built["name"] == "subworkflow:baseline-megatron"
    assert built["gates"] is None  # a subworkflow never carries a stage scope
    training = next(step for step in built["plan"]["steps"] if step["id"] == "training.summarize")
    assert training["bindings"] == {"execution": {"step": "execution.command", "path": []}}
    assert training["depends_on"] == ["execution.command"]


def test_template_subworkflow_keeps_its_fixed_wiring():
    plan = catalog.subworkflow_plan("baseline-pipeline", {
        "environment": {}, "training": {}, "training_contract": {},
        "profiling": {}, "project": "/repo"})
    assert plan.name == "fresh-baseline-closed-loop"
    assert plan.steps[2].bindings == {"execution": {"step": "training", "path": []}}


def test_composition_without_declarative_steps_cannot_be_planned_as_template():
    with pytest.raises(ModuleContractError):
        catalog.subworkflow_plan("baseline-megatron", {})


def test_composition_subworkflows_reject_conflicting_report_producers():
    conflicting = Subworkflow("both-baselines", "conflict",
                              ("training.summarize", "training.summarize-torch"))
    with pytest.raises(ModuleContractError):
        catalog.validate_subworkflow(conflicting)
    with pytest.raises(ModuleContractError):
        catalog.validate_subworkflow(Subworkflow("ghost", "unknown", ("not.a.module",)))


def test_profiles_compose_subworkflows_instead_of_listing_modules():
    llm = catalog.profile("llm-megatron")
    assert llm.subworkflows and not llm.modules
    assert len(llm.module_ids()) == 23
    assert "training.summarize-torch" not in llm.module_ids()
    torch_llm = catalog.profile("torch-native-llm")
    assert "training.summarize-torch" in torch_llm.module_ids()
    assert "training.summarize" not in torch_llm.module_ids()
    # analysis-only stays an explicit module list: it has no functional pairing.
    assert catalog.profile("analysis-only").modules
    assert not catalog.profile("analysis-only").subworkflows


def test_profile_must_declare_modules_or_subworkflows_not_both():
    with pytest.raises(ModuleContractError):
        Profile("x-y", {"mode": ("analyze",)}, ("prepared",),
                modules=("environment.probe",), subworkflows=("source-handoff",))
    with pytest.raises(ModuleContractError):
        Profile("x-y", {"mode": ("analyze",)}, ("prepared",))


def test_subworkflow_list_cli_reports_interfaces(tmp_path):
    from hcu_trainflow import cli
    assert cli.main(["--workspace", str(tmp_path / "store"), "subworkflow-list"]) == 0
    assert cli.main(["--workspace", str(tmp_path / "store"), "module-catalog"]) == 0


def test_a_functional_subworkflow_runs_end_to_end_through_module_run(tmp_path):
    from hcu_trainflow.core import Store
    from hcu_trainflow.modular_cli import module_run

    store = Store(tmp_path / "store")
    task = store.create({"schema_version": 1, "task_id": "sw", "mode": "analyze",
                         "objective": "functional subworkflow", "context": {"source": "fixture"},
                         "permissions": ["execute"],
                         "budget": {"max_operations": 2, "max_seconds": 60}})
    raw = store.put(b"synthetic loss series")
    contract = {"context": task["context"], "sample_fingerprint": "frozen-sample",
                "aggregation": "mean", "initial_state_fingerprint": "state",
                "training_recipe_fingerprint": "recipe", "min_steps": 3, "atol": 0.01,
                "rtol": 0.0, "tolerance_basis": "synthetic test contract"}
    record = {key: contract[key] for key in ("context", "sample_fingerprint", "aggregation",
                                            "initial_state_fingerprint",
                                            "training_recipe_fingerprint")}
    record.update(steps=[1, 2, 3], loss=[2.0, 1.9, 1.8], executed=3, evidence=[raw],
                  candidate_path_exercised=True)
    correctness = dict(record, profiler_off=True,
                       measurement_protocol={"max_relative_mad": 0.1})
    result = module_run(store, {
        "subworkflow": "quality-accept",
        "inputs": {"contract": contract, "baseline": dict(record), "candidate": dict(record),
                   "correctness": correctness, "baseline_times": [10, 10, 10],
                   "candidate_times": [9, 9, 9]},
    }, task_id=task["id"])
    assert result["status"] == "complete", result["steps"]
    assert result["modules"] == ["quality.loss", "quality.iteration"]
    assert result["gates"] is None
    assert result["steps"]["quality.loss"]["status"] == "pass"
    assert result["steps"]["quality.iteration"]["status"] == "pass"


def test_every_module_belongs_to_at_least_one_subworkflow():
    covered = {module_id for entry in catalog.subworkflows().values()
               for module_id in entry.modules}
    assert {module.id for module in catalog.modules()} <= covered
