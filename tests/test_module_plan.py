"""Automatic wiring is declared, validated and never guessed."""
import json

import pytest

from hcu_trainflow import catalog
from hcu_trainflow.catalog.contracts import ModuleContractError
from hcu_trainflow.kernel import PipelinePlan

CANNOT_QUALIFY = {"profile": {"status": "complete"}, "normalized_artifact": "sha",
                  "training": {"status": "pass"}, "environment": {"status": "pass"}}


def kinds(built):
    return sorted({problem["kind"] for problem in built["problems"]})


def test_unique_provider_is_wired_automatically():
    built = catalog.build_plan(modules=["profiling.summarize", "quality.qualify"],
                               inputs=dict(CANNOT_QUALIFY))
    assert built["status"] == "pass", built["problems"]
    qualify = next(step for step in built["plan"]["steps"] if step["id"] == "quality.qualify")
    assert qualify["bindings"] == {"analysis": {"step": "profiling.summarize", "path": ["analysis"]}}
    assert qualify["depends_on"] == ["profiling.summarize"]
    assert qualify["config"] == {"report_kind": "baseline-qualification"}
    PipelinePlan.from_dict(built["plan"])


def test_two_providers_are_reported_not_guessed():
    built = catalog.build_plan(
        modules=["profiling.analyze", "profiling.summarize", "quality.qualify"],
        inputs={**CANNOT_QUALIFY, "trace": "trace.json", "window": {"start": 1}})
    assert built["status"] == "incomplete"
    ambiguous = [problem for problem in built["problems"] if problem["kind"] == "ambiguous-input"]
    assert ambiguous and ambiguous[0]["input"] == "analysis"
    assert set(ambiguous[0]["candidates"]) == {"profiling.analyze", "profiling.summarize"}


def test_explicit_binding_resolves_the_ambiguity():
    built = catalog.build_plan(
        modules=["profiling.analyze", "profiling.summarize", "quality.qualify"],
        inputs={**CANNOT_QUALIFY, "trace": "trace.json", "window": {"start": 1}},
        bindings={"quality.qualify.analysis": {"step": "profiling.summarize", "path": ["analysis"]}})
    assert built["status"] == "pass", built["problems"]


def test_missing_inputs_and_unsatisfied_needs_are_listed():
    built = catalog.build_plan(modules=["training.summarize", "execution.command"])
    assert "missing-input" in kinds(built)
    needs = [problem for problem in built["problems"] if problem["kind"] == "unsatisfied-need"]
    assert {problem["module"] for problem in needs} == {"training.summarize", "execution.command"}
    satisfied = catalog.build_plan(modules=["execution.command"],
                                   capabilities=["hardware", "lease", "task-bound"],
                                   inputs={"card": {}, "operation": "op", "lease": {}})
    assert satisfied["status"] == "pass", satisfied["problems"]


def test_a_thinned_stage_cannot_hide_a_dropped_report():
    built = catalog.build_plan(modules=["environment.probe"], stages=["baseline_validated"],
                               inputs={"contract": {"context": "c"}, "observations": []})
    dropped = [problem for problem in built["problems"]
               if problem["kind"] == "stage-evidence-dropped"]
    assert dropped and dropped[0]["report"] == "baseline"


def test_duplicate_or_alias_collapsed_modules_are_rejected():
    with pytest.raises(ModuleContractError):
        catalog.build_plan(modules=["environment.probe", "environment.check"])
    with pytest.raises(ModuleContractError):
        catalog.build_plan(modules=["not.a.module"])


def test_unknown_document_fields_are_rejected():
    with pytest.raises(ModuleContractError):
        catalog.build_plan(document={"modules": ["environment.probe"], "reports": ["environment"]})
    with pytest.raises(ModuleContractError):
        catalog.build_plan(document={"profile": "llm-megatron", "modules": ["environment.probe"]})


def test_step_inputs_seed_one_module_without_leaking_to_others():
    built = catalog.build_plan(
        subworkflow="adaptation",
        inputs={"upstream": {"argv": ["a"]}, "hcu": {"argv": ["a"]},
                "mapping": [{"upstream": "a", "hcu": "a", "basis": "same"}],
                "contract": {"context": "c"}},
        step_inputs={"adaptation.config-diff.baseline": {"tp": 8},
                     "adaptation.config-diff.adapted": {"tp": 4},
                     "adaptation.config-diff.basis": {"tp": "x"},
                     "adaptation.numeric-equivalence.baseline":
                         {"components": {"forward": [1.0]}},
                     "adaptation.numeric-equivalence.candidate":
                         {"components": {"forward": [1.0]}}})
    assert built["status"] == "pass", built["problems"]
    steps = {step["id"]: step for step in built["plan"]["steps"]}
    assert steps["adaptation.config-diff"]["inputs"]["baseline"] == {"tp": 8}
    assert steps["adaptation.numeric-equivalence"]["inputs"]["baseline"] == {
        "components": {"forward": [1.0]}}
    assert steps["adaptation.launch-parity"]["inputs"] == {}
    PipelinePlan.from_dict(built["plan"])
    with pytest.raises(ModuleContractError):
        catalog.build_plan(document={"modules": ["environment.probe"],
                                     "step_inputs": {"no-dot-here": 1}})


def test_profile_plan_reports_derived_gates_and_flow_comparison():
    built = catalog.build_plan(profile="analysis-only")
    assert built["gates"] == {"optimizing": ["analysis"]}
    assert built["stage_scope_declared"] is True
    assert built["evidence_reports"] == []
    from hcu_trainflow import flow
    assert set(built["gates"]["optimizing"]) <= set(flow.GATES["optimizing"])


def test_baseline_preset_reproduces_the_published_wiring():
    plan = catalog.preset_plan("baseline-pipeline", {
        "environment": {"contract": {"context": "ctx"}}, "training": {"operation": "t"},
        "training_contract": {"context": "ctx"}, "profiling": {"operation": "p"},
        "project": "/repo"})
    assert plan.name == "fresh-baseline-closed-loop"
    assert [(step.id, step.capability, step.action) for step in plan.steps] == [
        ("environment", "environment.check", "collect"),
        ("training", "execution.command", "run"),
        ("training-summary", "training.summarize", "parse"),
        ("profile-capture", "execution.command", "run"),
        ("profile-files", "artifact.collect", "retain"),
        ("tracelens", "profiling.tracelens", "analyze"),
        ("analysis", "profiling.analyze", "summarize"),
        ("qualification", "quality.accept", "qualify"),
    ]
    assert plan.steps[1].inputs == {"operation": "t"}
    assert plan.steps[5].inputs == {"project": "/repo", "mode": "hipprof", "trace_format": "json"}
    assert plan.steps[7].depends_on == ("environment", "training-summary", "analysis")


def test_baseline_preset_requires_its_site_inputs():
    with pytest.raises(ModuleContractError):
        catalog.preset_plan("baseline-pipeline", {"environment": {}})


def test_module_plan_cli_reports_status(tmp_path):
    from hcu_trainflow import cli
    workspace = tmp_path / "store"
    document = tmp_path / "plan.json"
    document.write_text(json.dumps({"modules": ["profiling.summarize", "quality.qualify"],
                                    "inputs": CANNOT_QUALIFY}))
    assert cli.main(["--workspace", str(workspace), "module-plan", str(document)]) == 0
    document.write_text(json.dumps({"modules": ["training.summarize"]}))
    assert cli.main(["--workspace", str(workspace), "module-plan", str(document)]) == 2
