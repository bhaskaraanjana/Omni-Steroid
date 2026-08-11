"""Property 4 tests for evidence-based claim classification."""

from __future__ import annotations

import random
from datetime import date

from assessor import (
    AssessmentStatus,
    ClaimClassificationFacts,
    DocumentaryClassification,
    HistoricalEvidenceCitation,
    PathSearchEvidence,
    classify_claim,
)

_CASES = 512
_KINDS = (
    "not-implemented",
    "historical-only",
    "unverified",
    "stale",
    "contradictory",
    "aspirational",
    "unsupported",
)


def _search(case: int, *, exhaustive: bool, path_found: bool) -> PathSearchEvidence:
    return PathSearchEvidence(
        evidence_ref=f"search-{case}",
        exhaustive=exhaustive,
        exact_searches=(f"query-{case}",),
        searched_scopes=("assessor", "configuration"),
        inspected_matches=tuple(f"match-{i}" for i in range(case % 3)),
        executable_path_found=path_found,
        concluded_no_qualifying_implementation=exhaustive and not path_found,
    )


def _facts(case: int, kind: str, rng: random.Random) -> ClaimClassificationFacts:
    doc = f"document-{case}"
    exhaustive = kind in {"not-implemented", "unsupported"}
    path_found = kind not in {"not-implemented", "unsupported"} and rng.choice((True, False))
    if kind == "unverified" and case % 2:
        path_found = False
    if not path_found and kind not in {"not-implemented", "unsupported"}:
        exhaustive = False
    history = ()
    if kind in {"not-implemented", "historical-only"}:
        history = (HistoricalEvidenceCitation(f"history-{case}", None if case % 2 else date(2025, 1, 1)),)
    return ClaimClassificationFacts(
        search=_search(case, exhaustive=exhaustive, path_found=path_found),
        documentary_claim_ref=doc,
        asserts_current=kind not in {"aspirational"},
        document_predates_newer_disagreement=kind == "stale",
        newer_disagreeing_evidence_refs=(f"newer-{case}",) if kind == "stale" else (),
        contradictory_claim_refs=(doc, f"conflict-{case}") if kind == "contradictory" else (),
        selected_conclusion_ref=f"selected-{case}" if kind == "contradictory" else None,
        aspirational_wording_refs=(f"wording-{case}",) if kind == "aspirational" else (),
        historical_evidence=history,
    )


def test_incomplete_search_cannot_establish_not_implemented() -> None:
    facts = _facts(1, "unverified", random.Random(1))
    decision = classify_claim(facts)

    assert facts.search.exhaustive is False
    assert facts.search.executable_path_found is False
    assert decision.primary_status is AssessmentStatus.UNVERIFIED


def test_exhaustive_missing_path_overrides_historical_support() -> None:
    facts = _facts(2, "not-implemented", random.Random(2))
    decision = classify_claim(facts)

    assert decision.primary_status is AssessmentStatus.NOT_IMPLEMENTED
    assert facts.search.evidence_ref in decision.citation_refs


def test_property_4_missing_path_and_documentary_classifications_follow_evidence() -> None:
    """**Validates: Requirements 2.3, 2.4, 2.5, 2.6, 2.7, 2.9, 8.7, 8.8, 8.11**"""
    rng = random.Random(0xC1A55)
    expected_documentary = {
        "stale": DocumentaryClassification.STALE,
        "contradictory": DocumentaryClassification.CONTRADICTORY,
        "aspirational": DocumentaryClassification.ASPIRATIONAL,
        "unsupported": DocumentaryClassification.UNSUPPORTED,
    }

    for case in range(_CASES):
        kind = _KINDS[case % len(_KINDS)]
        facts = _facts(case, kind, rng)
        decision = classify_claim(facts)
        missing_after_exhaustive_search = (
            facts.search.exhaustive and not facts.search.executable_path_found
        )

        if missing_after_exhaustive_search:
            assert decision.primary_status is AssessmentStatus.NOT_IMPLEMENTED
            assert facts.search.evidence_ref in decision.citation_refs
        elif facts.historical_evidence:
            assert decision.primary_status is AssessmentStatus.HISTORICAL_ONLY
            assert set(item.evidence_ref for item in facts.historical_evidence) <= set(decision.citation_refs)
            assert decision.historical_dates == tuple(item.measured_on for item in facts.historical_evidence)
        else:
            assert decision.primary_status is AssessmentStatus.UNVERIFIED

        if kind in expected_documentary:
            assert decision.documentary_classification is expected_documentary[kind]
        if decision.documentary_classification is DocumentaryClassification.STALE:
            assert facts.document_predates_newer_disagreement
            assert facts.documentary_claim_ref in decision.citation_refs
            assert set(facts.newer_disagreeing_evidence_refs) <= set(decision.citation_refs)
        elif decision.documentary_classification is DocumentaryClassification.CONTRADICTORY:
            assert len(set(facts.contradictory_claim_refs)) >= 2
            assert set(facts.contradictory_claim_refs) <= set(decision.citation_refs)
            assert facts.selected_conclusion_ref in decision.citation_refs
        elif decision.documentary_classification is DocumentaryClassification.ASPIRATIONAL:
            assert set(facts.aspirational_wording_refs) <= set(decision.citation_refs)
        elif decision.documentary_classification is DocumentaryClassification.UNSUPPORTED:
            assert facts.asserts_current and not facts.search.executable_path_found
            assert not facts.historical_evidence
            assert facts.search.evidence_ref in decision.citation_refs
