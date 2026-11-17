"""The module catalog must stay a single source of truth for gates and routes."""
import json

import pytest

from hcu_trainflow import catalog, flow
from hcu_trainflow.capabilities import default_registry
from hcu_trainflow.catalog.contracts import (EVIDENCE_REPORTS, FLOW_STAGES, GATE_REPORTS,
                                             Module, ModuleContractError, Profile)
from hcu_trainflow.core import GATES

EXPECTED_MODULES = {
    "environment.probe", "resource.admission", "resource.lease",
    "execution.command", "execution.stdout-json", "artifact.collect", "source.transfer",
    "adaptation.launch-parity", "adaptation.config-diff", "adaptation.numeric-equivalence",
    "training.summarize", "training.summarize-torch", "training.observe",
    "quality.loss", "quality.iteration",
    "quality.proxy", "quality.qualify",
    "profiling.trace", "profiling.analyze", "profiling.summarize", "profiling.communication",
    "optimization.change", "optimization.benchmark", "optimization.netgain",
}


def test_catalog_lists_the_documented_modules():
    assert {module.id for module in catalog.modules()} == EXPECTED_MODULES
    assert len(catalog.modules()) == 24
    catalog.validate_catalog()


def test_every_alias_and_preset_points_inside_the_catalog():
    for alias, target in catalog.aliases().items():
        assert target in {module.id for module in catalog.modules()}, alias
        assert catalog.resolve(alias).id == target
    for entry in catalog.subworkflows().values():
        for module_id in entry.modules:
            assert catalog.module(module_id).id == module_id
    with pytest.raises(ModuleContractError):
        catalog.resolve("not.a.module")


def test_every_module_route_is_a_real_docs_page():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    for module in catalog.modules():
        assert (root / module.route).is_file(), module.id


def test_every_module_is_executable_and_maps_to_a_registered_capability():
    registry = default_registry()
    for module in catalog.modules():
        assert module.executable, module.id + " has no implementation"
        capability, action = module.implementation
        assert capability in registry.names(), module.id
        assert action in registry.resolve(capability).actions(), module.id


def test_declared_volatility_covers_the_legacy_whitelist():
    """Module volatility must not be laxer than the hardcoded runtime rule."""

    from hcu_trainflow.kernel import PipelineStep
    from hcu_trainflow.services.runtime import RuntimeService
    for module in catalog.modules():
        capability, action = module.implementation
        step = PipelineStep(id=module.id, capability=capability, action=action)
        if RuntimeService._volatile(step):
            assert module.volatile, module.id + " is volatile at runtime but not in the catalog"


def test_stage_vocabulary_matches_the_flow_state_machine():
    assert tuple(FLOW_STAGES) == tuple(flow.NEXT) + ("completed",)
    for module in catalog.modules():
        assert set(module.stage) <= set(FLOW_STAGES)


def test_llm_megatron_derives_exactly_the_current_flow_gates():
    derived = catalog.derived_gates("llm-megatron")
    comparison = catalog.compare_to_flow(derived)
    assert comparison["equal"], comparison["differences"]
    assert {stage: sorted(kinds) for stage, kinds in derived.items()} == {
        stage: sorted(kinds) for stage, kinds in GATES.items()}


def test_profile_gates_are_a_subset_that_keeps_stage_evidence():
    full = catalog.derive([catalog.module(module.id) for module in catalog.modules()])
    for entry in catalog.profiles().values():
        gates = catalog.derived_gates(entry)
        assert set(gates) <= set(full), entry.id
        for stage, kinds in gates.items():
            assert set(kinds) <= set(full[stage]), entry.id + " " + stage
        assert catalog.missing_producers(
            [catalog.module(module_id) for module_id in entry.module_ids()], entry.stages) == []


def test_profiles_never_relax_an_agent_authored_gate():
    """thinning work may not thin the review conclusions a kept stage demands."""

    for entry in catalog.profiles().values():
        gates = catalog.derived_gates(entry)
        for stage in entry.stages:
            destination = flow.NEXT[stage]
            authored = set(catalog.AGENT_AUTHORED.get(stage, ()))
            if authored and destination in gates:
                assert authored <= set(gates[destination]), entry.id + " " + stage


def test_lightweight_profile_reads_much_less_than_the_full_catalog():
    full = catalog.route_surface([module.id for module in catalog.modules()])
    analysis = catalog.route_surface(catalog.profile("analysis-only").module_ids())
    vision = catalog.route_surface(catalog.profile("torch-native-vision").module_ids())
    assert analysis["share"] < 0.6
    assert vision["share"] < full["share"]
    assert full["count"] > analysis["count"]


def test_profile_schema_refuses_reports_gates_and_reading():
    document = catalog.profile("analysis-only").to_dict()
    for field in ("reports", "gates", "reading"):
        with pytest.raises(ModuleContractError):
            Profile.from_dict({**document, field: []})
    with pytest.raises(ModuleContractError):
        Profile.from_dict({**document, "surprise": 1})
    assert Profile.from_dict(document).id == "analysis-only"


