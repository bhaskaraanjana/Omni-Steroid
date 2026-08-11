"""Examples for task 9.4 canonical scoped parity construction.

**Validates: Requirements 6.1–6.10**
"""

from datetime import date, datetime, timezone
from decimal import Decimal

from assessor import (
    AssessmentStatus, BenchmarkSet, BenchmarkSource, Measurement, MeasurementUnit,
    ParityMeasurement, ScopedBenchmarkSource, ScopedParityEvidence, SourceLocation,
    construct_canonical_parity_matrix,
)


def test_scoped_construction_keeps_basis_independent_and_never_name_joins() -> None:
    measured_latency = ParityMeasurement(
        "latency", Measurement("latency", Decimal("84"), MeasurementUnit.MILLISECONDS, "local dictation"),
        AssessmentStatus.VERIFIED_WORKING, "evidence-latency",
    )
    scoped = (
        ScopedParityEvidence(
            BenchmarkSet.GRANOLA, "live transcription", "streaming transcript", "speech transcription",
            ("claim-live",), (SourceLocation("engine/stt/live.py", 10, 20),),
            AssessmentStatus.VERIFIED_WORKING, "evidence-live", ("speaker labels unverified",),
            ("quality", "latency", "accuracy", "reliability", "platform breadth"), (measured_latency,),
        ),
        ScopedParityEvidence(
            BenchmarkSet.GRANOLA, "live transcription", "speaker labels", "speech transcription",
            (), (), AssessmentStatus.UNVERIFIED, None, ("no fresh speaker-label evidence",), (), (),
        ),
    )
    unavailable_research = ScopedBenchmarkSource(
        BenchmarkSet.GRANOLA, "live transcription",
        BenchmarkSource(SourceLocation("research/granola.md", 1, 5), date(2026, 7, 1), False),
    )

    rows = construct_canonical_parity_matrix(
        scoped, (unavailable_research,), datetime(2026, 7, 9, tzinfo=timezone.utc), False,
    )
    granola = next(row for row in rows if row.benchmark_set is BenchmarkSet.GRANOLA and row.benchmark_capability == "live transcription")
    wispr = next(row for row in rows if row.benchmark_set is BenchmarkSet.WISPR_FLOW and row.benchmark_capability == "speech transcription")

    assert len(rows) == 29
    assert granola.benchmark_basis_status is AssessmentStatus.UNVERIFIED
    assert granola.primary_status is AssessmentStatus.VERIFIED_PARTIAL
    assert granola.omni_documentary_claim_refs == ("claim-live",)
    assert granola.fresh_evidence_refs == ("evidence-live", "evidence-latency")
    assert {item.dimension: item.primary_status for item in granola.measurements} == {"quality": AssessmentStatus.UNVERIFIED, "latency": AssessmentStatus.VERIFIED_WORKING, "accuracy": AssessmentStatus.UNVERIFIED, "reliability": AssessmentStatus.UNVERIFIED, "platform breadth": AssessmentStatus.UNVERIFIED}
    assert "speaker labels" in granola.limitation and "benchmark basis" in granola.limitation.lower()
    assert wispr.primary_status is AssessmentStatus.UNVERIFIED
    assert wispr.omni_documentary_claim_refs == ()
