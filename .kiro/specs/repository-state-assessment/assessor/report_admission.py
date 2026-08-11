"""Apply fail-closed gates before an assessment report may be published.

Admission independently recomputes shape, accounting, evidence reachability, source
preservation, and sanitization invariants so post-synthesis mutations cannot pass.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass

from .evidence_precedence import EvidenceTier
from .model_types import AssessmentStatus, VerificationPlane
from .report_markdown_rendering import render_assessment_report_markdown
from .report_synthesis import AssessmentReport, _classified_rows
from .security_records import SecurityControl
from .status_accounting import summarize_classified_rows

_CANONICAL_PARITY_ROW_COUNT = 29
_COMMITTED_VALUES = (
    ("committed_test_count", "1,358 tests"),
    ("committed_line_coverage", "86.7 percent"),
    ("committed_branch_coverage", "78.2 percent"),
)


@dataclass(frozen=True, slots=True)
class ReportAdmissionDecision:
    """Whether a synthesized report passed every publication gate and why not."""

    admitted: bool
    reasons: tuple[str, ...]


def _shape_reasons(report: AssessmentReport) -> list[str]:
    reasons: list[str] = []
    if tuple(section.plane for section in report.plane_sections) != tuple(VerificationPlane):
        reasons.append("verification plane sections are incomplete or out of order")
    for section in report.plane_sections:
        if any(finding.plane is not section.plane for finding in section.findings):
            reasons.append("verification finding is assigned to the wrong plane section")
            break

    check_ids = tuple(
        finding.check_id
        for section in report.plane_sections
        for finding in section.findings
    )
    if len(check_ids) != len(set(check_ids)):
        reasons.append("duplicate findings exist within the report plane sections")

    parity_ids = tuple(row.row_id for row in report.parity_rows)
    if len(report.parity_rows) != _CANONICAL_PARITY_ROW_COUNT:
        reasons.append("capability parity matrix must contain exactly 29 rows")
    elif len(parity_ids) != len(set(parity_ids)):
        reasons.append("capability parity matrix contains duplicate rows")

    controls = tuple(record.control for record in report.security_records.records)
    if controls != tuple(SecurityControl):
        reasons.append("security records must contain every control exactly once in order")
    security_ref_controls = tuple(control for control, _ in report.security_evidence_refs)
    if security_ref_controls != tuple(SecurityControl):
        reasons.append("security evidence references must cover every control exactly once")
    return reasons


def _accounting_reasons(report: AssessmentReport) -> list[str]:
    try:
        expected = summarize_classified_rows(report.baseline.run_id, _classified_rows(report))
    except (TypeError, ValueError) as error:
        return [f"status total reconstruction failed: {error}"]
    actual = report.status_summary
    if (
        actual.collection_id != expected.collection_id
        or actual.classified_row_count != expected.classified_row_count
        or actual.status_totals != expected.status_totals
        or actual.row_id_checksum != expected.row_id_checksum
        or sum(total.count for total in actual.status_totals)
        != actual.classified_row_count
    ):
        return ["status totals do not reconcile with classified report rows"]
    if tuple(total.status for total in actual.status_totals) != tuple(AssessmentStatus):
        return ["status total inventory is incomplete or out of order"]
    return []


def _referenced_evidence_ids(report: AssessmentReport) -> set[str]:
    references = {
        ref
        for trace in report.claims
        for ref in (
            trace.search_evidence_refs
            + trace.fresh_evidence_refs
            + trace.historical_evidence_refs
        )
    }
    references.update(
        ref
        for section in report.plane_sections
        for finding in section.findings
        for ref in finding.evidence_refs
    )
    references.update(
        ref for row in report.parity_rows for ref in row.fresh_evidence_refs
    )
    references.update(
        measurement.evidence_ref
        for row in report.parity_rows
        for measurement in row.measurements
        if measurement.evidence_ref is not None
    )
    references.update(item.evidence_id for item in report.actionable.evidence)
    references.update(
        ref
        for conclusion in report.actionable.conclusions
        for ref in conclusion.evidence_refs
    )
    references.update(
        ref for finding in report.actionable.findings for ref in finding.evidence_refs
    )
    references.update(ref for _, ref in report.security_evidence_refs)
    references.add(report.dense_retrieval.evidence_ref)
    references.add(report.stt_accuracy.evidence_reference)
    references.update(
        source.source
        for metric in report.metric_reconciliations
        for source in metric.sources
        if source.tier in (EvidenceTier.FRESH, EvidenceTier.HISTORICAL)
    )
    return references


def _evidence_reasons(report: AssessmentReport) -> list[str]:
    validated = report.schema_validated_evidence_ids
    if any(not evidence_id for evidence_id in validated) or len(validated) != len(set(validated)):
        return ["schema-validated evidence identifiers must be non-empty and unique"]
    missing = _referenced_evidence_ids(report) - set(validated)
    if missing:
        return [f"schema validation is missing referenced evidence IDs: {sorted(missing)}"]
    return []


def _metric_reasons(report: AssessmentReport) -> list[str]:
    observed = tuple(
        (item.metric_id, item.committed_value) for item in report.metric_reconciliations
    )
    if observed != _COMMITTED_VALUES:
        return ["committed metric claims are missing, changed, or out of order"]
    if any(item.decision.selected is None for item in report.metric_reconciliations):
        return ["committed metric reconciliation lacks a selected conclusion"]
    return []


def _measurement_reasons(report: AssessmentReport) -> list[str]:
    if report.stt_accuracy.word_error_rate_percent is None:
        if not report.stt_accuracy.blockers:
            return ["unmeasured STT accuracy lacks a blocking condition"]
    elif report.stt_accuracy.blockers:
        return ["measured STT accuracy cannot retain blocking conditions"]
    if not report.dense_retrieval.dense_available and not report.dense_retrieval.note.strip():
        return ["unavailable dense retrieval lacks an explanatory note"]
    return []



def _string_content(value: object) -> tuple[str, ...]:
    """Collect report string leaves in field order without serialization punctuation."""
    if isinstance(value, str):
        return (value,)
    if isinstance(value, tuple):
        return tuple(part for item in value for part in _string_content(item))
    if is_dataclass(value) and not isinstance(value, type):
        return tuple(
            part
            for field in fields(value)
            for part in _string_content(getattr(value, field.name))
        )
    return ()


def _reconstructable_from_fields(value: str, content: tuple[str, ...]) -> bool:
    """Detect a sensitive value assembled from ordered field-edge fragments."""
    if any(value in item for item in content):
        return True
    for split_at in range(1, len(value)):
        prefix = value[:split_at]
        suffix = value[split_at:]
        for index, item in enumerate(content):
            if item.endswith(prefix) and any(
                later.startswith(suffix) for later in content[index + 1 :]
            ):
                return True
    return False


def _contains_sensitive_content(
    report: AssessmentReport,
    forbidden_sensitive_values: tuple[str, ...],
) -> bool:
    """Fail closed on empty values, contiguous matches, and field-boundary reconstruction."""
    if any(not value for value in forbidden_sensitive_values):
        return True
    serialized_report = repr(report)
    rendered_report = render_assessment_report_markdown(report)
    content = _string_content(report)
    return any(
        value in serialized_report
        or value in rendered_report
        or _reconstructable_from_fields(value, content)
        for value in forbidden_sensitive_values
    )

def admit_assessment_report(
    report: AssessmentReport,
    forbidden_sensitive_values: tuple[str, ...] = (),
) -> ReportAdmissionDecision:
    """Admit only reports satisfying every publication and preservation invariant."""
    reasons = _shape_reasons(report)
    reasons.extend(_accounting_reasons(report))
    reasons.extend(_evidence_reasons(report))
    reasons.extend(_metric_reasons(report))
    reasons.extend(_measurement_reasons(report))

    if not report.final_comparison.preservation_confirmed:
        reasons.append("source workspace mismatch: final comparison did not preserve production")

    if _contains_sensitive_content(report, forbidden_sensitive_values):
        reasons.append("sensitive content remains in the assessment report")
    return ReportAdmissionDecision(not reasons, tuple(reasons))
