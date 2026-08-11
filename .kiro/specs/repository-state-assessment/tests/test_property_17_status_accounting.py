"""Property 17: Primary statuses and totals reconcile exactly.

Feature: repository-state-assessment, Property 17: Primary statuses and totals reconcile exactly

**Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 8.9, 8.10, 8.11, 8.12, 9.1**
"""

from __future__ import annotations

import hashlib
import random
from collections import Counter

import pytest

from assessor import (
    AssessmentStatus,
    ClassifiedRow,
    ClassifiedRowKind,
    row_id_checksum,
    summarize_classified_rows,
)

_CASES = 128
_SEED = 20260717
_ROOT_KINDS = (
    ClassifiedRowKind.CLAIM,
    ClassifiedRowKind.CHECK,
    ClassifiedRowKind.PARITY,
)


def _generated_hierarchy(rng: random.Random, case: int) -> tuple[ClassifiedRow, ...]:
    rows: list[ClassifiedRow] = []
    root_count = rng.randint(3, 9)

    for root_index in range(root_count):
        kind = _ROOT_KINDS[(case + root_index) % len(_ROOT_KINDS)]
        status = tuple(AssessmentStatus)[(case + root_index) % len(AssessmentStatus)]
        row_id = f"case-{case}-{kind.value}-{root_index}"
        subset_keys: tuple[str, ...] = ()
        if status is AssessmentStatus.VERIFIED_PARTIAL:
            subset_keys = tuple(
                f"scope-{child_index}" for child_index in range(rng.randint(1, 5))
            )

        rows.append(
            ClassifiedRow(
                row_id=row_id,
                row_kind=kind,
                primary_status=status,
                required_subset_keys=subset_keys,
            )
        )

        for child_index, subset_key in enumerate(subset_keys):
            child_statuses = tuple(
                status
                for status in AssessmentStatus
                if status is not AssessmentStatus.VERIFIED_PARTIAL
            )
            rows.append(
                ClassifiedRow(
                    row_id=f"{row_id}-subset-{child_index}",
                    row_kind=ClassifiedRowKind.SUBSET,
                    primary_status=rng.choice(child_statuses),
                    parent_row_id=row_id,
                    subset_key=subset_key,
                )
            )

    rng.shuffle(rows)
    return tuple(rows)


def test_partial_parent_and_children_are_counted_as_distinct_rows() -> None:
    rows = (
        ClassifiedRow(
            row_id="check-capture",
            row_kind=ClassifiedRowKind.CHECK,
            primary_status=AssessmentStatus.VERIFIED_PARTIAL,
            required_subset_keys=("microphone", "loopback"),
        ),
        ClassifiedRow(
            row_id="check-capture-microphone",
            row_kind=ClassifiedRowKind.SUBSET,
            primary_status=AssessmentStatus.VERIFIED_WORKING,
            parent_row_id="check-capture",
            subset_key="microphone",
        ),
        ClassifiedRow(
            row_id="check-capture-loopback",
            row_kind=ClassifiedRowKind.SUBSET,
            primary_status=AssessmentStatus.ENVIRONMENT_BLOCKED,
            parent_row_id="check-capture",
            subset_key="loopback",
        ),
    )

    summary = summarize_classified_rows("global", rows)

    assert summary.classified_row_count == 3
    assert summary.count_for(AssessmentStatus.VERIFIED_PARTIAL) == 1
    assert summary.count_for(AssessmentStatus.VERIFIED_WORKING) == 1
    assert summary.count_for(AssessmentStatus.ENVIRONMENT_BLOCKED) == 1
    assert sum(total.count for total in summary.status_totals) == 3


def test_invalid_primary_status_and_incomplete_partial_partition_are_rejected() -> None:
    with pytest.raises(TypeError, match="one AssessmentStatus"):
        ClassifiedRow(
            row_id="claim-invalid",
            row_kind=ClassifiedRowKind.CLAIM,
            primary_status=(AssessmentStatus.UNVERIFIED,),  # type: ignore[arg-type]
        )

    incomplete_rows = (
        ClassifiedRow(
            row_id="parity-partial",
            row_kind=ClassifiedRowKind.PARITY,
            primary_status=AssessmentStatus.VERIFIED_PARTIAL,
            required_subset_keys=("supported", "remainder"),
        ),
        ClassifiedRow(
            row_id="parity-supported",
            row_kind=ClassifiedRowKind.SUBSET,
            primary_status=AssessmentStatus.VERIFIED_WORKING,
            parent_row_id="parity-partial",
            subset_key="supported",
        ),
    )

    with pytest.raises(ValueError, match="not exhaustive"):
        summarize_classified_rows("global", incomplete_rows)


def test_duplicate_row_ids_cannot_be_double_counted() -> None:
    duplicate_rows = (
        ClassifiedRow(
            row_id="claim-one",
            row_kind=ClassifiedRowKind.CLAIM,
            primary_status=AssessmentStatus.VERIFIED_WORKING,
        ),
        ClassifiedRow(
            row_id="claim-one",
            row_kind=ClassifiedRowKind.CLAIM,
            primary_status=AssessmentStatus.FRESH_FAILURE,
        ),
    )

    with pytest.raises(ValueError, match="row IDs must be unique"):
        summarize_classified_rows("global", duplicate_rows)


def test_property_17_primary_statuses_and_totals_reconcile_exactly() -> None:
    """Generate at least 100 claim/check/subset/parity status hierarchies."""
    rng = random.Random(_SEED)
    seen_kinds: set[ClassifiedRowKind] = set()
    seen_statuses: set[AssessmentStatus] = set()
    partial_hierarchy_count = 0

    for case in range(_CASES):
        rows = _generated_hierarchy(rng, case)
        summary = summarize_classified_rows(f"generated-{case}", rows)
        expected_counts = Counter(row.primary_status for row in rows)
        totals = {total.status: total.count for total in summary.status_totals}
        row_ids = tuple(row.row_id for row in rows)
        expected_checksum = hashlib.sha256(
            "\n".join(sorted(row_ids)).encode("utf-8")
        ).hexdigest()

        seen_kinds.update(row.row_kind for row in rows)
        seen_statuses.update(row.primary_status for row in rows)
        partial_hierarchy_count += any(
            row.primary_status is AssessmentStatus.VERIFIED_PARTIAL for row in rows
        )

        assert all(isinstance(row.primary_status, AssessmentStatus) for row in rows)
        assert set(totals) == set(AssessmentStatus)
        assert totals == {
            status: expected_counts[status] for status in AssessmentStatus
        }
        assert summary.classified_row_count == len(rows) == len(set(row_ids))
        assert sum(totals.values()) == summary.classified_row_count
        assert summary.row_id_checksum == expected_checksum
        assert summary.row_id_checksum == row_id_checksum(tuple(reversed(row_ids)))

        rows_by_parent: dict[str, list[ClassifiedRow]] = {}
        for row in rows:
            if row.parent_row_id is not None:
                rows_by_parent.setdefault(row.parent_row_id, []).append(row)
        for parent in rows:
            if parent.primary_status is AssessmentStatus.VERIFIED_PARTIAL:
                children = rows_by_parent[parent.row_id]
                assert {child.subset_key for child in children} == set(
                    parent.required_subset_keys
                )
                assert len(children) == len(parent.required_subset_keys)
                assert all(child.row_id != parent.row_id for child in children)

    assert _CASES >= 100
    assert seen_kinds == set(ClassifiedRowKind)
    assert seen_statuses == set(AssessmentStatus)
    assert partial_hierarchy_count > 0
