"""Pin committed report metrics and reconcile them through evidence precedence.

This module sits before report synthesis and guarantees that documentary baseline
claims cannot silently drift while fresher evidence still determines conclusions.
"""

from __future__ import annotations

from dataclasses import dataclass

from .evidence_precedence import EvidenceDecision, EvidenceSource, EvidenceTier, select_evidence

_COMMITTED_METRICS = (
    ("committed_test_count", "1,358 tests"),
    ("committed_line_coverage", "86.7 percent"),
    ("committed_branch_coverage", "78.2 percent"),
)


@dataclass(frozen=True, slots=True)
class CommittedMetricReconciliation:
    """A pinned documentary claim, all supplied evidence, and its selected result."""

    metric_id: str
    committed_value: str
    sources: tuple[EvidenceSource, ...]
    decision: EvidenceDecision


def reconcile_committed_metrics(
    metric_sources: dict[str, tuple[EvidenceSource, ...]],
) -> tuple[CommittedMetricReconciliation, ...]:
    """Validate fixed claims and select each metric by established tier precedence.

    The fixed order is part of the report contract. Exactly one documentary source
    must preserve each committed value; fresher evidence may supersede that value in
    the selected conclusion but may not rewrite the historical commitment.
    """
    expected_ids = {metric_id for metric_id, _ in _COMMITTED_METRICS}
    unexpected_ids = set(metric_sources) - expected_ids
    if unexpected_ids:
        raise ValueError(f"unknown committed metrics: {sorted(unexpected_ids)}")

    reconciled: list[CommittedMetricReconciliation] = []
    for metric_id, committed_value in _COMMITTED_METRICS:
        sources = metric_sources.get(metric_id)
        if sources is None:
            raise ValueError(
                f"{metric_id} is missing documentary committed value {committed_value}"
            )
        if any(not isinstance(source, EvidenceSource) for source in sources):
            raise TypeError("metric sources must contain only EvidenceSource values")
        documentary = tuple(
            source for source in sources if source.tier is EvidenceTier.DOCUMENTARY
        )
        if len(documentary) != 1 or documentary[0].value != committed_value:
            raise ValueError(
                f"{metric_id} documentary source must equal committed value {committed_value}"
            )
        decision = select_evidence(sources)
        if decision.selected is None:
            raise ValueError(f"{metric_id} has no selectable evidence")
        reconciled.append(
            CommittedMetricReconciliation(metric_id, committed_value, sources, decision)
        )
    return tuple(reconciled)
