"""Derive parity conclusions from evidence rather than from name similarity.

A conclusion is earned by matching scoped behavior and typed measurements. A missing
quality dimension stays an unverified measurement; it never becomes a silent pass and
never widens a partial result into a full one.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .model_types import AssessmentStatus, require_primary_status
from .report_models import ParityMeasurement


@dataclass(frozen=True, slots=True)
class ParityBehaviorEvidence:
    """Fresh evidence classification for one behavior represented by a parity row."""

    behavior: str
    primary_status: AssessmentStatus
    evidence_ref: str | None

    def __post_init__(self) -> None:
        require_primary_status(self.primary_status)
        if not self.behavior:
            raise ValueError("represented behavior must not be empty")
        if self.primary_status is AssessmentStatus.VERIFIED_WORKING and not self.evidence_ref:
            raise ValueError("a verified behavior requires a Fresh_Evidence reference")


@dataclass(frozen=True, slots=True)
class ParityConclusionDecision:
    """Structured conclusion with an exact supported/remainder partition."""

    primary_status: AssessmentStatus
    supported_subset: tuple[str, ...]
    remainder: tuple[ParityBehaviorEvidence, ...]
    limitation: str
    parity_conclusion: str
    measurements: tuple[ParityMeasurement, ...]

    def __post_init__(self) -> None:
        require_primary_status(self.primary_status)


def _quality_measurements(
    quality_dimensions: Iterable[str],
    measurements: Iterable[ParityMeasurement],
) -> tuple[ParityMeasurement, ...]:
    """Fill every missing quality dimension with an explicit Unverified result."""
    dimensions = tuple(quality_dimensions)
    if any(not dimension for dimension in dimensions) or len(set(dimensions)) != len(dimensions):
        raise ValueError("quality dimensions must be non-empty and unique")
    supplied = tuple(measurements)
    by_dimension = {measurement.dimension: measurement for measurement in supplied}
    if len(by_dimension) != len(supplied):
        raise ValueError("measurements must contain each dimension at most once")
    if not set(by_dimension).issubset(dimensions):
        raise ValueError("measurement dimension is not associated with this parity row")

    return tuple(
        by_dimension.get(
            dimension,
            ParityMeasurement(
                dimension=dimension,
                measurement=None,
                primary_status=AssessmentStatus.UNVERIFIED,
                evidence_ref=None,
            ),
        )
        for dimension in dimensions
    )


def derive_evidence_parity(
    *,
    benchmark_feature_name: str,
    omni_feature_name: str,
    behavior_evidence: Iterable[ParityBehaviorEvidence],
    quality_dimensions: Iterable[str] = (),
    measurements: Iterable[ParityMeasurement] = (),
) -> ParityConclusionDecision:
    """Derive parity solely from scoped evidence, never feature-name similarity."""
    if not benchmark_feature_name or not omni_feature_name:
        raise ValueError("feature names must not be empty")

    evidence = tuple(behavior_evidence)
    if not evidence:
        raise ValueError("parity conclusion requires represented behavior evidence")
    behaviors = tuple(item.behavior for item in evidence)
    if len(set(behaviors)) != len(behaviors):
        raise ValueError("represented behaviors must be unique")

    supported = tuple(
        item.behavior
        for item in evidence
        if item.primary_status is AssessmentStatus.VERIFIED_WORKING
    )
    remainder = tuple(
        item
        for item in evidence
        if item.primary_status is not AssessmentStatus.VERIFIED_WORKING
    )

    if len(supported) == len(evidence):
        status = AssessmentStatus.VERIFIED_WORKING
        conclusion = "Full parity for all represented behaviors from Fresh_Evidence."
    elif supported:
        status = AssessmentStatus.VERIFIED_PARTIAL
        conclusion = (
            f"Partial parity: {len(supported)} of {len(evidence)} represented "
            "behaviors verified by Fresh_Evidence."
        )
    else:
        status = AssessmentStatus.UNVERIFIED
        conclusion = "Parity is Unverified because no represented behavior is verified."

    supported_text = ", ".join(supported) or "none"
    remainder_text = ", ".join(
        f"{item.behavior} ({item.primary_status.value})" for item in remainder
    ) or "none"
    limitation = (
        f"Supported subset: [{supported_text}]; "
        f"unverified or failing remainder: [{remainder_text}]"
    )

    return ParityConclusionDecision(
        primary_status=status,
        supported_subset=supported,
        remainder=remainder,
        limitation=limitation,
        parity_conclusion=conclusion,
        measurements=_quality_measurements(quality_dimensions, measurements),
    )