def test_routing_maps_context_to_candidates():
    assert catalog.resolve_profile({"engine": "megatron", "model_family": "llm"})["profile"] == "llm-megatron"
    assert catalog.resolve_profile({"engine": "torch", "model_family": "llm"})["profile"] == "torch-native-llm"
    assert catalog.resolve_profile({"engine": "torch", "model_family": "video"})["profile"] == "torch-native-vision"
    assert catalog.resolve_profile({"mode": "diagnose"})["profile"] == "analysis-only"


def test_torch_native_profiles_keep_the_full_gates():
    for name in ("llm-megatron", "torch-native-llm", "torch-native-vision"):
        assert catalog.compare_to_flow(catalog.derived_gates(name))["equal"], name


def test_routing_lists_candidates_instead_of_guessing():
    result = catalog.resolve_profile({"mode": "analyze", "engine": "megatron", "model_family": "llm"})
    assert result["selection_required"] is True
    assert set(result["candidates"]) == {"llm-megatron", "analysis-only"}
    assert result["profile"] is None


def test_routing_halts_when_no_profile_matches():
    result = catalog.resolve_profile({"engine": "jax", "model_family": "llm"})
    assert result["status"] == "halt"
    assert result["halt_reason"] == "profile-unknown"
    assert result["candidates"] == []


def test_explicit_profile_conflict_is_rejected():
    with pytest.raises(ModuleContractError):
        catalog.resolve_profile({"engine": "torch", "model_family": "vision"}, "llm-megatron")
    chosen = catalog.resolve_profile({"engine": "torch", "model_family": "vision"},
                                     "torch-native-vision")
    assert chosen["reason"] == "explicit" and chosen["profile"] == "torch-native-vision"


def test_every_gate_report_has_one_producer_per_engine():
    producers = {}
    for module in catalog.modules():
        if module.report in GATE_REPORTS:
            producers.setdefault(module.report, []).append(module)
    assert {report: sorted(module.id for module in entries)
            for report, entries in producers.items()} == {
        "environment": ["environment.probe"],
        "baseline": ["training.summarize", "training.summarize-torch"],
        "analysis": ["profiling.analyze"],
        "performance": ["optimization.netgain"],
    }
    # The two baseline producers must be mutually exclusive by engine, so no
    # single run can ever hold both.
    baseline = producers["baseline"]
    engines = [set(module.tags["engine"]) for module in baseline]
    assert not (engines[0] & engines[1])
    derived = catalog.derived_gates("llm-megatron")
    gated = {kind for kinds in derived.values() for kind in kinds}
    assert not gated & set(EVIDENCE_REPORTS)


def test_profiles_never_list_conflicting_report_producers():
    for entry in catalog.profiles().values():
        records = [module.report for module in
                   (catalog.module(module_id) for module_id in entry.module_ids()) if module.report]
        assert len(set(records)) == len(records), entry.id
        gates = catalog.derived_gates(entry)
        assert set(gates) <= set(flow.GATES), entry.id


def test_evidence_reports_are_declared_but_never_open_a_gate():
    evidence = {module.report for module in catalog.modules()
                if module.report in EVIDENCE_REPORTS}
    assert evidence == {"baseline-qualification", "profile-summary", "optimization-change",
                        "adaptation-parity", "adaptation-diff", "adaptation-numerics"}
    for entry in catalog.profiles().values():
        gated = {kind for kinds in catalog.derived_gates(entry).values() for kind in kinds}
        assert not gated & evidence


def test_module_contract_rejects_unknown_vocabulary():
    with pytest.raises(ModuleContractError):
        Module(id="Bad Id", summary="x", actions=("run",), route="docs/quickstart.md")
    with pytest.raises(ModuleContractError):
        Module(id="a.b", summary="x", actions=("run",), role="wizard", route="docs/quickstart.md")
    with pytest.raises(ModuleContractError):
        Module(id="a.b", summary="x", actions=("run",), tags={"engine": ("cuda",)},
               route="docs/quickstart.md")
    with pytest.raises(ModuleContractError):
        Module(id="a.b", summary="x", actions=("run",), report="baseline", stage=(),
               route="docs/quickstart.md")
    with pytest.raises(ModuleContractError):
        Module(id="a.b", summary="x", actions=("run",), implementation=("cap", "other"),
               route="docs/quickstart.md")


def test_catalog_command_and_profile_commands_are_json_serializable(tmp_path):
    from hcu_trainflow import cli
    workspace = tmp_path / "store"
    assert cli.main(["--workspace", str(workspace), "module-catalog"]) == 0
    assert cli.main(["--workspace", str(workspace), "profile-list"]) == 0
    context = tmp_path / "context.json"
    context.write_text(json.dumps({"engine": "torch", "model_family": "vision"}))
    assert cli.main(["--workspace", str(workspace), "profile-resolve", str(context)]) == 0
    unknown = tmp_path / "unknown.json"
    unknown.write_text(json.dumps({"engine": "jax"}))
    assert cli.main(["--workspace", str(workspace), "profile-resolve", str(unknown)]) == 2
