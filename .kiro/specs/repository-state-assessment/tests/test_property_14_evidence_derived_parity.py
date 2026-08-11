"""Property 14: Parity conclusions are evidence-derived.

**Validates: Requirements 6.7, 6.8, 6.9, 6.10**
"""

from __future__ import annotations

import random
from decimal import Decimal

from assessor import (
    AssessmentStatus,
    Measurement,
    MeasurementUnit,
    ParityBehaviorEvidence,
    ParityMeasurement,
    derive_evidence_parity,
)

_CASES = 128
_SEED = 20260710
_QUALITY_DIMENSIONS = (
    "quality",
    "latency",
    "accuracy",
    "reliability",
    "platform breadth",
)


def _measurement(case: int, dimension: str) -> ParityMeasurement:
    unit = (
        MeasurementUnit.MILLISECONDS
        if dimension == "latency"
        else MeasurementUnit.PERCENT
    )
    return ParityMeasurement(
        dimension=dimension,
        measurement=Measurement(
            name=dimension,
            value=Decimal(case + 1) / Decimal("10"),
            unit=unit,
            assessed_scope=f"generated scope {case}",
        ),
        primary_status=AssessmentStatus.VERIFIED_WORKING,
        evidence_ref=f"evidence-quality-{case}-{dimension}",
    )


def test_feature_presence_does_not_fill_an_unmeasured_quality_dimension() -> None:
    decision = derive_evidence_parity(
        benchmark_feature_name="Fast transcription",
        omni_feature_name="Unrelated local capability",
        behavior_evidence=(
            ParityBehaviorEvidence(
                "speech transcription",
                AssessmentStatus.VERIFIED_WORKING,
                "evidence-transcription",
            ),
        ),
        quality_dimensions=("latency",),
        measurements=(),
    )

    assert decision.primary_status is AssessmentStatus.VERIFIED_WORKING
    assert decision.supported_subset == ("speech transcription",)
    assert decision.remainder == ()
    assert decision.measurements == (
        ParityMeasurement(
            dimension="latency",
            measurement=None,
            primary_status=AssessmentStatus.UNVERIFIED,
            evidence_ref=None,
        ),
    )


def test_property_14_parity_conclusions_are_evidence_derived() -> None:
    """Exercise independent names, proper subsets, and missing dimensions."""
    rng = random.Random(_SEED)

    for case in range(_CASES):
        behavior_count = rng.randint(2, 9)
        behaviors = tuple(f"behavior-{case}-{index}" for index in range(behavior_count))
        supported_indices = set(
            rng.sample(range(behavior_count), rng.randint(1, behavior_count - 1))
        )
        behavior_evidence = tuple(
            ParityBehaviorEvidence(
                behavior=behavior,
                primary_status=(
                    AssessmentStatus.VERIFIED_WORKING
                    if index in supported_indices
                    else rng.choice(
                        (AssessmentStatus.UNVERIFIED, AssessmentStatus.FRESH_FAILURE)
                    )
                ),
                evidence_ref=f"evidence-{case}-{index}",
            )
            for index, behavior in enumerate(behaviors)
        )
        measured_dimensions = set(
            rng.sample(
                _QUALITY_DIMENSIONS,
                rng.randint(0, len(_QUALITY_DIMENSIONS) - 1),
            )
        )
        measurements = tuple(
            _measurement(case, dimension)
            for dimension in _QUALITY_DIMENSIONS
            if dimension in measured_dimensions
        )

        similar_names = derive_evidence_parity(
            benchmark_feature_name=f"Shared feature {case}",
            omni_feature_name=f"Shared feature {case}",
            behavior_evidence=behavior_evidence,
            quality_dimensions=_QUALITY_DIMENSIONS,
            measurements=measurements,
        )
        dissimilar_names = derive_evidence_parity(
            benchmark_feature_name=f"Benchmark alpha {case}",
            omni_feature_name=f"Omni unrelated omega 東京 {case}",
            behavior_evidence=behavior_evidence,
            quality_dimensions=_QUALITY_DIMENSIONS,
            measurements=measurements,
        )

        expected_supported = tuple(
            evidence.behavior
            for evidence in behavior_evidence
            if evidence.primary_status is AssessmentStatus.VERIFIED_WORKING
        )
        expected_remainder = tuple(
            evidence
            for evidence in behavior_evidence
            if evidence.primary_status is not AssessmentStatus.VERIFIED_WORKING
        )

        assert similar_names == dissimilar_names
        assert similar_names.primary_status is AssessmentStatus.VERIFIED_PARTIAL
        assert similar_names.supported_subset == expected_supported
        assert similar_names.remainder == expected_remainder
        assert set(similar_names.supported_subset).isdisjoint(
            evidence.behavior for evidence in similar_names.remainder
        )
        assert set(similar_names.supported_subset) | {
            evidence.behavior for evidence in similar_names.remainder
        } == set(behaviors)

        results_by_dimension = {
            result.dimension: result for result in similar_names.measurements
        }
        assert tuple(results_by_dimension) == _QUALITY_DIMENSIONS
        for dimension in _QUALITY_DIMENSIONS:
            result = results_by_dimension[dimension]
            if dimension in measured_dimensions:
                assert result == next(
                    item for item in measurements if item.dimension == dimension
                )
            else:
                assert result.measurement is None
                assert result.primary_status is AssessmentStatus.UNVERIFIED
                assert result.evidence_ref is None

    assert _CASES >= 100
