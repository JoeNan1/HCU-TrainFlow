"""Capability registration without importing optional integrations eagerly."""
from __future__ import annotations

from typing import Any

from ..kernel.contracts import Capability


class CapabilityRegistry:
    def __init__(self, capabilities: list[Capability] | None = None):
        self._items: dict[str, Capability] = {}
        for capability in capabilities or []:
            self.register(capability)

    def register(self, capability: Capability) -> Capability:
        name = getattr(capability, "name", None)
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Capability requires a nonempty name")
        if name in self._items:
            raise ValueError("Capability already registered: " + name)
        self._items[name] = capability
        return capability

    def resolve(self, name: str) -> Capability:
        try:
            return self._items[name]
        except KeyError:
            raise KeyError("Unknown capability: " + name) from None

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._items))


def default_registry() -> CapabilityRegistry:
    from .baseline import (ArtifactCollectionCapability, TorchTrainingSummaryCapability,
                           TrainingSummaryCapability)
    from .modules import (
        AdaptationDiffCapability,
        AdaptationNumericsCapability,
        AdaptationParityCapability,
        CommunicationCapability,
        OptimizationBenchmarkCapability,
        OptimizationChangeCapability,
        OptimizationNetgainCapability,
        ResourceLeaseCapability,
        SourceTransferCapability,
        StdoutJsonCapability,
    )
    from .scenarios import QualityAcceptanceCapability, TraceLensCapability
    from .builtin import (
        AdaptationCapability,
        DeliveryCapability,
        EnvironmentCapability,
        ExecutionCapability,
        OccupancyCapability,
        OptimizationCapability,
        ObservationCapability,
        ProfilingCapability,
        ProfilingPlanCapability,
        QualityCapability,
        QualityIterationCapability,
        QualityProxyCapability,
        ScaleAdmissionCapability,
    )
    return CapabilityRegistry([
        ArtifactCollectionCapability(), TrainingSummaryCapability(),
        TorchTrainingSummaryCapability(),
        AdaptationCapability(), DeliveryCapability(), EnvironmentCapability(),
        ExecutionCapability(), OccupancyCapability(), OptimizationCapability(),
        ObservationCapability(), ProfilingCapability(), ProfilingPlanCapability(),
        QualityCapability(), QualityIterationCapability(), QualityProxyCapability(),
        ScaleAdmissionCapability(),
        TraceLensCapability(), QualityAcceptanceCapability(),
        CommunicationCapability(), OptimizationBenchmarkCapability(),
        OptimizationChangeCapability(), OptimizationNetgainCapability(),
        ResourceLeaseCapability(), SourceTransferCapability(), StdoutJsonCapability(),
        AdaptationDiffCapability(), AdaptationNumericsCapability(), AdaptationParityCapability(),
    ])
