"""Property 13: Benchmark source selection is current and independent.

**Validates: Requirements 6.4, 6.5, 6.6**
"""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta, timezone

from assessor import (
    AssessmentStatus,
    BenchmarkSet,
    BenchmarkSource,
    ParityRow,
    SourceLocation,
    apply_benchmark_source_decision,
    select_benchmark_source,
)

_CASES = 128
_SEED = 20260709


def _source(index: int, published_on: date, *, repository: bool) -> BenchmarkSource:
    return BenchmarkSource(
        location=SourceLocation(f"sources/benchmark-{index}.md", index + 1, index + 1),
        published_on=published_on,
        available_in_repository=repository,
    )


def _omni_row() -> ParityRow:
    return ParityRow(
        row_id="Granola_Capability_Set-meeting-search",
        benchmark_set=BenchmarkSet.GRANOLA,
        benchmark_capability="meeting search",
        benchmark_source=SourceLocation("old.md", 1, 1),
        benchmark_source_date=date(2020, 1, 1),
        benchmark_basis_status=AssessmentStatus.HISTORICAL_ONLY,
        omni_documentary_claim_refs=("claim-1",),
        implementation_locations=(SourceLocation("engine/search.py", 10, 20),),
        fresh_evidence_refs=("evidence-1",),
        primary_status=AssessmentStatus.VERIFIED_PARTIAL,
        limitation="Omni search excludes archived meetings",
        parity_conclusion="Partial parity from fresh evidence",
        measurements=(),
    )


def _omni_projection(row: ParityRow) -> tuple[object, ...]:
    return (
        row.row_id,
        row.benchmark_set,
        row.benchmark_capability,
        row.omni_documentary_claim_refs,
        row.implementation_locations,
        row.fresh_evidence_refs,
        row.primary_status,
        row.parity_conclusion,
        row.measurements,
    )

def test_boundary_and_permission_examples_select_only_qualifying_sources() -> None:
    baseline = datetime(2026, 7, 9, 12, tzinfo=timezone.utc)
    sources = (
        _source(0, baseline.date() + timedelta(days=1), repository=True),
        _source(1, baseline.date(), repository=False),
        _source(2, baseline.date() - timedelta(days=365), repository=True),
        _source(3, baseline.date() - timedelta(days=366), repository=True),
    )

    repository_only = select_benchmark_source(sources, baseline, research_permitted=False)
    with_research = select_benchmark_source(sources, baseline, research_permitted=True)

    assert repository_only.source == sources[2]
    assert with_research.source == sources[1]
    assert repository_only.benchmark_basis_status is AssessmentStatus.VERIFIED_WORKING
    assert with_research.benchmark_basis_status is AssessmentStatus.VERIFIED_WORKING


def test_no_qualifying_source_marks_only_basis_unverified() -> None:
    baseline = datetime(2026, 7, 9, 12, tzinfo=timezone.utc)
    row = _omni_row()
    decision = select_benchmark_source(
        (_source(0, baseline.date(), repository=False),),
        baseline,
        research_permitted=False,
    )

    updated = apply_benchmark_source_decision(row, decision)

    assert decision.benchmark_basis_status is AssessmentStatus.UNVERIFIED
    assert updated.benchmark_source is None
    assert updated.benchmark_source_date is None
    assert updated.benchmark_basis_status is AssessmentStatus.UNVERIFIED
    assert "benchmark basis" in updated.limitation.lower()
    assert _omni_projection(updated) == _omni_projection(row)


def test_property_13_benchmark_source_selection_is_current_and_independent() -> None:
    """Exercise at least 100 source sets across date and permission boundaries."""
    rng = random.Random(_SEED)
    row = _omni_row()

    for case in range(_CASES):
        baseline = datetime(
            2022 + case % 7,
            1 + case % 12,
            1 + case % 27,
            case % 24,
            tzinfo=timezone(timedelta(minutes=rng.choice((-480, 0, 330, 600)))),
        )
        research_permitted = case % 2 == 0
        offsets = [-366, -365, 0, 1]
        offsets.extend(rng.randint(-500, 50) for _ in range(rng.randint(0, 12)))
        sources = [
            _source(
                index,
                baseline.date() + timedelta(days=offset),
                repository=rng.choice((True, False)),
            )
            for index, offset in enumerate(offsets)
        ]
        rng.shuffle(sources)

        qualifying = [
            source
            for source in sources
            if baseline.date() - timedelta(days=365)
            <= source.published_on
            <= baseline.date()
            and (source.available_in_repository or research_permitted)
        ]
        expected = max(
            qualifying,
            key=lambda source: (
                source.published_on,
                source.location.path,
                source.location.start_line,
                source.location.end_line,
            ),
            default=None,
        )

        decision = select_benchmark_source(sources, baseline, research_permitted)
        updated = apply_benchmark_source_decision(row, decision)

        assert decision.source == expected
        assert decision.source_date == (None if expected is None else expected.published_on)
        assert decision.benchmark_basis_status is (
            AssessmentStatus.UNVERIFIED
            if expected is None
            else AssessmentStatus.VERIFIED_WORKING
        )
        assert updated.benchmark_source == (None if expected is None else expected.location)
        assert updated.benchmark_source_date == decision.source_date
        assert _omni_projection(updated) == _omni_projection(row)

    assert _CASES >= 100
