"""Task 10.4 report-example and admission tests.

Validates Requirements 4.6, 6.1–6.2, 7.11, 9.1–9.3, 9.7–9.10,
and 9.12–9.14.
"""

from __future__ import annotations

from dataclasses import fields, replace
from datetime import date

import pytest

from assessor import (
    AssessmentStatus,
    BenchmarkSet,
    EvidenceArtifact,
    EvidenceSource,
    EvidenceTier,
    FindingCandidate,
    FindingCategory,
    NextActionDisposition,
    STTAccuracyReportEntry,
    VerificationPlane,
    admit_assessment_report,
    reconcile_committed_metrics,
    render_assessment_report_markdown,
    synthesize_actionable_conclusions,
)
from test_report_synthesis import _metric_sources, _report


EXPECTED_SECTIONS = (
    "Baseline and preservation",
    "Status summary",
    "Documentary claim traceability",
    *(plane.value for plane in VerificationPlane),
    "Tests and coverage reconciliation",
    "Dense retrieval",
    "STT accuracy",
    "Capability parity matrix",
    "Security and privacy controls",
    "Evidence index and rerun instructions",
    "Ranked next actions",
    "User-facing efficacy (separate from tests and coverage)",
    "Final source-workspace comparison",
)
PARITY_COLUMNS = (
    "row_id",
    "benchmark_set",
    "benchmark_capability",
    "benchmark_source",
    "benchmark_source_date",
    "benchmark_basis_status",
    "omni_documentary_claim_refs",
    "implementation_locations",
    "fresh_evidence_refs",
    "primary_status",
    "limitation",
    "parity_conclusion",
    "measurements",
)


def _section_titles(markdown: str) -> tuple[str, ...]:
    return tuple(line.lstrip("# ") for line in markdown.splitlines() if line.startswith(("## ", "### ")))


def _with_historical_metrics():
    sources = _metric_sources()
    historical_values = {
        "committed_test_count": "1,390 tests",
        "committed_line_coverage": "88.4 percent",
        "committed_branch_coverage": "80.1 percent",
    }
    for metric_id, value in historical_values.items():
        sources[metric_id] += (
            EvidenceSource(EvidenceTier.HISTORICAL, value, f"history-{metric_id}", date(2026, 7, 12)),
        )
    return reconcile_committed_metrics(sources), historical_values


def test_fully_populated_report_has_the_exact_fixed_section_order() -> None:
    """Every required report section is emitted once in deterministic order."""
    markdown = render_assessment_report_markdown(_report())

    assert _section_titles(markdown) == EXPECTED_SECTIONS
    assert len(set(_section_titles(markdown))) == len(EXPECTED_SECTIONS)


def test_historical_current_and_fresh_metrics_remain_visible_with_fresh_selected() -> None:
    """Fresh metrics win without erasing documentary, current, or historical values."""
    reconciliations, historical = _with_historical_metrics()
    report = replace(_report(), metric_reconciliations=reconciliations)
    expected_selected = ("1,402 tests", "91.2 percent", "87.4 percent")

    assert tuple(item.decision.selected.value for item in reconciliations) == expected_selected
    assert all(
        {source.tier for source in item.sources}
        == {EvidenceTier.DOCUMENTARY, EvidenceTier.CONFIGURATION, EvidenceTier.FRESH, EvidenceTier.HISTORICAL}
        for item in reconciliations
    )
    markdown = render_assessment_report_markdown(report)
    for item in reconciliations:
        assert item.committed_value in markdown
        assert historical[item.metric_id] in markdown
        assert next(source.value for source in item.sources if source.tier is EvidenceTier.CONFIGURATION) in markdown
        assert item.decision.selected.value in markdown


@pytest.mark.parametrize(
    ("metric_id", "drifted", "expected"),
    (
        ("committed_test_count", "1,359 tests", "1,358 tests"),
        ("committed_line_coverage", "86.8 percent", "86.7 percent"),
        ("committed_branch_coverage", "78.3 percent", "78.2 percent"),
    ),
)
def test_documentary_metric_drift_names_the_pinned_value(metric_id: str, drifted: str, expected: str) -> None:
    """Each changed documentary claim is rejected with its exact committed value."""
    sources = _metric_sources()
    sources[metric_id] = tuple(
        replace(source, value=drifted) if source.tier is EvidenceTier.DOCUMENTARY else source
        for source in sources[metric_id]
    )

    message = f"{metric_id} documentary source must equal committed value {expected}"
    with pytest.raises(ValueError, match=message.replace(".", r"\.")):
        reconcile_committed_metrics(sources)


