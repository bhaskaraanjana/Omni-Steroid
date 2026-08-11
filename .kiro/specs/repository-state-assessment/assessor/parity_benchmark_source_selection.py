"""Select the one current, independent benchmark source a parity row may cite.

A source qualifies only while it is current and independently published. When none
qualifies, only the benchmark basis is marked unverified — the product's own
evaluation continues rather than being withheld for want of a competitor citation.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta

from .model_types import AssessmentStatus, SourceLocation
from .report_models import ParityRow


@dataclass(frozen=True, slots=True)
class BenchmarkSource:
    """One dated benchmark source and how it is available to the assessment."""

    location: SourceLocation
    published_on: date
    available_in_repository: bool

    def __post_init__(self) -> None:
        if not isinstance(self.location, SourceLocation):
            raise TypeError("location must be a SourceLocation")
        if type(self.published_on) is not date:
            raise TypeError("published_on must be a date")
        if not isinstance(self.available_in_repository, bool):
            raise TypeError("available_in_repository must be a bool")


@dataclass(frozen=True, slots=True)
class BenchmarkSourceDecision:
    """Selected benchmark basis without changing the independent Omni evaluation."""

    source: BenchmarkSource | None
    source_date: date | None
    benchmark_basis_status: AssessmentStatus
    limitation: str | None


def _benchmark_source_key(source: BenchmarkSource) -> tuple[date, str, int, int]:
    """Order equally dated sources deterministically without input-order dependence."""
    return (
        source.published_on,
        source.location.path,
        source.location.start_line,
        source.location.end_line,
    )


def select_benchmark_source(
    sources: Iterable[BenchmarkSource],
    baseline_time: datetime,
    research_permitted: bool,
) -> BenchmarkSourceDecision:
    """Select the newest permitted source from the inclusive 365-day window."""
    if baseline_time.tzinfo is None or baseline_time.utcoffset() is None:
        raise ValueError("baseline_time must include a time-zone offset")
    if not isinstance(research_permitted, bool):
        raise TypeError("research_permitted must be a bool")

    candidates = tuple(sources)
    if any(not isinstance(source, BenchmarkSource) for source in candidates):
        raise TypeError("sources must contain only BenchmarkSource values")

    baseline_date = baseline_time.date()
    earliest_date = baseline_date - timedelta(days=365)
    qualifying = tuple(
        source
        for source in candidates
        if earliest_date <= source.published_on <= baseline_date
        and (source.available_in_repository or research_permitted)
    )
    if not qualifying:
        permission_context = (
            " competitor research was not permitted;" if not research_permitted else ""
        )
        return BenchmarkSourceDecision(
            source=None,
            source_date=None,
            benchmark_basis_status=AssessmentStatus.UNVERIFIED,
            limitation=(
                "No permitted benchmark source is non-future and no more than "
                f"365 calendar days old;{permission_context} benchmark basis is unavailable."
            ),
        )

    selected = max(qualifying, key=_benchmark_source_key)
    return BenchmarkSourceDecision(
        source=selected,
        source_date=selected.published_on,
        benchmark_basis_status=AssessmentStatus.VERIFIED_WORKING,
        limitation=None,
    )


def apply_benchmark_source_decision(
    row: ParityRow,
    decision: BenchmarkSourceDecision,
) -> ParityRow:
    """Apply only benchmark-basis fields while preserving Omni evaluation fields."""
    limitation = row.limitation
    if decision.limitation is not None:
        basis_limitation = f"Benchmark basis: {decision.limitation}"
        limitation = f"{limitation}; {basis_limitation}" if limitation else basis_limitation

    return replace(
        row,
        benchmark_source=None if decision.source is None else decision.source.location,
        benchmark_source_date=decision.source_date,
        benchmark_basis_status=decision.benchmark_basis_status,
        limitation=limitation,
    )
