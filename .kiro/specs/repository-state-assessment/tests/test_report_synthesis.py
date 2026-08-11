"""Task 10.3 tests for evidence-backed report synthesis and admission.

**Validates: Requirements 9.1–9.14**
"""

from dataclasses import replace
from datetime import date, datetime, timezone

import pytest

from assessor import (
    AssessmentBaseline, AssessmentStatus, BenchmarkSet, CitedEvidence,
    DenseRetrievalReportEntry, DocumentaryClaim, DocumentaryClassification,
    EfficacySection, EvidenceSource, EvidenceTier, ExactArgumentVector,
    FindingCandidate, FindingCategory, NextActionDisposition, OperatingSystemInventory,
    RepositoryHead, RepositoryHeadKind, RerunInstruction, SecurityControl,
    SecurityRecord, SecurityRecordCollection, SourceLocation, SourceReference,
    STTAccuracyReportEntry, VerificationFinding, VerificationMethods,
    VerificationPlane, WorkspaceComparison, ZonedTimestamp,
    admit_assessment_report, build_canonical_parity_matrix,
    reconcile_committed_metrics, render_assessment_report_markdown,
    synthesize_actionable_conclusions, synthesize_assessment_report,
)
from assessor.claim_models import ClaimTrace


NOW = ZonedTimestamp(datetime(2026, 7, 17, 12, tzinfo=timezone.utc))


def _source(source_id: str, line: int) -> SourceReference:
    return SourceReference(source_id, SourceLocation("docs/evidence.md", line, line))


def _evidence(evidence_id: str, status: AssessmentStatus) -> CitedEvidence:
    prerequisite = "dense weights" if status is AssessmentStatus.ENVIRONMENT_BLOCKED else "python"
    return CitedEvidence(
        evidence_id, status,
        RerunInstruction((prerequisite,), ExactArgumentVector(("python", "-m", "pytest")), None, "terminates with recorded result"),
        "Windows 11; baseline commit abc",
        prerequisite if status is AssessmentStatus.ENVIRONMENT_BLOCKED else None,
        "preflight found no dense model directory" if status is AssessmentStatus.ENVIRONMENT_BLOCKED else None,
    )


def _baseline() -> AssessmentBaseline:
    return AssessmentBaseline(
        "run-10-3", "C:/DEV/Omni Steroid", RepositoryHead("abc", RepositoryHeadKind.BRANCH, "main"), NOW,
        (), (), ("concurrent.txt",), OperatingSystemInventory("Windows", "11", "26100"), (), (),
        "source-manifest.json", ("C:/assessment-output",), "mirror-manifest.json",
    )


def _claim() -> ClaimTrace:
    claim = DocumentaryClaim(
        "claim-local", "All data remains local.", SourceLocation("README.md", 10, 10), "local storage", date(2026, 7, 1)
    )
    return ClaimTrace(
        claim, (SourceLocation("engine/store.py", 1, 4),), (), (), (), ("ev-security-local_only_storage",), (),
        DocumentaryClassification.CURRENT, AssessmentStatus.VERIFIED_WORKING,
        "Fresh hermetic evidence verifies local storage.", "fresh_evidence is highest precedence",
    )


def _metric_sources() -> dict[str, tuple[EvidenceSource, ...]]:
    return {
        "committed_test_count": (
            EvidenceSource(EvidenceTier.DOCUMENTARY, "1,358 tests", "src-tests", date(2026, 6, 1)),
            EvidenceSource(EvidenceTier.CONFIGURATION, "repository-defined selected suite", "src-test-config", date(2026, 7, 10)),
            EvidenceSource(EvidenceTier.FRESH, "1,402 tests", "ev-Python_Engine", date(2026, 7, 17)),
        ),
        "committed_line_coverage": (
            EvidenceSource(EvidenceTier.DOCUMENTARY, "86.7 percent", "src-line", date(2026, 6, 1)),
            EvidenceSource(EvidenceTier.CONFIGURATION, "90 percent target", "src-line-config", date(2026, 7, 10)),
            EvidenceSource(EvidenceTier.FRESH, "91.2 percent", "ev-Python_Engine", date(2026, 7, 17)),
        ),
        "committed_branch_coverage": (
            EvidenceSource(EvidenceTier.DOCUMENTARY, "78.2 percent", "src-branch", date(2026, 6, 1)),
            EvidenceSource(EvidenceTier.CONFIGURATION, "85 percent target", "src-branch-config", date(2026, 7, 10)),
            EvidenceSource(EvidenceTier.FRESH, "87.4 percent", "ev-Python_Engine", date(2026, 7, 17)),
        ),
    }