def test_canonical_matrix_has_exact_sets_unique_ids_and_columns() -> None:
    """The parity matrix is exactly 13 Granola plus 16 Wispr rows with all columns."""
    rows = _report().parity_rows
    granola = tuple(row for row in rows if row.benchmark_set is BenchmarkSet.GRANOLA)
    wispr = tuple(row for row in rows if row.benchmark_set is BenchmarkSet.WISPR_FLOW)

    assert (len(granola), len(wispr), len(rows)) == (13, 16, 29)
    assert len({row.row_id for row in rows}) == 29
    assert all(tuple(field.name for field in fields(row)) == PARITY_COLUMNS for row in rows)


@pytest.mark.parametrize("row_count", (28, 30))
def test_admission_refuses_both_under_and_overfilled_matrices(row_count: int) -> None:
    """A parity matrix one row short or one row over is refused, never normalized."""
    report = _report()
    rows = report.parity_rows[:28] if row_count == 28 else report.parity_rows + (report.parity_rows[0],)
    decision = admit_assessment_report(replace(report, parity_rows=rows))

    assert not decision.admitted
    assert "capability parity matrix must contain exactly 29 rows" in decision.reasons


def test_admission_refuses_a_duplicate_row_id_at_exact_matrix_size() -> None:
    """Twenty-nine rows are still invalid when two rows share an identity."""
    report = _report()
    duplicate = replace(report.parity_rows[-1], row_id=report.parity_rows[0].row_id)
    decision = admit_assessment_report(replace(report, parity_rows=report.parity_rows[:-1] + (duplicate,)))

    assert not decision.admitted
    assert "capability parity matrix contains duplicate rows" in decision.reasons


def test_blocked_check_keeps_complete_rerun_and_is_not_a_product_failure() -> None:
    """Blocked evidence remains visible, reproducible, and excluded from failures."""
    report = _report()
    blocked = tuple(item for item in report.actionable.evidence if item.primary_status is AssessmentStatus.ENVIRONMENT_BLOCKED)
    assert len(blocked) == 1
    item = blocked[0]
    assert item.unavailable_prerequisite == "dense weights"
    assert item.rerun.prerequisites == ("dense weights",)
    assert item.rerun.exact_argv.values == ("python", "-m", "pytest")
    assert item.rerun.numbered_procedure is None
    assert item.rerun.expected_observable == "terminates with recorded result"
    totals = {total.status: total.count for total in report.status_summary.status_totals}
    assert totals[AssessmentStatus.ENVIRONMENT_BLOCKED] == 1
    assert totals[AssessmentStatus.FRESH_FAILURE] == 0
    markdown = render_assessment_report_markdown(report)
    assert "dense weights" in markdown
    assert "python -m pytest" in markdown
    assert "terminates with recorded result" in markdown


def test_absent_screenshot_and_trace_are_explicit_report_markers() -> None:
    """Missing E2E artifacts are explicit markers, not an ambiguous empty collection."""
    absent = (EvidenceArtifact("screenshot", absent=True), EvidenceArtifact("trace", absent=True))
    assert tuple((item.kind, item.path, item.absent) for item in absent) == (
        ("screenshot", None, True),
        ("trace", None, True),
    )
    markdown = render_assessment_report_markdown(_report())
    assert "Screenshot: explicitly absent (no artifact generated)" in markdown
    assert "Trace: explicitly absent (no artifact generated)" in markdown


