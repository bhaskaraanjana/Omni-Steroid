"""Trace every inventoried documentary claim to code, configuration, and tests.

One bounded repository search per claim, using the claim's own most distinctive
tokens so the link is exact rather than incidental. A claim with no searchable token
is recorded as untraceable and reported by identifier — never silently dropped, and
never counted as verified.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from .claim_models import DocumentaryClaim
from .claim_traceability import (
    ClaimTraceDecisionInput,
    decide_claim_trace,
    search_claim_traceability,
)
from .model_types import SourceLocation

_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_-]{4,}")
_STOPWORDS = frozenset(
    {
        "about", "after", "again", "along", "already", "always", "another", "because",
        "before", "being", "between", "could", "during", "every", "first",
        "into", "never", "other", "should", "since", "still", "such", "than", "that",
        "their", "them", "there", "these", "they", "this", "those", "through", "under",
        "until", "using", "were", "what", "when", "where", "which", "while", "with",
        "without", "would", "your",
    }
)


def claim_search_terms(exact_text: str) -> tuple[str, ...]:
    """Pick the most distinctive tokens of a claim, deterministically.

    Longest-first keeps the terms specific. Ordering never depends on where a token
    appeared, so the same claim always produces the same search.
    """
    tokens = [
        token for token in _WORD.findall(exact_text)
        if token.casefold() not in _STOPWORDS
    ]
    if not tokens:
        return ()
    ranked = sorted(dict.fromkeys(tokens), key=lambda item: (-len(item), item))
    return tuple(ranked[:2])


def build_claim_traces(
    mirror_root: Path, claims: list[dict[str, object]], fresh_evidence_refs: tuple[str, ...]
) -> tuple[tuple[object, ...], tuple[str, ...]]:
    """Trace every inventoried claim through the repository search, once each."""
    traces = []
    skipped: list[str] = []
    for record in claims:
        claim = _documentary_claim(record)
        terms = claim_search_terms(claim.exact_text)
        if not terms:
            # Recorded, never silently dropped: a claim with no searchable token
            # cannot be traced and must not be counted as verified.
            skipped.append(claim.claim_id)
            continue
        search = search_claim_traceability(mirror_root, terms)
        decision = decide_claim_trace(
            ClaimTraceDecisionInput(
                claim=claim,
                search=search,
                documentary_claim_ref=f"{claim.source.path}:{claim.source.start_line}",
                asserts_current=True,
                fresh_evidence_refs=fresh_evidence_refs,
            )
        )
        traces.append(decision.trace)
    return tuple(traces), tuple(skipped)


def _documentary_claim(record: dict[str, object]) -> DocumentaryClaim:
    source = record["source"]
    if not isinstance(source, dict):
        raise ValueError("a claim record requires a source location")
    return DocumentaryClaim(
        str(record["claim_id"]),
        str(record["exact_text"]),
        SourceLocation(
            str(source["path"]),
            int(source["start_line"]),
            int(source["end_line"]),
        ),
        str(record["material_scope"]),
        _claim_date(record.get("document_date")),
    )


def _claim_date(value: object) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None