def _report():
    findings = tuple(
        VerificationFinding(
            f"check-{plane.value}", plane, f"{plane.value} assessed scope",
            AssessmentStatus.ENVIRONMENT_BLOCKED if plane is VerificationPlane.HARDWARE_INTEGRATION else AssessmentStatus.VERIFIED_WORKING,
            f"{plane.value} conclusion", (f"ev-{plane.value}",),
        )
        for plane in VerificationPlane
        if plane is not VerificationPlane.SECURITY_PRIVACY
    ) + tuple(
        VerificationFinding(
            f"security-{control.value}", VerificationPlane.SECURITY_PRIVACY, control.value,
            AssessmentStatus.VERIFIED_WORKING, f"{control.value} conclusion",
            (f"ev-security-{control.value}",),
        )
        for control in SecurityControl
    )
    evidence = tuple(
        _evidence(
            f"ev-{plane.value}",
            AssessmentStatus.ENVIRONMENT_BLOCKED if plane is VerificationPlane.HARDWARE_INTEGRATION else AssessmentStatus.VERIFIED_WORKING,
        )
        for plane in VerificationPlane
        if plane is not VerificationPlane.SECURITY_PRIVACY
    ) + tuple(
        _evidence(f"ev-security-{control.value}", AssessmentStatus.VERIFIED_WORKING)
        for control in SecurityControl
    )
    source_ids = ("src-tests", "src-test-config", "src-line", "src-line-config", "src-branch", "src-branch-config")
    sources = tuple(_source(source_id, index + 1) for index, source_id in enumerate(source_ids))
    actionable = synthesize_actionable_conclusions(
        (), evidence, sources,
        (FindingCandidate(
            "finding-dense", FindingCategory.VERIFICATION_GAP, "Dense retrieval is unavailable", 5,
            AssessmentStatus.ENVIRONMENT_BLOCKED, ("ev-Hardware_Integration",), (),
            NextActionDisposition.VALIDATE, "A fresh dense-tier retrieval evidence record",
        ),),
    )
    methods = VerificationMethods(True, False, True, False, False)
    security = SecurityRecordCollection(
        tuple(SecurityRecord(control, methods, (), ()) for control in SecurityControl), (),
    )
    comparison = WorkspaceComparison(
        "source-manifest.json", "final-manifest.json", True, True, True, (), (), NOW,
    )
    stt = STTAccuracyReportEntry(
        None, None, None, None, None, None, ("labelled speech corpus",),
        AssessmentStatus.ENVIRONMENT_BLOCKED, "ev-Hardware_Integration",
    )
    return synthesize_assessment_report(
        baseline=_baseline(), claims=(_claim(),), verification_findings=findings,
        subset_rows=(), parity_rows=build_canonical_parity_matrix(),
        security_records=security,
        security_evidence_refs=tuple(
            (control, f"ev-security-{control.value}") for control in SecurityControl
        ),
        actionable=actionable,
        metric_reconciliations=reconcile_committed_metrics(_metric_sources()),
        dense_retrieval=DenseRetrievalReportEntry(False, AssessmentStatus.ENVIRONMENT_BLOCKED, "ev-Hardware_Integration", "Dense weights were absent; fallback is reported separately."),
        stt_accuracy=stt, efficacy=EfficacySection((), "No fresh user-facing efficacy measurement was produced."),
        final_comparison=comparison,
        schema_validated_evidence_ids=tuple(item.evidence_id for item in evidence),
    )


def test_synthesis_reconciles_claims_and_builds_every_fixed_section() -> None:
    report = _report()

    assert tuple(section.plane for section in report.plane_sections) == tuple(VerificationPlane)
    assert report.status_summary.classified_row_count == 45  # 1 claim + 15 checks + 29 parity rows
    assert sum(total.count for total in report.status_summary.status_totals) == 45
    assert len(report.parity_rows) == 29
    assert {row.benchmark_set for row in report.parity_rows} == {BenchmarkSet.GRANOLA, BenchmarkSet.WISPR_FLOW}
    assert len(report.security_records.records) == 8
    assert all(len(record.methods.values()) == 5 for record in report.security_records.records)
    assert [item.decision.selected.value for item in report.metric_reconciliations] == [
        "1,402 tests", "91.2 percent", "87.4 percent",
    ]
    assert admit_assessment_report(report).admitted


def test_admission_blocks_each_fail_closed_defect_class() -> None:
    report = _report()
    missing_matrix = replace(report, parity_rows=report.parity_rows[:-1])
    wrong_total = replace(report, status_summary=replace(report.status_summary, classified_row_count=999))
    bad_schema = replace(report, schema_validated_evidence_ids=report.schema_validated_evidence_ids[:-1])
    mismatch = replace(report, final_comparison=replace(report.final_comparison, production_bytes_identical=False))
    duplicate_status = replace(
        report,
        plane_sections=(
            replace(report.plane_sections[0], findings=report.plane_sections[0].findings * 2),
            *report.plane_sections[1:],
        ),
    )

    cases = (
        (missing_matrix, "matrix"), (wrong_total, "total"), (bad_schema, "schema"),
        (mismatch, "source workspace mismatch"), (duplicate_status, "duplicate"),
    )
    for defective, expected in cases:
        decision = admit_assessment_report(defective)
        assert not decision.admitted
        assert expected in " ".join(decision.reasons).lower()

    secret_report = replace(
        report,
        efficacy=EfficacySection((), "unredacted-test-secret"),
    )
    secret_decision = admit_assessment_report(
        secret_report, forbidden_sensitive_values=("unredacted-test-secret",)
    )
    assert not secret_decision.admitted
    assert "sensitive" in " ".join(secret_decision.reasons).lower()


def test_markdown_keeps_efficacy_separate_and_never_invents_dense_or_stt_values() -> None:
    markdown = render_assessment_report_markdown(_report())

    assert "## User-facing efficacy (separate from tests and coverage)" in markdown
    assert "1,358 tests" in markdown and "86.7 percent" in markdown and "78.2 percent" in markdown
    assert "Dense weights were absent" in markdown
    assert "labelled speech corpus" in markdown
    assert "word error rate: unmeasured" in markdown.lower()
    assert "invented" not in markdown.lower()


def test_reconciliation_rejects_missing_or_changed_committed_claims() -> None:
    sources = _metric_sources()
    sources["committed_line_coverage"] = tuple(
        replace(item, value="86.8 percent") if item.tier is EvidenceTier.DOCUMENTARY else item
        for item in sources["committed_line_coverage"]
    )
    with pytest.raises(ValueError, match="86.7 percent"):
        reconcile_committed_metrics(sources)
