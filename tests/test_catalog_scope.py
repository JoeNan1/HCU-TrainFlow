"""Catalog invariants that keep a profile, its modules and its wiring coherent.

Three failures this file locks down, all found by auditing the catalog rather
than by a failing run:

* a profile may not list a module that serves none of its declared stages, or a
  stage slice silently drops the module the profile promised;
* a whole-profile plan may not carry an ambiguous input, or "pick a profile and
  run it" never reaches ``pass`` and needs a hand-written binding to work;
* the legacy preset spellings must keep resolving, including the second half of
  a slash-joined alias such as ``quality.accept/assess``.
"""
import pytest

from hcu_trainflow import catalog
from hcu_trainflow.catalog.contracts import ModuleContractError, Profile

CAPABILITIES = ["hardware", "lease", "task-bound"]


def test_every_profile_member_serves_one_of_its_declared_stages():
    for entry in catalog.profiles().values():
        for module_id in entry.module_ids():
            stages = set(catalog.module(module_id).stage)
            assert stages & set(entry.stages), entry.id + " lists " + module_id


def test_profile_scope_check_rejects_a_member_outside_the_declared_stages():
    entry = Profile("bad-scope", applies_to={"engine": ("torch",)},
                    modules=("environment.probe", "profiling.analyze"),
                    stages=("profiling",))
    with pytest.raises(ModuleContractError) as raised:
        catalog.validate_scope(entry)
    assert "environment.probe" in str(raised.value)


def test_whole_profile_plans_have_no_ambiguous_input():
    for name in catalog.profiles():
        built = catalog.build_plan(profile=name, capabilities=CAPABILITIES)
        ambiguous = [problem for problem in built["problems"]
                     if problem["kind"] in {"ambiguous-input", "stage-evidence-dropped"}]
        assert ambiguous == [], (name, ambiguous)


def test_analysis_only_only_lists_read_only_modules_it_can_run():
    entry = catalog.profile("analysis-only")
    assert set(entry.module_ids()) == {
        "execution.command", "execution.stdout-json", "artifact.collect",
        "profiling.trace", "profiling.analyze"}
    assert catalog.derived_gates(entry) == {"optimizing": ["analysis"]}
    # The environment probe and the source snapshot belong to ``prepared``; they
    # stay available as standalone modules but cannot live in this scope.
    assert not {"environment.probe", "source.transfer"} & set(entry.module_ids())


@pytest.mark.parametrize("legacy,expected", [
    ("quality.accept", "quality-accept"),
    ("quality.assess", "quality-accept"),
    ("quality.accept/assess", "quality-accept"),
    ("profiling.tracelens", "profiling-tracelens"),
    ("environment.collect", "environment-collect"),
])
def test_legacy_preset_names_still_resolve(legacy, expected):
    assert catalog.subworkflow(legacy).id == expected
    assert catalog.select(subworkflow=legacy)["name"] == "subworkflow:" + expected


def test_unknown_subworkflow_still_raises():
    with pytest.raises(ModuleContractError):
        catalog.subworkflow("quality.qualify")
