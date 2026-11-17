"""Adaptation modules report what is traceable, never that a port works."""
import json

import pytest

from hcu_trainflow import catalog
from hcu_trainflow.capabilities import default_registry
from hcu_trainflow.core import Store
from hcu_trainflow.kernel import CapabilityContext, CapabilityRequest

CONTEXT = "adapt-ctx"


def invoke(store, name, inputs, action=None):
    capability = default_registry().resolve(name)
    context = CapabilityContext("adapt-task", CONTEXT, store.root)
    return capability.run(context, CapabilityRequest(name, action or capability.actions()[0], inputs))


def raw(store):
    return store.put(b"synthetic launch/tensor record")


def test_launch_parity_requires_every_upstream_element_to_be_mapped(tmp_path):
    store = Store(tmp_path / "store")
    sha = raw(store)
    upstream = {"argv": ["python", "pretrain_gpt.py", "--tensor-model-parallel-size", "8"],
                "env": {"MASTER_PORT": "6000"}, "config": {"hidden_size": 4096}}
    hcu = {"argv": ["torchrun", "--tp", "8"],
           "env": {"MASTER_PORT": "6000"}, "config": {"hidden_size": 4096}}
    mapping = [{"upstream": "pretrain_gpt.py", "hcu": "torchrun", "basis": "launcher"},
               {"upstream": "--tensor-model-parallel-size", "hcu": "--tp", "basis": "flag rename"},
               {"upstream": "MASTER_PORT", "hcu": "MASTER_PORT", "basis": "same"},
               {"upstream": "hidden_size", "hcu": "hidden_size", "basis": "same"}]
    result = invoke(store, "adaptation.launch-parity",
                    {"upstream": upstream, "hcu": hcu, "mapping": mapping, "evidence": [sha]})
    # Every argv token is an element, including bare values: "python" and the
    # "8" value have no declared counterpart.
    assert result.status == "incomplete"
    assert result.outputs["unmatched_upstream"] == ["8", "python"]
    assert "upstream-element-without-mapping:python" in result.outputs["required_missing"]
    assert result.outputs["executed"] == 4

    complete = invoke(store, "adaptation.launch-parity", {
        "upstream": {"argv": ["torchrun"], "env": {}, "config": {}},
        "hcu": {"argv": ["torchrun"], "env": {}, "config": {}},
        "mapping": [{"upstream": "torchrun", "hcu": "torchrun", "basis": "same"}],
        "evidence": [sha]})
    assert complete.status == "complete", complete.outputs["required_missing"]


def test_launch_parity_rejects_untraceable_or_duplicated_mappings(tmp_path):
    store = Store(tmp_path / "store")
    sha = raw(store)
    record = {"argv": ["a", "b"], "env": {}, "config": {}}
    no_basis = invoke(store, "adaptation.launch-parity", {
        "upstream": record, "hcu": record, "evidence": [sha],
        "mapping": [{"upstream": "a", "hcu": "a", "basis": ""},
                    {"upstream": "b", "hcu": "b", "basis": "same"}]})
    assert no_basis.status == "incomplete"
    assert "mapping-without-basis:a" in no_basis.outputs["required_missing"]

    duplicated = invoke(store, "adaptation.launch-parity", {
        "upstream": record, "hcu": record, "evidence": [sha],
        "mapping": [{"upstream": "a", "hcu": "x", "basis": "same"},
                    {"upstream": "b", "hcu": "x", "basis": "same"}]})
    assert "duplicate-hcu-mapping:x" in duplicated.outputs["required_missing"]

    without_evidence = invoke(store, "adaptation.launch-parity", {
        "upstream": record, "hcu": record,
        "mapping": [{"upstream": "a", "hcu": "a", "basis": "same"},
                    {"upstream": "b", "hcu": "b", "basis": "same"}]})
    assert without_evidence.status == "incomplete"
    assert "raw-launch-evidence-required" in without_evidence.outputs["required_missing"]


def test_config_diff_names_every_unexplained_change(tmp_path):
    store = Store(tmp_path / "store")
    result = invoke(store, "adaptation.config-diff", {
        "baseline": {"hidden_size": 4096, "tp": 8, "fp16": False},
        "adapted": {"hidden_size": 4096, "tp": 4, "fp16": True, "device": "hcu"},
        "basis": {"tp": "device count", "fp16": "hcbn support"}})
    assert result.status == "incomplete"
    assert result.outputs["unexplained"] == ["device"]
    assert "unexplained-change:device" in result.outputs["required_missing"]
    assert result.outputs["changed"]["tp"] == {"baseline": 8, "adapted": 4,
                                               "basis": "device count"}
    assert result.outputs["added"] == ["device"]
    assert result.evidence  # the record itself is retained for review

    explained = invoke(store, "adaptation.config-diff", {
        "baseline": {"tp": 8}, "adapted": {"tp": 4},
        "basis": {"tp": "device count"}})
    assert explained.status == "complete"


def test_config_diff_rejects_basis_for_an_unchanged_key(tmp_path):
    store = Store(tmp_path / "store")
    with pytest.raises(ValueError):
        invoke(store, "adaptation.config-diff", {
            "baseline": {"tp": 8}, "adapted": {"tp": 4},
            "basis": {"tp": "device count", "hidden_size": "not changed"}})
    empty = invoke(store, "adaptation.config-diff",
                   {"baseline": {"tp": 8}, "adapted": {"tp": 8}, "basis": {}})
    assert empty.status == "incomplete"
    assert empty.outputs["required_missing"] == ["empty-diff"]


