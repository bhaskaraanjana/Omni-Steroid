"""Pure evidence-precedence selection and complete conflict records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Iterable


class EvidenceTier(StrEnum):
    """Evidence tiers in required highest-to-lowest precedence order."""

    FRESH = "fresh_evidence"
    CONFIGURATION = "configuration"
    CODE = "code"
    DOCUMENTARY = "documentary"
    HISTORICAL = "historical"


_TIER_RANK = {tier: rank for rank, tier in enumerate(EvidenceTier)}


@dataclass(frozen=True, slots=True)
class EvidenceSource:
    """One applicable value and its auditable source metadata."""

    tier: EvidenceTier
    value: str
    source: str
    collected_on: date | None

    def __post_init__(self) -> None:
        if not isinstance(self.tier, EvidenceTier):
            raise TypeError("tier must be an EvidenceTier")
        if not self.value:
            raise ValueError("evidence value must not be empty")
        if not self.source:
            raise ValueError("evidence source must not be empty")


@dataclass(frozen=True, slots=True)
class EvidenceConflict:
    """Every source participating when applicable evidence values disagree."""

    evidence: tuple[EvidenceSource, ...]
    selected_conclusion: str
    precedence_basis: str


@dataclass(frozen=True, slots=True)
class EvidenceDecision:
    """Deterministic conclusion selected from the highest available tier."""

    selected: EvidenceSource | None
    precedence_basis: str
    conflict: EvidenceConflict | None

    @property
    def selected_conclusion(self) -> str | None:
        return None if self.selected is None else self.selected.value

    @property
    def selected_tier(self) -> EvidenceTier | None:
        return None if self.selected is None else self.selected.tier


def _canonical_key(item: EvidenceSource) -> tuple[int, str, str, str]:
    """Provide stable ordering, including deterministic same-tier conflicts."""
    date_key = "unknown" if item.collected_on is None else item.collected_on.isoformat()
    return (_TIER_RANK[item.tier], item.source, date_key, item.value)


def select_evidence(evidence: Iterable[EvidenceSource]) -> EvidenceDecision:
    """Select the highest-precedence evidence and retain complete disagreements."""
    ordered = tuple(sorted(evidence, key=_canonical_key))
    if not ordered:
        return EvidenceDecision(None, "no applicable evidence", None)
    if any(not isinstance(item, EvidenceSource) for item in ordered):
        raise TypeError("evidence must contain only EvidenceSource values")

    selected = ordered[0]
    basis = f"{selected.tier.value} is the highest available applicable evidence tier"
    conflict = None
    if len({item.value for item in ordered}) > 1:
        conflict = EvidenceConflict(
            evidence=ordered,
            selected_conclusion=selected.value,
            precedence_basis=basis,
        )
    return EvidenceDecision(selected, basis, conflict)
