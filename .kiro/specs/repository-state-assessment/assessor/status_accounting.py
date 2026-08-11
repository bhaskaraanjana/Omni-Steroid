"""Pure row-hierarchy validation and deterministic status accounting."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256

from .model_types import AssessmentStatus, require_primary_status


class ClassifiedRowKind(StrEnum):
    """Report row categories included in the global status summary."""

    CLAIM = "claim"
    CHECK = "check"
    SUBSET = "subset"
    PARITY = "parity"


@dataclass(frozen=True, slots=True)
class ClassifiedRow:
    """One independently classified report scope with one primary status."""

    row_id: str
    row_kind: ClassifiedRowKind
    primary_status: AssessmentStatus
    parent_row_id: str | None = None
    subset_key: str | None = None
    required_subset_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_primary_status(self.primary_status)
        if not self.row_id:
            raise ValueError("classified row requires a row ID")
        if not isinstance(self.row_kind, ClassifiedRowKind):
            raise TypeError("row_kind must be one ClassifiedRowKind value")

        if self.row_kind is ClassifiedRowKind.SUBSET:
            if not self.parent_row_id or not self.subset_key:
                raise ValueError("subset rows require a parent row ID and subset key")
        elif self.parent_row_id is not None or self.subset_key is not None:
            raise ValueError("only subset rows may reference a parent or subset key")

        if self.primary_status is AssessmentStatus.VERIFIED_PARTIAL:
            if not self.required_subset_keys:
                raise ValueError("partial rows must declare every required child subset")
            if len(set(self.required_subset_keys)) != len(self.required_subset_keys):
                raise ValueError("partial row subset keys must be unique")
            if any(not key for key in self.required_subset_keys):
                raise ValueError("partial row subset keys must be non-empty")
        elif self.required_subset_keys:
            raise ValueError("only partial rows may declare required child subsets")


@dataclass(frozen=True, slots=True)
class StatusTotal:
    """The exact row-level count for one assessment status."""

    status: AssessmentStatus
    count: int


@dataclass(frozen=True, slots=True)
class StatusSummary:
    """A reproducible summary for one declared collection of classified rows."""

    collection_id: str
    status_totals: tuple[StatusTotal, ...]
    classified_row_count: int
    row_id_checksum: str

    def count_for(self, status: AssessmentStatus) -> int:
        """Return the total for a status, including explicit zero totals."""
        require_primary_status(status)
        return next(total.count for total in self.status_totals if total.status is status)


def row_id_checksum(row_ids: tuple[str, ...]) -> str:
    """Hash sorted row IDs so input ordering cannot alter report identity."""
    canonical_ids = "\n".join(sorted(row_ids))
    return sha256(canonical_ids.encode("utf-8")).hexdigest()


def _validate_hierarchy(rows_by_id: dict[str, ClassifiedRow]) -> None:
    children_by_parent: dict[str, list[ClassifiedRow]] = {}
    for row in rows_by_id.values():
        if row.parent_row_id is None:
            continue
        parent = rows_by_id.get(row.parent_row_id)
        if parent is None:
            raise ValueError(f"subset row {row.row_id!r} references an unknown parent")
        if parent.primary_status is not AssessmentStatus.VERIFIED_PARTIAL:
            raise ValueError(f"subset row {row.row_id!r} has a non-partial parent")
        children_by_parent.setdefault(parent.row_id, []).append(row)

        ancestors = {row.row_id}
        ancestor = parent
        while ancestor.parent_row_id is not None:
            if ancestor.row_id in ancestors:
                raise ValueError("classified row hierarchy contains a cycle")
            ancestors.add(ancestor.row_id)
            next_ancestor = rows_by_id.get(ancestor.parent_row_id)
            if next_ancestor is None:
                raise ValueError(f"subset row {ancestor.row_id!r} references an unknown parent")
            ancestor = next_ancestor

    for row in rows_by_id.values():
        if row.primary_status is not AssessmentStatus.VERIFIED_PARTIAL:
            continue
        children = children_by_parent.get(row.row_id, [])
        child_keys = tuple(child.subset_key for child in children)
        if len(set(child_keys)) != len(child_keys):
            raise ValueError(f"partial row {row.row_id!r} has duplicate child subsets")
        if set(child_keys) != set(row.required_subset_keys):
            raise ValueError(f"partial row {row.row_id!r} children are not exhaustive")


def summarize_classified_rows(
    collection_id: str, rows: tuple[ClassifiedRow, ...]
) -> StatusSummary:
    """Validate a hierarchy and count each uniquely identified row exactly once."""
    if not collection_id:
        raise ValueError("status summary requires a collection ID")

    rows_by_id = {row.row_id: row for row in rows}
    if len(rows_by_id) != len(rows):
        raise ValueError("classified row IDs must be unique")
    _validate_hierarchy(rows_by_id)

    counts = Counter(row.primary_status for row in rows)
    totals = tuple(StatusTotal(status, counts[status]) for status in AssessmentStatus)
    return StatusSummary(
        collection_id=collection_id,
        status_totals=totals,
        classified_row_count=len(rows),
        row_id_checksum=row_id_checksum(tuple(rows_by_id)),
    )
