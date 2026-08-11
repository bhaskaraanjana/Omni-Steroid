"""Documentary-claim inventory and traceability domain records.

Exact quoted text is kept separate from normalized scope and evidence-based conclusions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from .model_types import AssessmentStatus, SourceLocation, require_primary_status


class DocumentaryClassification(StrEnum):
    """Relationship between a documentary claim and current evidence."""

    CURRENT = "current"
    STALE = "stale"
    CONTRADICTORY = "contradictory"
    ASPIRATIONAL = "aspirational"
    UNSUPPORTED = "unsupported"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class DocumentaryClaim:
    """An immutable exact claim extracted from repository documentation."""

    claim_id: str
    exact_text: str
    source: SourceLocation
    material_scope: str
    document_date: date | None = None


@dataclass(frozen=True, slots=True)
class ClaimTrace:
    """Links one claim to implementation, configuration, tests, and evidence."""

    claim: DocumentaryClaim
    implementation_links: tuple[SourceLocation, ...]
    configuration_links: tuple[SourceLocation, ...]
    test_links: tuple[SourceLocation, ...]
    search_evidence_refs: tuple[str, ...]
    fresh_evidence_refs: tuple[str, ...]
    historical_evidence_refs: tuple[str, ...]
    documentary_classification: DocumentaryClassification
    primary_status: AssessmentStatus
    conclusion: str
    precedence_basis: str

    def __post_init__(self) -> None:
        """Reject non-enum primary classifications."""
        require_primary_status(self.primary_status)


@dataclass(frozen=True, slots=True)
class PathSearchEvidence:
    """Auditable result of searching current code and configuration for a claim path."""

    evidence_ref: str
    exhaustive: bool
    exact_searches: tuple[str, ...]
    searched_scopes: tuple[str, ...]
    inspected_matches: tuple[str, ...]
    executable_path_found: bool
    concluded_no_qualifying_implementation: bool

    def __post_init__(self) -> None:
        if not self.evidence_ref or not self.exact_searches or not self.searched_scopes:
            raise ValueError("path search requires a reference, exact searches, and searched scopes")
        if self.executable_path_found and self.concluded_no_qualifying_implementation:
            raise ValueError("a located executable path cannot also be concluded absent")
        if (
            self.exhaustive
            and not self.executable_path_found
            and not self.concluded_no_qualifying_implementation
        ):
            raise ValueError("an exhaustive missing-path search requires an explicit conclusion")


@dataclass(frozen=True, slots=True)
class HistoricalEvidenceCitation:
    """Historical support with a known measurement date or explicit unknown date."""

    evidence_ref: str
    measured_on: date | None

    def __post_init__(self) -> None:
        if not self.evidence_ref:
            raise ValueError("historical evidence requires a reference")


@dataclass(frozen=True, slots=True)
class ClaimClassificationFacts:
    """Pure evidence predicates used by the narrow claim-classification decision."""

    search: PathSearchEvidence
    documentary_claim_ref: str
    asserts_current: bool
    document_predates_newer_disagreement: bool = False
    newer_disagreeing_evidence_refs: tuple[str, ...] = ()
    contradictory_claim_refs: tuple[str, ...] = ()
    selected_conclusion_ref: str | None = None
    aspirational_wording_refs: tuple[str, ...] = ()
    historical_evidence: tuple[HistoricalEvidenceCitation, ...] = ()

    def __post_init__(self) -> None:
        if not self.documentary_claim_ref:
            raise ValueError("documentary claim requires a source reference")
        if self.document_predates_newer_disagreement and not self.newer_disagreeing_evidence_refs:
            raise ValueError("staleness requires newer disagreeing evidence")
        if self.contradictory_claim_refs:
            if len(set(self.contradictory_claim_refs)) < 2 or not self.selected_conclusion_ref:
                raise ValueError("contradiction requires every conflicting source and a conclusion")
        elif self.selected_conclusion_ref is not None:
            raise ValueError("a selected contradiction conclusion requires conflicting claims")


@dataclass(frozen=True, slots=True)
class ClaimClassificationDecision:
    """One primary status, one documentary classification, and their citations."""

    primary_status: AssessmentStatus
    documentary_classification: DocumentaryClassification
    citation_refs: tuple[str, ...]
    historical_dates: tuple[date | None, ...] = ()


def _unique_citations(*groups: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item for group in groups for item in group))


def classify_claim(facts: ClaimClassificationFacts) -> ClaimClassificationDecision:
    """Classify missing paths and documentary evidence without repository side effects."""
    search = facts.search
    missing_after_exhaustive_search = search.exhaustive and not search.executable_path_found

    if facts.contradictory_claim_refs:
        documentary = DocumentaryClassification.CONTRADICTORY
        documentary_citations = facts.contradictory_claim_refs + (facts.selected_conclusion_ref or "",)
    elif facts.document_predates_newer_disagreement:
        documentary = DocumentaryClassification.STALE
        documentary_citations = (facts.documentary_claim_ref,) + facts.newer_disagreeing_evidence_refs
    elif facts.aspirational_wording_refs:
        documentary = DocumentaryClassification.ASPIRATIONAL
        documentary_citations = facts.aspirational_wording_refs
    elif (
        facts.asserts_current
        and missing_after_exhaustive_search
        and not facts.historical_evidence
    ):
        documentary = DocumentaryClassification.UNSUPPORTED
        documentary_citations = (search.evidence_ref,)
    elif facts.asserts_current and search.executable_path_found:
        documentary = DocumentaryClassification.CURRENT
        documentary_citations = (facts.documentary_claim_ref, search.evidence_ref)
    else:
        documentary = DocumentaryClassification.NONE
        documentary_citations = ()

    historical_refs = tuple(item.evidence_ref for item in facts.historical_evidence)
    if missing_after_exhaustive_search:
        status = AssessmentStatus.NOT_IMPLEMENTED
        status_citations = (search.evidence_ref,)
    elif facts.historical_evidence:
        status = AssessmentStatus.HISTORICAL_ONLY
        status_citations = historical_refs
    else:
        status = AssessmentStatus.UNVERIFIED
        status_citations = (search.evidence_ref, facts.documentary_claim_ref)

    return ClaimClassificationDecision(
        primary_status=status,
        documentary_classification=documentary,
        citation_refs=_unique_citations(status_citations, documentary_citations),
        historical_dates=tuple(item.measured_on for item in facts.historical_evidence),
    )