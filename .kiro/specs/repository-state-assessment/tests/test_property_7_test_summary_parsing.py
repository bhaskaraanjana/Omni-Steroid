"""Property 7 coverage for disjoint test counts and coverage measurements."""

from __future__ import annotations

import random
from decimal import Decimal

from assessor import MeasurementUnit, TestCounts as OutcomeCounts, parse_test_summary

_SEED = 20260708
_CASES = 160
_COVERAGE_NAMES = ("statements", "lines", "branches", "functions")
_WARNING_TEXT = (
    "naïve résumé warning",
    "警告: 会議データ",
    "предупреждение проверки",
    "smart quotes ‘warning’ — café £5",
)


def _case(case_index: int) -> tuple[str | bytes, OutcomeCounts, int, tuple[str, ...], dict[str, Decimal]]:
    rng = random.Random(_SEED + case_index)
    mode = case_index % 4
    counts = OutcomeCounts(*(rng.randint(0, 40) for _ in range(5)))
    warning_count = rng.randint(0, 4)
    warning_pool = (_WARNING_TEXT[0], _WARNING_TEXT[3]) if mode == 3 else _WARNING_TEXT
    warnings = tuple(warning_pool[item % len(warning_pool)] for item in range(warning_count))
    values = {
        name: Decimal(f"{(case_index * 17 + position * 13) % 100}.{position + 1}")
        for position, name in enumerate(_COVERAGE_NAMES)
    }
    count_parts = [
        f"{counts.passed} passed",
        f"{counts.failed} failed",
        f"{counts.skipped} skipped",
        f"{counts.deselected} deselected",
        f"{counts.ignored} ignored",
        f"{warning_count} warnings",
    ]
    coverage_parts = [f"{name.title()}: {values[name]}%" for name in _COVERAGE_NAMES]
    rng.shuffle(count_parts)
    rng.shuffle(coverage_parts)
    lines = [" | ".join(count_parts), " | ".join(coverage_parts)]
    lines.extend(f"[warning]: {warning}" for warning in warnings)

    if mode == 1:
        lines.insert(0, "malformed: -7 passed; 1.2 failed; NaN lines; 999 passedness")
    elif mode == 2:
        lines.insert(0, "測試結果 🚀 — résumé / данные / العربية")
    elif mode == 3:
        lines.insert(0, "cp1252 smart quotes ‘result’ — café costs £5")
        return "\n".join(lines).encode("cp1252"), counts, warning_count, warnings, values
    return "\n".join(lines), counts, warning_count, warnings, values


def test_property_7_test_counts_and_measurements_do_not_conflate_outcomes() -> None:
    """Property 7: Test counts and measurements do not conflate outcomes.

    **Validates: Requirements 3.5, 3.8, 3.16, 9.11**
    """
    seen_modes: set[int] = set()

    for case_index in range(_CASES):
        summary, counts, warning_count, warnings, values = _case(case_index)
        parsed = parse_test_summary(summary, assessed_scope=f"generated-case-{case_index}")
        seen_modes.add(case_index % 4)

        assert parsed.test_counts == counts
        assert parsed.warning_count == warning_count
        assert parsed.warnings == warnings
        assert len(parsed.measurements) == len(_COVERAGE_NAMES)
        assert {measurement.name: measurement.value for measurement in parsed.measurements} == {
            f"{name}_coverage": value for name, value in values.items()
        }
        assert all(
            measurement.unit is MeasurementUnit.PERCENT
            and measurement.assessed_scope == f"generated-case-{case_index}"
            for measurement in parsed.measurements
        )
        assert parsed.test_counts.passed == counts.passed
        assert parsed.test_counts.passed != (
            counts.passed + counts.skipped + counts.deselected + counts.ignored
        ) or not (counts.skipped or counts.deselected or counts.ignored)

    assert seen_modes == {0, 1, 2, 3}


def test_malformed_summary_does_not_invent_outcomes_or_measurements() -> None:
    parsed = parse_test_summary(
        "-3 passed, many failed, 2.5 skipped, NaN lines, 80 percent branches",
        assessed_scope="malformed-only",
    )

    assert parsed.test_counts == OutcomeCounts()
    assert parsed.warning_count == 0
    assert parsed.warnings == ()
    assert parsed.measurements == ()
