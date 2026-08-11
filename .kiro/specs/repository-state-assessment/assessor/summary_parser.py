"""Pure normalization of test outcomes, warnings, and coverage summaries."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from .evidence_models import TestCounts
from .model_types import Measurement, MeasurementUnit

_COUNT_PATTERN = re.compile(
    r"(?<![-\w.])(?P<count>\d+)\s+"
    r"(?P<category>passed|failed|skipped|deselected|ignored|warnings?)\b",
    re.IGNORECASE,
)
_COVERAGE_PATTERN = re.compile(
    r"\b(?P<name>statements?|lines?|branches?|functions?)\s*"
    r"(?:coverage\s*)?[:=]\s*(?P<value>\d+(?:\.\d+)?)\s*%",
    re.IGNORECASE,
)
_WARNING_PATTERN = re.compile(
    r"^\s*(?:warning|\[warning\])\s*[:\-]\s*(?P<detail>.+?)\s*$",
    re.IGNORECASE,
)
_COVERAGE_ORDER = ("statements", "lines", "branches", "functions")
_COVERAGE_ALIASES = {
    "statement": "statements",
    "statements": "statements",
    "line": "lines",
    "lines": "lines",
    "branch": "branches",
    "branches": "branches",
    "function": "functions",
    "functions": "functions",
}


@dataclass(frozen=True, slots=True)
class ParsedTestSummary:
    """Disjoint normalized values parsed from one runner summary."""

    test_counts: TestCounts
    warning_count: int
    warnings: tuple[str, ...]
    measurements: tuple[Measurement, ...]


def _text(summary: str | bytes) -> str:
    if isinstance(summary, str):
        return summary
    try:
        return summary.decode("utf-8")
    except UnicodeDecodeError:
        return summary.decode("cp1252")


def parse_test_summary(summary: str | bytes, *, assessed_scope: str) -> ParsedTestSummary:
    """Parse recognized summary fields without deriving one category from another."""
    decoded = _text(summary)
    counts = {name: 0 for name in ("passed", "failed", "skipped", "deselected", "ignored")}
    warning_count = 0
    for match in _COUNT_PATTERN.finditer(decoded):
        category = match.group("category").lower()
        value = int(match.group("count"))
        if category.startswith("warning"):
            warning_count = value
        else:
            counts[category] = value

    coverage: dict[str, Decimal] = {}
    for match in _COVERAGE_PATTERN.finditer(decoded):
        name = _COVERAGE_ALIASES[match.group("name").lower()]
        coverage.setdefault(name, Decimal(match.group("value")))

    warnings = tuple(
        match.group("detail")
        for line in decoded.splitlines()
        if (match := _WARNING_PATTERN.match(line)) is not None
    )
    measurements = tuple(
        Measurement(
            name=f"{name}_coverage",
            value=coverage[name],
            unit=MeasurementUnit.PERCENT,
            assessed_scope=assessed_scope,
        )
        for name in _COVERAGE_ORDER
        if name in coverage
    )
    return ParsedTestSummary(
        test_counts=TestCounts(**counts),
        warning_count=warning_count,
        warnings=warnings,
        measurements=measurements,
    )


@dataclass(frozen=True, slots=True)
class CoverageTargetDecision:
    """Independent comparison of one measured Python coverage dimension."""

    dimension: str
    target: Decimal
    measured_value: Decimal | None
    meets_target: bool | None


def evaluate_python_coverage(
    measurements: tuple[Measurement, ...],
    *,
    line_target: Decimal = Decimal("90"),
    branch_target: Decimal = Decimal("85"),
) -> tuple[CoverageTargetDecision, CoverageTargetDecision]:
    """Compare Python line and branch measurements without coupling outcomes."""
    if not line_target.is_finite() or not branch_target.is_finite():
        raise ValueError("coverage targets must be finite")

    by_name: dict[str, Measurement] = {}
    for measurement in measurements:
        if measurement.name not in {"lines_coverage", "branches_coverage"}:
            continue
        if measurement.name in by_name:
            raise ValueError(f"duplicate coverage measurement: {measurement.name}")
        if measurement.unit is not MeasurementUnit.PERCENT:
            raise ValueError("coverage measurements must use percent units")
        by_name[measurement.name] = measurement

    decisions = []
    for dimension, name, target in (
        ("lines", "lines_coverage", line_target),
        ("branches", "branches_coverage", branch_target),
    ):
        measurement = by_name.get(name)
        measured = None if measurement is None else measurement.value
        decisions.append(
            CoverageTargetDecision(
                dimension=dimension,
                target=target,
                measured_value=measured,
                meets_target=None if measured is None else measured >= target,
            )
        )
    return decisions[0], decisions[1]