def test_ranked_findings_put_dependencies_first_with_one_disposition_each() -> None:
    """Impact ranking is unique while prerequisites precede findings they unblock."""
    evidence = _report().actionable.evidence
    ref = (evidence[0].evidence_id,)
    candidates = (
        FindingCandidate("dependent", FindingCategory.RELEASE_RISK, "release blocked", 10, AssessmentStatus.UNVERIFIED, ref, ("prerequisite",), NextActionDisposition.FIX, "release rerun"),
        FindingCandidate("independent", FindingCategory.DOCUMENTATION_DRIFT, "docs drift", 7, AssessmentStatus.UNVERIFIED, ref, (), NextActionDisposition.DEFER, "documentation review"),
        FindingCandidate("prerequisite", FindingCategory.VERIFICATION_GAP, "weights absent", 1, AssessmentStatus.ENVIRONMENT_BLOCKED, ref, (), NextActionDisposition.VALIDATE, "dense evidence"),
    )
    findings = synthesize_actionable_conclusions((), evidence, (), candidates).findings

    assert tuple((item.rank, item.finding_id) for item in findings) == (
        (1, "prerequisite"), (2, "dependent"), (3, "independent")
    )
    assert tuple(item.disposition for item in findings) == (
        NextActionDisposition.VALIDATE, NextActionDisposition.FIX, NextActionDisposition.DEFER
    )
    ranks = {item.finding_id: item.rank for item in findings}
    assert all(ranks[dependency] < item.rank for item in findings for dependency in item.dependency_ids)


def test_each_admission_defect_has_its_own_exact_reason_and_clean_report_passes() -> None:
    """Every fail-closed defect class is independently human-readable."""
    report = _report()
    defects = (
        (replace(report, schema_validated_evidence_ids=report.schema_validated_evidence_ids + ("",)), "schema-validated evidence identifiers must be non-empty and unique"),
        (replace(report, dense_retrieval=replace(report.dense_retrieval, evidence_ref="ev-missing-Ω")), "schema validation is missing referenced evidence IDs: ['ev-missing-Ω']"),
        (replace(report, plane_sections=(replace(report.plane_sections[0], findings=report.plane_sections[0].findings * 2), *report.plane_sections[1:])), "duplicate findings exist within the report plane sections"),
        (replace(report, status_summary=replace(report.status_summary, classified_row_count=report.status_summary.classified_row_count + 1)), "status totals do not reconcile with classified report rows"),
        (replace(report, parity_rows=report.parity_rows[:-1]), "capability parity matrix must contain exactly 29 rows"),
        (replace(report, efficacy=replace(report.efficacy, note="synthetic-sensitive-Ω")), "sensitive content remains in the assessment report"),
        (replace(report, final_comparison=replace(report.final_comparison, production_bytes_identical=False)), "source workspace mismatch: final comparison did not preserve production"),
    )
    reasons = []
    for defective, expected in defects:
        forbidden = ("synthetic-sensitive-Ω",) if "sensitive" in expected else ()
        decision = admit_assessment_report(defective, forbidden)
        assert not decision.admitted
        assert expected in decision.reasons
        reasons.append(expected)
    assert len(set(reasons)) == 7
    assert admit_assessment_report(report).reasons == ()
    assert admit_assessment_report(report).admitted


def test_sensitive_value_split_across_fields_is_quarantined() -> None:
    """Admission detects a forbidden Unicode value even when field boundaries split it."""
    report = _report()
    split = replace(
        report,
        dense_retrieval=replace(report.dense_retrieval, note=report.dense_retrieval.note + " synthetic-sensitive-"),
        efficacy=replace(report.efficacy, note="Ω remains quarantined"),
    )
    decision = admit_assessment_report(split, ("synthetic-sensitive-Ω",))

    assert not decision.admitted
    assert "sensitive content remains in the assessment report" in decision.reasons


def test_unmeasured_stt_is_not_zero_but_a_real_zero_survives() -> None:
    """Absent and measured-zero STT values remain semantically distinct."""
    report = _report()
    absent_markdown = render_assessment_report_markdown(report)
    zero = STTAccuracyReportEntry(0.0, 1, 2.5, "en-GB", "synthetic-model-Ω", "CPU", (), AssessmentStatus.VERIFIED_WORKING, "ev-Hardware_Integration")
    zero_markdown = render_assessment_report_markdown(replace(report, stt_accuracy=zero))

    assert "Word error rate: unmeasured" in absent_markdown
    assert "Word error rate: 0.0 percent" not in absent_markdown
    assert "Word error rate: 0.0 percent" in zero_markdown
    assert "synthetic-model-Ω" in zero_markdown
