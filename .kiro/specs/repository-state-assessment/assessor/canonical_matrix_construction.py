"""Construct canonical parity rows from exact scoped-behavior evidence.

Rows are allocated before joins. Benchmark basis remains independent from Omni
status, and only explicit benchmark/capability/behavior keys can associate data.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import datetime

from .model_types import AssessmentStatus, SourceLocation, require_primary_status
from .parity_matrix import (
    BenchmarkSource,
    ParityBehaviorEvidence,
    apply_benchmark_source_decision,
    build_canonical_parity_matrix,
    derive_evidence_parity,
    select_benchmark_source,
)
from .report_models import BenchmarkSet, ParityMeasurement, ParityRow

_MEASUREMENT_DIMENSIONS = ("quality", "latency", "accuracy", "reliability", "platform breadth")
_CANONICAL_DIMENSIONS = {
    (BenchmarkSet.GRANOLA, "platform support"): ("platform breadth",),
    (BenchmarkSet.WISPR_FLOW, "latency"): ("latency",),
    (BenchmarkSet.WISPR_FLOW, "accuracy"): ("accuracy",),
    (BenchmarkSet.WISPR_FLOW, "platform support"): ("platform breadth",),
}


@dataclass(frozen=True, slots=True)
class ScopedBenchmarkSource:
    """A benchmark source explicitly assigned to one canonical row."""

    benchmark_set: BenchmarkSet
    benchmark_capability: str
    source: BenchmarkSource


@dataclass(frozen=True, slots=True)
class ScopedParityEvidence:
    """Claims, implementation, evidence, limits, and measurements for one behavior."""

    benchmark_set: BenchmarkSet
    benchmark_capability: str
    scoped_behavior: str
    omni_feature_name: str
    omni_documentary_claim_refs: tuple[str, ...]
    implementation_locations: tuple[SourceLocation, ...]
    primary_status: AssessmentStatus
    fresh_evidence_ref: str | None
    limitations: tuple[str, ...]
    quality_dimensions: tuple[str, ...]
    measurements: tuple[ParityMeasurement, ...]

    def __post_init__(self) -> None:
        """Reject ambiguous or untyped scoped join data."""
        require_primary_status(self.primary_status)
        if not self.benchmark_capability or not self.scoped_behavior or not self.omni_feature_name:
            raise ValueError("parity scope and feature name must not be empty")
        if any(not ref for ref in self.omni_documentary_claim_refs):
            raise ValueError("claim references must not be empty")
        if any(not limitation for limitation in self.limitations):
            raise ValueError("limitations must not be empty")
        if len(set(self.quality_dimensions)) != len(self.quality_dimensions):
            raise ValueError("quality dimensions must be unique within a behavior")
        if not set(self.quality_dimensions).issubset(_MEASUREMENT_DIMENSIONS):
            raise ValueError("quality dimension is not a supported typed parity dimension")
        supplied_dimensions = tuple(item.dimension for item in self.measurements)
        if len(set(supplied_dimensions)) != len(supplied_dimensions):
            raise ValueError("measurements must be unique within a behavior")
        if not set(supplied_dimensions).issubset(self.quality_dimensions):
            raise ValueError("every measurement requires an associated quality dimension")
        if self.primary_status is AssessmentStatus.VERIFIED_WORKING and not self.fresh_evidence_ref:
            raise ValueError("verified behavior requires a Fresh_Evidence reference")


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _locations(records: Iterable[ScopedParityEvidence]) -> tuple[SourceLocation, ...]:
    values = {location for record in records for location in record.implementation_locations}
    return tuple(sorted(values, key=lambda item: (item.path, item.start_line, item.end_line)))


def _dimensions(key: tuple[BenchmarkSet, str], records: Iterable[ScopedParityEvidence]) -> tuple[str, ...]:
    requested = set(_CANONICAL_DIMENSIONS.get(key, ()))
    requested.update(dimension for record in records for dimension in record.quality_dimensions)
    return tuple(dimension for dimension in _MEASUREMENT_DIMENSIONS if dimension in requested)


def _measurements(records: Iterable[ScopedParityEvidence]) -> tuple[ParityMeasurement, ...]:
    supplied: dict[str, ParityMeasurement] = {}
    for record in records:
        for measurement in record.measurements:
            if measurement.dimension in supplied:
                raise ValueError("a parity row may contain at most one measurement per dimension")
            supplied[measurement.dimension] = measurement
    return tuple(supplied[dimension] for dimension in _MEASUREMENT_DIMENSIONS if dimension in supplied)


def _unverified_measurements(dimensions: Iterable[str]) -> tuple[ParityMeasurement, ...]:
    return tuple(
        ParityMeasurement(dimension, None, AssessmentStatus.UNVERIFIED, None)
        for dimension in dimensions
    )

def construct_canonical_parity_matrix(
    scoped_evidence: Iterable[ScopedParityEvidence],
    scoped_sources: Iterable[ScopedBenchmarkSource],
    baseline_time: datetime,
    research_permitted: bool,
) -> tuple[ParityRow, ...]:
    """Build all rows, then join data only through explicit scoped behavior keys."""
    rows = build_canonical_parity_matrix()
    canonical = {(row.benchmark_set, row.benchmark_capability) for row in rows}
    evidence_by_row: dict[tuple[BenchmarkSet, str], list[ScopedParityEvidence]] = {}
    for record in scoped_evidence:
        if not isinstance(record, ScopedParityEvidence):
            raise TypeError("scoped_evidence must contain ScopedParityEvidence values")
        key = (record.benchmark_set, record.benchmark_capability)
        if key not in canonical:
            raise ValueError("scoped evidence does not target a canonical capability")
        evidence_by_row.setdefault(key, []).append(record)

    sources_by_row: dict[tuple[BenchmarkSet, str], list[BenchmarkSource]] = {}
    for scoped_source in scoped_sources:
        if not isinstance(scoped_source, ScopedBenchmarkSource):
            raise TypeError("scoped_sources must contain ScopedBenchmarkSource values")
        key = (scoped_source.benchmark_set, scoped_source.benchmark_capability)
        if key not in canonical:
            raise ValueError("scoped source does not target a canonical capability")
        sources_by_row.setdefault(key, []).append(scoped_source.source)

    completed: list[ParityRow] = []
    for row in rows:
        key = (row.benchmark_set, row.benchmark_capability)
        records = tuple(sorted(evidence_by_row.get(key, ()), key=lambda item: item.scoped_behavior))
        behaviors = tuple(record.scoped_behavior for record in records)
        if len(set(behaviors)) != len(behaviors):
            raise ValueError("a scoped behavior may be joined to a parity row only once")

        dimensions = _dimensions(key, records)
        if records:
            decision = derive_evidence_parity(
                benchmark_feature_name=row.benchmark_capability,
                omni_feature_name="; ".join(sorted({item.omni_feature_name for item in records})),
                behavior_evidence=tuple(
                    ParityBehaviorEvidence(item.scoped_behavior, item.primary_status, item.fresh_evidence_ref)
                    for item in records
                ),
                quality_dimensions=dimensions,
                measurements=_measurements(records),
            )
            joined_limitations = _unique(
                (decision.limitation,) + tuple(item for record in records for item in record.limitations)
            )
            row = replace(
                row,
                omni_documentary_claim_refs=_unique(
                    ref for record in records for ref in record.omni_documentary_claim_refs
                ),
                implementation_locations=_locations(records),
                fresh_evidence_refs=_unique(
                    tuple(item.fresh_evidence_ref for item in records if item.fresh_evidence_ref)
                    + tuple(item.evidence_ref for item in decision.measurements if item.evidence_ref)
                ),
                primary_status=decision.primary_status,
                limitation="; ".join(joined_limitations),
                parity_conclusion=decision.parity_conclusion,
                measurements=decision.measurements,
            )
        elif dimensions:
            row = replace(row, measurements=_unverified_measurements(dimensions))

        source_decision = select_benchmark_source(
            sources_by_row.get(key, ()), baseline_time, research_permitted
        )
        completed.append(apply_benchmark_source_decision(row, source_decision))

    return tuple(completed)