def contract(**overrides):
    value = {"context": CONTEXT,
             "components": [{"name": "forward", "tolerance": 1e-4},
                            {"name": "grad", "tolerance": 1e-3}]}
    value.update(overrides)
    return value


def test_component_numerics_are_local_evidence(tmp_path):
    store = Store(tmp_path / "store")
    sha = raw(store)
    record = {"components": {"forward": [1.0, 2.0, 3.0], "grad": [0.5, 0.25]},
              "evidence": [sha]}
    result = invoke(store, "adaptation.numeric-equivalence",
                    {"contract": contract(), "baseline": record, "candidate": record,
                     "evidence": [sha]})
    assert result.status == "pass"
    assert result.outputs["executed"] == 2
    assert result.outputs["stage_equivalent"] is False
    assert all(row["within_tolerance"] for row in result.outputs["components"])

    drifted = {"components": {"forward": [1.0, 2.0, 3.5], "grad": [0.5, 0.25]},
               "evidence": [sha]}
    failed = invoke(store, "adaptation.numeric-equivalence",
                    {"contract": contract(), "baseline": record, "candidate": drifted,
                     "evidence": [sha]})
    assert failed.status == "fail"
    assert failed.outputs["failures"] == ["forward-differs-beyond-tolerance"]


def test_component_numerics_report_missing_pieces_instead_of_passing(tmp_path):
    store = Store(tmp_path / "store")
    sha = raw(store)
    baseline = {"components": {"forward": [1.0, 2.0], "grad": [0.5]}, "evidence": [sha]}
    missing_component = {"components": {"forward": [1.0, 2.0]}, "evidence": [sha]}
    result = invoke(store, "adaptation.numeric-equivalence",
                    {"contract": contract(), "baseline": baseline,
                     "candidate": missing_component, "evidence": [sha]})
    assert result.status == "incomplete"
    assert "grad-component-absent" in result.outputs["required_missing"]

    shorter = {"components": {"forward": [1.0], "grad": [0.5]}, "evidence": [sha]}
    length = invoke(store, "adaptation.numeric-equivalence",
                    {"contract": contract(), "baseline": baseline, "candidate": shorter,
                     "evidence": [sha]})
    assert "forward-length-mismatch" in length.outputs["required_missing"]

    no_evidence = invoke(store, "adaptation.numeric-equivalence",
                         {"contract": contract(), "baseline": baseline,
                          "candidate": baseline})
    assert no_evidence.status == "incomplete"
    assert "raw-tensor-evidence-required" in no_evidence.outputs["required_missing"]

    with pytest.raises(ValueError):
        invoke(store, "adaptation.numeric-equivalence",
               {"contract": contract(context="other"), "baseline": baseline,
                "candidate": baseline, "evidence": [sha]})


def test_adaptation_subworkflow_plans_and_never_opens_a_gate():
    built = catalog.build_plan(
        subworkflow="adaptation",
        inputs={"upstream": {"argv": ["a"]}, "hcu": {"argv": ["a"]},
                "mapping": [{"upstream": "a", "hcu": "a", "basis": "same"}],
                "contract": {"context": "c"}},
        # Two modules both want "baseline": the seeded values must differ, so
        # they are declared per step instead of shared.
        step_inputs={"adaptation.config-diff.baseline": {"tp": 8},
                     "adaptation.config-diff.adapted": {"tp": 4},
                     "adaptation.config-diff.basis": {"tp": "x"},
                     "adaptation.numeric-equivalence.baseline":
                         {"components": {"forward": [1.0]}},
                     "adaptation.numeric-equivalence.candidate":
                         {"components": {"forward": [1.0]}}})
    assert built["status"] == "pass", built["problems"]
    assert built["gates"] is None
    assert built["modules"] == ["adaptation.launch-parity", "adaptation.config-diff",
                                "adaptation.numeric-equivalence"]
    assert built["evidence_reports"] == ["adaptation-diff", "adaptation-numerics",
                                        "adaptation-parity"]
    # None of the adaptation reports appear in any profile gate.
    for entry in catalog.profiles().values():
        gated = {kind for kinds in catalog.derived_gates(entry).values() for kind in kinds}
        assert not gated & {"adaptation-parity", "adaptation-diff", "adaptation-numerics"}


def test_adaptation_reports_are_registered_on_a_task(tmp_path):
    from hcu_trainflow.modular_cli import module_run
    store = Store(tmp_path / "store")
    task = store.create({"schema_version": 1, "task_id": "adapt", "mode": "adapt",
                         "objective": "adaptation evidence", "context": {"source": "fixture"},
                         "permissions": ["execute"],
                         "budget": {"max_operations": 2, "max_seconds": 60}})
    result = module_run(store, {
        "subworkflow": "adaptation",
        "inputs": {
            "upstream": {"argv": ["a"]}, "hcu": {"argv": ["a"]},
            "mapping": [{"upstream": "a", "hcu": "a", "basis": "same"}],
            "contract": {"context": task["context"],
                         "components": [{"name": "forward", "tolerance": 1e-4}]},
        },
        "step_inputs": {
            "adaptation.config-diff.baseline": {"tp": 8},
            "adaptation.config-diff.adapted": {"tp": 4},
            "adaptation.config-diff.basis": {"tp": "device count"},
            "adaptation.numeric-equivalence.baseline": {"components": {"forward": [1.0]}},
            "adaptation.numeric-equivalence.candidate": {"components": {"forward": [1.0]}},
        },
    }, task_id=task["id"])
    assert result["steps"]["adaptation.config-diff"]["status"] == "complete"
    assert result["steps"]["adaptation.launch-parity"]["status"] == "incomplete"
    assert "adaptation.config-diff" in result["reports"]
