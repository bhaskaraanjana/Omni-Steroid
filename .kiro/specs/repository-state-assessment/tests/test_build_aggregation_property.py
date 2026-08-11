"""Property 6 coverage for fail-closed Product Build aggregation.

**Validates: Requirements 3.10, 3.11, 8.4**
"""

from __future__ import annotations

import random

from assessor import (
    AssessmentStatus,
    BuildComponentResult,
    aggregate_product_build,
)

_SEED = 20260708
_CASES = 256


def _component_sets(
    rng: random.Random, case: int
) -> tuple[tuple[str, ...], tuple[BuildComponentResult, ...]]:
    component_ids = tuple(
        f"case-{case}-component-{index}" for index in range(rng.randint(1, 8))
    )
    records: list[BuildComponentResult] = []

    for index, component_id in enumerate(component_ids):
        state = rng.choice(("passed", "failed", "missing", "unclassified"))
        if index == 0:
            state = ("failed", "missing", "unclassified", "passed")[case % 4]

        if state == "missing":
            continue
        if state == "unclassified":
            records.append(
                BuildComponentResult(
                    component_id=component_id,
                    executed=bool((case + index) % 2),
                    passed=None,
                )
            )
        else:
            records.append(
                BuildComponentResult(
                    component_id=component_id,
                    executed=True,
                    passed=state == "passed",
                )
            )

    rng.shuffle(records)
    return component_ids, tuple(records)


def test_failure_cannot_be_hidden_by_missing_or_unclassified_components() -> None:
    """A known component failure dominates gaps without collapsing child records."""
    records = (
        BuildComponentResult("engine-build", executed=True, passed=False),
        BuildComponentResult("frontend-build", executed=True, passed=None),
    )

    aggregate = aggregate_product_build(
        ("engine-build", "frontend-build", "desktop-build"), records
    )

    assert aggregate.primary_status is AssessmentStatus.FRESH_FAILURE
    assert aggregate.component_records == records
    assert aggregate.missing_component_ids == ("desktop-build",)


def test_incomplete_results_never_report_a_passing_aggregate() -> None:
    """Missing and unclassified required components fail closed as Unverified."""
    aggregate = aggregate_product_build(
        ("engine-build", "frontend-build"),
        (BuildComponentResult("engine-build", executed=True, passed=True),),
    )
    assert aggregate.primary_status is AssessmentStatus.UNVERIFIED
    assert aggregate.missing_component_ids == ("frontend-build",)

    unclassified = aggregate_product_build(
        ("engine-build",),
        (BuildComponentResult("engine-build", executed=False, passed=None),),
    )
    assert unclassified.primary_status is AssessmentStatus.UNVERIFIED


def test_property_6_aggregate_build_status_is_fail_closed() -> None:
    """Generate applicable component sets and preserve every supplied result."""
    rng = random.Random(_SEED)
    seen = {"failed": 0, "missing": 0, "unclassified": 0, "complete": 0}

    for case in range(_CASES):
        component_ids, records = _component_sets(rng, case)
        aggregate = aggregate_product_build(component_ids, records)
        records_by_id = {record.component_id: record for record in records}
        missing = tuple(
            component_id
            for component_id in component_ids
            if component_id not in records_by_id
        )
        failed = tuple(
            record
            for record in records
            if record.executed and record.passed is False
        )
        unclassified = tuple(record for record in records if record.passed is None)

        seen["failed"] += bool(failed)
        seen["missing"] += bool(missing)
        seen["unclassified"] += bool(unclassified)
        seen["complete"] += not failed and not missing and not unclassified

        if failed:
            expected_status = AssessmentStatus.FRESH_FAILURE
        elif missing or unclassified:
            expected_status = AssessmentStatus.UNVERIFIED
        else:
            expected_status = AssessmentStatus.VERIFIED_WORKING

        assert aggregate.primary_status is expected_status, f"failed case {case}"
        assert aggregate.component_records == records
        assert aggregate.missing_component_ids == missing
        assert len(aggregate.component_records) == len(records)
        assert tuple(record.component_id for record in aggregate.component_records) == tuple(
            record.component_id for record in records
        )

        if failed:
            assert aggregate.primary_status is AssessmentStatus.FRESH_FAILURE

    assert _CASES >= 100
    assert all(count > 0 for count in seen.values()), seen
