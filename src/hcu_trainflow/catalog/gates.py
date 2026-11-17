"""Derive stage gates from a module set instead of declaring them twice.

A sub-workflow never carries its own report list: the reports demanded when
leaving stage ``s`` are exactly the gate reports of the modules that declare
``s`` in ``stage``, plus the reports the candidate/review flow authors itself
(``stage-quality``, ``scale``, ``completion``).  The Flow state machine stays
authoritative; this module only reproduces what it already enforces.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from .contracts import AGENT_AUTHORED, EVIDENCE_REPORTS, FLOW_STAGES, GATE_REPORTS, Module
from . import registry


def source_stages() -> tuple[str, ...]:
    """Stages whose outgoing gate exists (``completed`` has no successor)."""

    return tuple(stage for stage in FLOW_STAGES if stage != "completed")


def next_stage(stage: str) -> str | None:
    from ..flow import NEXT
    return NEXT.get(stage)


def _entries(modules: Iterable[Module | str]) -> list[Module]:
    resolved = []
    for item in modules:
        resolved.append(registry.resolve(item) if isinstance(item, str) else item)
    return resolved


def stage_scope(modules: Iterable[Module | str]) -> tuple[str, ...]:
    """Every stage at least one module is scoped to, in flow order."""

    touched = {stage for module in _entries(modules) for stage in module.stage}
    return tuple(stage for stage in FLOW_STAGES if stage in touched)


def derive(modules: Iterable[Module | str],
           stages: Sequence[str] | None = None) -> dict[str, list[str]]:
    """Return ``{destination stage: sorted report kinds}`` for this module set.

    ``stages`` restricts the derivation to a sub-workflow's stage scope; the
    default covers every stage of the full flow.
    """

    entries = _entries(modules)
    selected = tuple(stages) if stages is not None else source_stages()
    unknown = set(selected) - set(source_stages())
    if unknown:
        raise ValueError("Unknown or terminal stages: " + ", ".join(sorted(unknown)))
    gates: dict[str, list[str]] = {}
    for stage in source_stages():
        if stage not in selected:
            continue
        destination = next_stage(stage)
        kinds = {module.report for module in entries
                 if module.report in GATE_REPORTS and stage in module.stage}
        kinds.update(AGENT_AUTHORED.get(stage, ()))
        if kinds:
            gates[destination] = sorted(kinds)
    return gates


def evidence_reports(modules: Iterable[Module | str]) -> list[str]:
    """Evidence products in the set; they never open a gate."""

    return sorted({module.report for module in _entries(modules)
                   if module.report in EVIDENCE_REPORTS})


def flow_gates() -> dict[str, list[str]]:
    from ..flow import GATES
    return {stage: list(kinds) for stage, kinds in GATES.items()}


def compare_to_flow(gates: Mapping[str, Sequence[str]]) -> dict[str, Any]:
    """Compare derived gates with the live Flow gates as sets per destination."""

    expected = {stage: set(kinds) for stage, kinds in flow_gates().items()}
    actual = {stage: set(kinds) for stage, kinds in gates.items()}
    differences = {}
    for stage in sorted(set(expected) | set(actual)):
        want, got = expected.get(stage, set()), actual.get(stage, set())
        if want != got:
            differences[stage] = {"flow": sorted(want), "derived": sorted(got)}
    return {"equal": not differences, "differences": differences}


def missing_producers(modules: Iterable[Module | str],
                      stages: Sequence[str] | None = None) -> list[str]:
    """Gate reports a stage demands that this set cannot produce.

    The union of the full catalog tells us what a stage needs; a subset that
    drops a producing module must not silently accept a thinner gate.  Reports
    authored by the candidate/review flow are excluded: they are never module
    products.
    """

    entries = _entries(modules)
    provided = {module.report for module in entries if module.report}
    selected = tuple(stages) if stages is not None else source_stages()
    gaps = []
    for stage in selected:
        demanded = {module.report for module in registry.modules()
                    if module.report in GATE_REPORTS and stage in module.stage}
        for kind in sorted(demanded - provided - set(AGENT_AUTHORED.get(stage, ()))):
            gaps.append(stage + ":" + kind)
    return gaps
