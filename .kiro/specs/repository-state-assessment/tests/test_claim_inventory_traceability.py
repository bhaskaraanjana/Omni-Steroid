"""Task 2.5 examples for documentary claim inventory and traceability."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from assessor.claim_inventory import (
    PrimaryDocumentCategory,
    discover_primary_claim_documents,
    extract_material_claims,
)
from assessor.claim_models import DocumentaryClassification, HistoricalEvidenceCitation
from assessor.claim_traceability import (
    ClaimTraceDecisionInput,
    decide_claim_trace,
    search_claim_traceability,
)
from assessor.evidence_precedence import EvidenceSource, EvidenceTier
from assessor.model_types import AssessmentStatus


def _write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_discovers_each_primary_document_category_without_generated_noise(tmp_path: Path) -> None:
    documents = {
        "README.md": "# Product\n",
        "PRODUCT.md": "# Product context\n",
        "docs/features.md": "# Features\n",
        "docs/architecture.md": "# Architecture\n",
        "SECURITY.md": "# Security\n",
        "docs/threat-model.md": "# Privacy and threats\n",
        "packaging/README.md": "# Packaging and release\n",
        "evidence/README.md": "# Evidence\n",
        "evidence/coverage-report.md": "# Results\n",
        "docs/plans/future.md": "# Non-primary plan\n",
        "node_modules/example/README.md": "# Dependency\n",
    }
    for relative, text in documents.items():
        _write(tmp_path, relative, text)

    discovered = discover_primary_claim_documents(tmp_path)
    by_category = {
        category: {item.path for item in discovered if item.category is category}
        for category in PrimaryDocumentCategory
    }

    assert by_category[PrimaryDocumentCategory.OVERVIEW] == {"README.md", "PRODUCT.md"}
    assert by_category[PrimaryDocumentCategory.FEATURE] == {"docs/features.md"}
    assert by_category[PrimaryDocumentCategory.ARCHITECTURE] == {"docs/architecture.md"}
    assert by_category[PrimaryDocumentCategory.SECURITY_PRIVACY] == {
        "SECURITY.md",
        "docs/threat-model.md",
    }
    assert by_category[PrimaryDocumentCategory.PACKAGING_RELEASE] == {"packaging/README.md"}
    assert by_category[PrimaryDocumentCategory.EVIDENCE_RESULTS] == {
        "evidence/README.md",
        "evidence/coverage-report.md",
    }
    assert all("node_modules" not in item.path and "plans/" not in item.path for item in discovered)


def test_extracts_exact_claims_and_splits_line_and_branch_targets(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "README.md",
        "# Product\n\n"
        "Omni captures meetings locally and writes enhanced notes.\n\n"
        "Coverage gates require 90% line coverage and 85% branch coverage.\n\n"
        "This paragraph only introduces the documentation.\n",
    )
    document = discover_primary_claim_documents(tmp_path)[0]

    claims = extract_material_claims(tmp_path, (document,))
    by_scope = {claim.material_scope: claim for claim in claims}

    capability = by_scope["capability.capture"]
    assert capability.exact_text == "Omni captures meetings locally and writes enhanced notes."
    assert (capability.source.path, capability.source.start_line, capability.source.end_line) == (
        "README.md",
        3,
        3,
    )
    assert by_scope["quality.coverage.line.target"].exact_text == (
        "Coverage gates require 90% line coverage and 85% branch coverage."
    )
    assert by_scope["quality.coverage.branch.target"].exact_text == (
        "Coverage gates require 90% line coverage and 85% branch coverage."
    )
    assert by_scope["quality.coverage.line.target"].claim_id != by_scope[
        "quality.coverage.branch.target"
    ].claim_id
    assert "documentation" not in " ".join(claim.exact_text for claim in claims).lower()


def test_search_links_source_configuration_and_tests_with_complete_inspections(tmp_path: Path) -> None:
    _write(tmp_path, "engine/audio/capture.py", "def capture_audio():\n    return 'local'\n")
    _write(tmp_path, "pyproject.toml", "[tool.omni]\ncapture_audio = true\n")
    _write(tmp_path, "tests/test_capture.py", "def test_capture_audio():\n    assert True\n")
    _write(tmp_path, "docs/features.md", "capture_audio is described here\n")
    _write(tmp_path, "node_modules/pkg/index.js", "capture_audio()\n")

    result = search_claim_traceability(tmp_path, ("capture_audio",))

    assert result.search_evidence.exhaustive is True
    assert result.search_evidence.exact_searches == ("literal:capture_audio",)
    assert {item.path for item in result.implementation_links} == {"engine/audio/capture.py"}
    assert {item.path for item in result.configuration_links} == {"pyproject.toml"}
    assert {item.path for item in result.test_links} == {"tests/test_capture.py"}
    assert {inspection.location.path for inspection in result.inspections} == {
        "engine/audio/capture.py",
        "pyproject.toml",
        "tests/test_capture.py",
    }
    assert all(inspection.qualifies for inspection in result.inspections)


def test_exhaustive_absence_produces_not_implemented_and_explicit_empty_links(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "engine/server.py", "def health():\n    return 'ok'\n")
    _write(tmp_path, "README.md", "Omni teleports meeting notes instantly.\n")
    claim = extract_material_claims(
        tmp_path,
        discover_primary_claim_documents(tmp_path),
    )[0]
    search = search_claim_traceability(tmp_path, ("teleport_notes",))

    decision = decide_claim_trace(
        ClaimTraceDecisionInput(
            claim=claim,
            search=search,
            documentary_claim_ref="README.md:1",
            asserts_current=True,
        )
    )

    assert decision.trace.implementation_links == ()
    assert decision.trace.configuration_links == ()
    assert decision.trace.test_links == ()
    assert decision.trace.primary_status is AssessmentStatus.NOT_IMPLEMENTED
    assert decision.trace.documentary_classification is DocumentaryClassification.UNSUPPORTED
    assert decision.trace.search_evidence_refs == (search.search_evidence.evidence_ref,)
    assert search.search_evidence.concluded_no_qualifying_implementation is True
    assert search.search_evidence.searched_scopes


def test_trace_decision_uses_precedence_and_links_historical_dates(tmp_path: Path) -> None:
    _write(tmp_path, "README.md", "Omni captures meetings locally.\n")
    _write(tmp_path, "engine/audio/capture.py", "CAPTURE_MODE = 'local'\n")
    claim = extract_material_claims(
        tmp_path,
        discover_primary_claim_documents(tmp_path),
    )[0]
    search = search_claim_traceability(tmp_path, ("CAPTURE_MODE",))
    history = HistoricalEvidenceCitation("history-2025", date(2025, 6, 1))
    evidence = (
        EvidenceSource(EvidenceTier.HISTORICAL, "partial", "history-2025", date(2025, 6, 1)),
        EvidenceSource(EvidenceTier.CODE, "local", "engine/audio/capture.py:1", None),
        EvidenceSource(EvidenceTier.CONFIGURATION, "disabled", "config:1", None),
        EvidenceSource(EvidenceTier.FRESH, "working", "fresh-run", date(2026, 7, 1)),
    )

    decision = decide_claim_trace(
        ClaimTraceDecisionInput(
            claim=claim,
            search=search,
            documentary_claim_ref="README.md:1",
            asserts_current=True,
            evidence=evidence,
            fresh_evidence_refs=("fresh-run",),
            historical_evidence=(history,),
            fresh_status=AssessmentStatus.VERIFIED_WORKING,
        )
    )

    assert decision.trace.conclusion == "working"
    assert decision.trace.precedence_basis.startswith("fresh_evidence")
    assert decision.trace.primary_status is AssessmentStatus.VERIFIED_WORKING
    assert decision.trace.fresh_evidence_refs == ("fresh-run",)
    assert decision.trace.historical_evidence_refs == ("history-2025",)
    assert decision.evidence_decision.conflict is not None
    assert {item.source for item in decision.evidence_decision.conflict.evidence} == {
        "history-2025",
        "engine/audio/capture.py:1",
        "config:1",
        "fresh-run",
    }
