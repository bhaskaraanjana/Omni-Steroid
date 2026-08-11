"""Bounded production-code searches and evidence-backed claim trace decisions.

Searches are exhaustive only when every eligible text file was read without a
limit or decoding omission. This fail-closed rule prevents unsupported absence
from being reported as Not Implemented.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Iterable

from .claim_models import (
    ClaimClassificationFacts,
    ClaimTrace,
    DocumentaryClaim,
    HistoricalEvidenceCitation,
    PathSearchEvidence,
    classify_claim,
)
from .evidence_precedence import EvidenceDecision, EvidenceSource, select_evidence
from .model_types import AssessmentStatus, SourceLocation


class TraceLinkKind(StrEnum):
    """Direct relationship of a matching production location to a claim."""

    IMPLEMENTATION = "implementation"
    CONFIGURATION = "configuration"
    TEST = "test"


@dataclass(frozen=True, slots=True)
class SearchInspection:
    """One inspected textual match and why it does or does not qualify."""

    location: SourceLocation
    kind: TraceLinkKind
    matched_terms: tuple[str, ...]
    qualifies: bool
    reason: str


@dataclass(frozen=True, slots=True)
class ClaimSearchResult:
    """Complete links plus the auditable record of the bounded search."""

    search_evidence: PathSearchEvidence
    implementation_links: tuple[SourceLocation, ...]
    configuration_links: tuple[SourceLocation, ...]
    test_links: tuple[SourceLocation, ...]
    inspections: tuple[SearchInspection, ...]
    omissions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ClaimTraceDecisionInput:
    """Inputs required to classify and select a conclusion for one claim."""

    claim: DocumentaryClaim
    search: ClaimSearchResult
    documentary_claim_ref: str
    asserts_current: bool
    evidence: tuple[EvidenceSource, ...] = ()
    fresh_evidence_refs: tuple[str, ...] = ()
    historical_evidence: tuple[HistoricalEvidenceCitation, ...] = ()
    fresh_status: AssessmentStatus | None = None
    document_predates_newer_disagreement: bool = False
    newer_disagreeing_evidence_refs: tuple[str, ...] = ()
    contradictory_claim_refs: tuple[str, ...] = ()
    selected_conclusion_ref: str | None = None
    aspirational_wording_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.fresh_status is not None and not self.fresh_evidence_refs:
            raise ValueError("a fresh status requires fresh evidence references")


@dataclass(frozen=True, slots=True)
class ClaimTraceDecision:
    """Trace record together with any complete evidence-conflict decision."""

    trace: ClaimTrace
    evidence_decision: EvidenceDecision


_EXCLUDED_PARTS = {
    ".git", ".venv", "node_modules", "target", "dist", "build",
    "assessment-output", "__pycache__", "docs", "evidence", "assets", "media",
}
_SOURCE_SUFFIXES = {".py", ".pyi", ".ts", ".tsx", ".js", ".jsx", ".rs", ".sql", ".ps1", ".sh"}
_CONFIG_SUFFIXES = {".toml", ".json", ".yaml", ".yml", ".ini", ".cfg", ".conf", ".lock"}
_CONFIG_NAMES = {"makefile", "dockerfile", ".coveragerc", ".env.example"}


def _link_kind(relative: str) -> TraceLinkKind | None:
    path = Path(relative)
    lowered_parts = {part.lower() for part in path.parts}
    if lowered_parts & _EXCLUDED_PARTS or relative.startswith(".kiro/"):
        return None
    name = path.name.lower()
    if "tests" in lowered_parts or name.startswith("test_") or ".test." in name or ".spec." in name:
        return TraceLinkKind.TEST
    if (
        path.suffix.lower() in _CONFIG_SUFFIXES
        or name in _CONFIG_NAMES
        or relative.startswith(".github/workflows/")
    ):
        return TraceLinkKind.CONFIGURATION
    if path.suffix.lower() in _SOURCE_SUFFIXES:
        return TraceLinkKind.IMPLEMENTATION
    return None


def _unique_locations(values: Iterable[SourceLocation]) -> tuple[SourceLocation, ...]:
    return tuple(dict.fromkeys(values))


def _search_ref(terms: tuple[str, ...], inspections: tuple[SearchInspection, ...], omissions: tuple[str, ...]) -> str:
    payload = "\n".join(
        (*terms, *(f"{item.location.path}:{item.location.start_line}:{item.kind.value}" for item in inspections), *omissions)
    )
    return "claim-search-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def search_claim_traceability(
    repository_root: Path,
    search_terms: Iterable[str],
    *,
    max_file_bytes: int = 2_000_000,
    max_inspections: int = 10_000,
) -> ClaimSearchResult:
    """Search all eligible production source/config/tests with explicit safety bounds."""
    root = repository_root.resolve()
    terms = tuple(dict.fromkeys(term for term in search_terms if term))
    if not terms:
        raise ValueError("claim traceability search requires at least one exact term")
    lowered_terms = tuple(term.casefold() for term in terms)
    inspections: list[SearchInspection] = []
    omissions: list[str] = []
    searched_kinds: set[TraceLinkKind] = set()

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        kind = _link_kind(relative)
        if kind is None:
            continue
        searched_kinds.add(kind)
        try:
            if path.stat().st_size > max_file_bytes:
                omissions.append(f"{relative}: exceeds {max_file_bytes} byte search bound")
                continue
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError) as error:
            omissions.append(f"{relative}: unreadable as UTF-8 ({type(error).__name__})")
            continue
        for line_number, line in enumerate(lines, start=1):
            folded = line.casefold()
            matched = tuple(term for term, lowered in zip(terms, lowered_terms) if lowered in folded)
            if not matched:
                continue
            if len(inspections) >= max_inspections:
                omissions.append(f"search stopped at {max_inspections} matching locations")
                break
            inspections.append(
                SearchInspection(
                    location=SourceLocation(relative, line_number, line_number),
                    kind=kind,
                    matched_terms=matched,
                    qualifies=True,
                    reason=f"literal claim term occurs in {kind.value} scope",
                )
            )
        if omissions and omissions[-1].startswith("search stopped"):
            break

    inspection_tuple = tuple(inspections)
    omission_tuple = tuple(omissions)
    implementations = _unique_locations(
        item.location for item in inspections if item.qualifies and item.kind is TraceLinkKind.IMPLEMENTATION
    )
    configurations = _unique_locations(
        item.location for item in inspections if item.qualifies and item.kind is TraceLinkKind.CONFIGURATION
    )
    tests = _unique_locations(
        item.location for item in inspections if item.qualifies and item.kind is TraceLinkKind.TEST
    )
    executable_found = bool(implementations or configurations)
    exhaustive = not omissions
    scopes = tuple(f"all eligible {kind.value} files" for kind in sorted(searched_kinds, key=str))
    if not scopes:
        scopes = ("all eligible production source, configuration, and test files",)
    evidence = PathSearchEvidence(
        evidence_ref=_search_ref(terms, inspection_tuple, omission_tuple),
        exhaustive=exhaustive,
        exact_searches=tuple(f"literal:{term}" for term in terms),
        searched_scopes=scopes,
        inspected_matches=tuple(
            f"{item.location.path}:{item.location.start_line}|{item.kind.value}|{item.reason}"
            for item in inspection_tuple
        ),
        executable_path_found=executable_found,
        concluded_no_qualifying_implementation=exhaustive and not executable_found,
    )
    return ClaimSearchResult(
        search_evidence=evidence,
        implementation_links=implementations,
        configuration_links=configurations,
        test_links=tests,
        inspections=inspection_tuple,
        omissions=omission_tuple,
    )


def decide_claim_trace(inputs: ClaimTraceDecisionInput) -> ClaimTraceDecision:
    """Apply path classification and required evidence precedence to one claim."""
    classification = classify_claim(
        ClaimClassificationFacts(
            search=inputs.search.search_evidence,
            documentary_claim_ref=inputs.documentary_claim_ref,
            asserts_current=inputs.asserts_current,
            document_predates_newer_disagreement=inputs.document_predates_newer_disagreement,
            newer_disagreeing_evidence_refs=inputs.newer_disagreeing_evidence_refs,
            contradictory_claim_refs=inputs.contradictory_claim_refs,
            selected_conclusion_ref=inputs.selected_conclusion_ref,
            aspirational_wording_refs=inputs.aspirational_wording_refs,
            historical_evidence=inputs.historical_evidence,
        )
    )
    evidence_decision = select_evidence(inputs.evidence)
    missing_path = (
        inputs.search.search_evidence.exhaustive
        and not inputs.search.search_evidence.executable_path_found
    )
    if missing_path:
        primary_status = AssessmentStatus.NOT_IMPLEMENTED
    elif inputs.fresh_status is not None:
        primary_status = inputs.fresh_status
    else:
        primary_status = classification.primary_status
    conclusion = evidence_decision.selected_conclusion or primary_status.value
    trace = ClaimTrace(
        claim=inputs.claim,
        implementation_links=inputs.search.implementation_links,
        configuration_links=inputs.search.configuration_links,
        test_links=inputs.search.test_links,
        search_evidence_refs=(inputs.search.search_evidence.evidence_ref,),
        fresh_evidence_refs=inputs.fresh_evidence_refs,
        historical_evidence_refs=tuple(item.evidence_ref for item in inputs.historical_evidence),
        documentary_classification=classification.documentary_classification,
        primary_status=primary_status,
        conclusion=conclusion,
        precedence_basis=evidence_decision.precedence_basis,
    )
    return ClaimTraceDecision(trace=trace, evidence_decision=evidence_decision)
