"""Property 12: Parity matrices have exact canonical shape.

**Validates: Requirements 6.1, 6.2, 6.3, 9.7**
"""

from __future__ import annotations

import random

from assessor import (
    AssessmentStatus,
    BenchmarkSet,
    GRANOLA_CAPABILITIES,
    ParityRow,
    WISPR_FLOW_CAPABILITIES,
    build_canonical_parity_matrix,
)

_CASES = 128
_SEED = 20260708
_REQUIRED_COLUMNS = (
    "benchmark_capability",
    "benchmark_source",
    "benchmark_source_date",
    "omni_documentary_claim_refs",
    "implementation_locations",
    "fresh_evidence_refs",
    "primary_status",
    "limitation",
    "parity_conclusion",
)


def _evidence_row(benchmark_set: BenchmarkSet, capability: str) -> ParityRow:
    slug = capability.replace(" ", "-")
    return ParityRow(
        row_id=f"{benchmark_set.value}-{slug}",
        benchmark_set=benchmark_set,
        benchmark_capability=capability,
        benchmark_source=None,
        benchmark_source_date=None,
        benchmark_basis_status=AssessmentStatus.UNVERIFIED,
        omni_documentary_claim_refs=(f"claim-{slug}",),
        implementation_locations=(),
        fresh_evidence_refs=(f"evidence-{slug}",),
        primary_status=AssessmentStatus.UNVERIFIED,
        limitation="generated evidence",
        parity_conclusion=f"conclusion-{slug}",
        measurements=(),
    )

def _assert_exact_shape(rows: tuple[ParityRow, ...]) -> None:
    granola = tuple(
        row for row in rows if row.benchmark_set is BenchmarkSet.GRANOLA
    )
    wispr_flow = tuple(
        row for row in rows if row.benchmark_set is BenchmarkSet.WISPR_FLOW
    )
    keys = tuple((row.benchmark_set, row.benchmark_capability) for row in rows)

    assert len(granola) == 13
    assert len(wispr_flow) == 16
    assert tuple(row.benchmark_capability for row in granola) == GRANOLA_CAPABILITIES
    assert tuple(row.benchmark_capability for row in wispr_flow) == WISPR_FLOW_CAPABILITIES
    assert len(keys) == len(set(keys)) == 29
    assert all(
        all(hasattr(row, column) for column in _REQUIRED_COLUMNS) for row in rows
    )


def test_empty_evidence_still_creates_every_required_matrix_row() -> None:
    rows = build_canonical_parity_matrix()

    _assert_exact_shape(rows)
    assert all(row.primary_status is AssessmentStatus.UNVERIFIED for row in rows)


def test_property_12_parity_matrices_have_exact_canonical_shape() -> None:
    """Assert exact rows and columns across at least 100 evidence permutations."""
    rng = random.Random(_SEED)
    evidence = [
        _evidence_row(BenchmarkSet.GRANOLA, capability)
        for capability in GRANOLA_CAPABILITIES
    ] + [
        _evidence_row(BenchmarkSet.WISPR_FLOW, capability)
        for capability in WISPR_FLOW_CAPABILITIES
    ]
    permutations: set[tuple[str, ...]] = set()

    while len(permutations) < _CASES:
        rng.shuffle(evidence)
        signature = tuple(row.row_id for row in evidence)
        if signature in permutations:
            continue
        permutations.add(signature)

        rows = build_canonical_parity_matrix(evidence)
        _assert_exact_shape(rows)
        assert {
            (row.benchmark_set, row.benchmark_capability): row.parity_conclusion
            for row in rows
        } == {
            (row.benchmark_set, row.benchmark_capability): row.parity_conclusion
            for row in evidence
        }

    assert len(permutations) >= 100
