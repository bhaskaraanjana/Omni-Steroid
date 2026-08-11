"""Assemble immutable assessment reports and exact row-level status accounting.

This synthesis stage groups checks by verification plane and projects claims,
checks, subsets, and parity rows into the canonical accounting implementation.
"""

from __future__ import annotations

from dataclasses import dataclass

from .baseline_models import AssessmentBaseline
from .claim_models import ClaimTrace
from .committed_metric_reconciliation import CommittedMetricReconciliation
from .model_types import AssessmentStatus, VerificationPlane
from .report_models import (
    DenseRetrievalReportEntry,
    EfficacySection,
    ParityRow,
    VerificationFinding,
)
from .report_traceability import ActionableConclusions
from .run_models import WorkspaceComparison
from .security_records import SecurityControl, SecurityRecordCollection
from .status_accounting import (
    ClassifiedRow,
    ClassifiedRowKind,
    StatusSummary,
    summarize_classified_rows,
)
from .stt_accuracy import STTAccuracyReportEntry


@dataclass(frozen=True, slots=True)
class VerificationPlaneSection:
    """All verification findings assigned to one fixed report plane."""

    plane: VerificationPlane
    findings: tuple[VerificationFinding, ...]


@dataclass(frozen=True, slots=True)
class AssessmentReport:
    """Complete immutable report awaiting fail-closed admission and rendering."""

    baseline: AssessmentBaseline
    claims: tuple[ClaimTrace, ...]
    plane_sections: tuple[VerificationPlaneSection, ...]
    subset_rows: tuple[ClassifiedRow, ...]
    parity_rows: tuple[ParityRow, ...]
    security_records: SecurityRecordCollection
    security_evidence_refs: tuple[tuple[SecurityControl, str], ...]
    actionable: ActionableConclusions
    metric_reconciliations: tuple[CommittedMetricReconciliation, ...]
    dense_retrieval: DenseRetrievalReportEntry
    stt_accuracy: STTAccuracyReportEntry
    efficacy: EfficacySection
    final_comparison: WorkspaceComparison
    schema_validated_evidence_ids: tuple[str, ...]
    status_summary: StatusSummary


def _children_by_parent(
    subset_rows: tuple[ClassifiedRow, ...],
) -> dict[str, tuple[str, ...]]:
    children: dict[str, list[str]] = {}
    for row in subset_rows:
        if row.row_kind is not ClassifiedRowKind.SUBSET:
            raise ValueError("subset_rows must contain only subset classified rows")
        if row.parent_row_id is None or row.subset_key is None:
            raise ValueError("subset rows require parent and subset identifiers")
        children.setdefault(row.parent_row_id, []).append(row.subset_key)
    return {parent: tuple(keys) for parent, keys in children.items()}


def _parent_row(
    row_id: str,
    kind: ClassifiedRowKind,
    status: AssessmentStatus,
    child_keys: dict[str, tuple[str, ...]],
) -> ClassifiedRow:
    required = child_keys.get(row_id, ()) if status is AssessmentStatus.VERIFIED_PARTIAL else ()
    return ClassifiedRow(row_id, kind, status, required_subset_keys=required)


def _classified_rows(report: AssessmentReport) -> tuple[ClassifiedRow, ...]:
    """Reproject current report content for independent admission reconciliation."""
    child_keys = _children_by_parent(report.subset_rows)
    claims = tuple(
        _parent_row(
            trace.claim.claim_id, ClassifiedRowKind.CLAIM, trace.primary_status, child_keys
        )
        for trace in report.claims
    )
    checks = tuple(
        _parent_row(finding.check_id, ClassifiedRowKind.CHECK, finding.status, child_keys)
        for section in report.plane_sections
        for finding in section.findings
    )
    parity = tuple(
        _parent_row(row.row_id, ClassifiedRowKind.PARITY, row.primary_status, child_keys)
        for row in report.parity_rows
    )
    return claims + checks + report.subset_rows + parity


def synthesize_assessment_report(
    *,
    baseline: AssessmentBaseline,
    claims: tuple[ClaimTrace, ...],
    verification_findings: tuple[VerificationFinding, ...],
    subset_rows: tuple[ClassifiedRow, ...],
    parity_rows: tuple[ParityRow, ...],
    security_records: SecurityRecordCollection,
    security_evidence_refs: tuple[tuple[SecurityControl, str], ...],
    actionable: ActionableConclusions,
    metric_reconciliations: tuple[CommittedMetricReconciliation, ...],
    dense_retrieval: DenseRetrievalReportEntry,
    stt_accuracy: STTAccuracyReportEntry,
    efficacy: EfficacySection,
    final_comparison: WorkspaceComparison,
    schema_validated_evidence_ids: tuple[str, ...],
) -> AssessmentReport:
    """Build every fixed plane section and derive totals from classified rows."""
    sections = tuple(
        VerificationPlaneSection(
            plane,
            tuple(finding for finding in verification_findings if finding.plane is plane),
        )
        for plane in VerificationPlane
    )
    provisional = AssessmentReport(
        baseline, claims, sections, subset_rows, parity_rows, security_records,
        security_evidence_refs, actionable, metric_reconciliations, dense_retrieval,
        stt_accuracy, efficacy, final_comparison, schema_validated_evidence_ids,
        StatusSummary(baseline.run_id, (), 0, ""),
    )
    summary = summarize_classified_rows(baseline.run_id, _classified_rows(provisional))
    return AssessmentReport(
        baseline, claims, sections, subset_rows, parity_rows, security_records,
        security_evidence_refs, actionable, metric_reconciliations, dense_retrieval,
        stt_accuracy, efficacy, final_comparison, schema_validated_evidence_ids, summary,
    )
