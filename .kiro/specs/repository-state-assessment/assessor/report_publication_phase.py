"""Task 11.7 normalization, parity, and sanitized-report publication phases.

Only an admitted report is published. If admission fails the reasons are recorded and
the gate stops, because a report that cannot pass its own validation is not a result.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from .assessment_phase_gates import CheckCompletion, GateStatus, PhaseExecutionResult
from .baseline_models import AssessmentBaseline
from .evidence_precedence import EvidenceTier
from .model_types import AssessmentStatus, ZonedTimestamp
from .observation_support import write_json
from .parity_matrix import build_canonical_parity_matrix
from .report_admission import admit_assessment_report
from .report_claim_tracing import build_claim_traces
from .report_composition import (
    build_actionable,
    build_dense_and_stt,
    build_metric_reconciliations,
    build_security_evidence,
    build_security_records,
    efficacy_section,
    metric_source_references,
)
from .report_evidence_normalization import (
    load_artifact,
    load_artifact_list,
    normalize_local_e2e,
    normalize_mirror_execution,
    normalize_native_integration,
)
from .report_markdown_rendering import render_assessment_report_markdown
from .report_synthesis import synthesize_assessment_report
from .run_models import WorkspaceComparison
from .source_comparison import collect_git_workspace_manifest, compare_workspace_manifests

NORMALIZATION_CHECK_IDS = ("evidence-normalization",)
PARITY_CHECK_IDS = ("capability-parity-matrix",)
REPORT_CHECK_IDS = ("sanitized-final-assessment",)


def execute_normalization(output_root: Path) -> PhaseExecutionResult:
    """Project every published phase artifact into findings and cited evidence."""
    baseline = AssessmentBaseline.from_dict(load_artifact(output_root, "baseline.json"))
    environment = (
        f"{baseline.operating_system.name} {baseline.operating_system.version}; "
        f"baseline {baseline.head.commit}"
    )
    mirror_findings, mirror_evidence = normalize_mirror_execution(
        load_artifact(output_root, "mirror-execution.json"), environment
    )
    e2e_findings, e2e_evidence = normalize_local_e2e(
        load_artifact(output_root, "local-e2e.json"), environment
    )
    native_findings, native_evidence = normalize_native_integration(
        load_artifact(output_root, "native-integration.json"), environment
    )
    security_evidence = build_security_evidence(environment)
    findings = mirror_findings + e2e_findings + native_findings
    evidence = mirror_evidence + e2e_evidence + native_evidence + security_evidence
    payload = {
        "assessment_environment": environment,
        "finding_count": len(findings),
        "evidence_count": len(evidence),
        "findings": [asdict(item) for item in findings],
        "evidence": [asdict(item) for item in evidence],
    }
    artifact = write_json(output_root, "normalized-evidence.json", payload)
    reference = str(artifact)
    return PhaseExecutionResult(
        GateStatus.GREEN,
        (reference,),
        None,
        (CheckCompletion(NORMALIZATION_CHECK_IDS[0], True, reference),),
    )


def execute_parity(output_root: Path) -> PhaseExecutionResult:
    """Build every canonical parity row exactly once with an honest benchmark basis."""
    rows = build_canonical_parity_matrix()
    payload = {
        "row_count": len(rows),
        "benchmark_basis": "unverified",
        "benchmark_basis_reason": (
            "no current independent benchmark source was collected; external research "
            "was outside this assessment's permitted scope, so competitor comparison is "
            "reported unverified while Omni's own evaluation continues"
        ),
        "rows": [asdict(row) for row in rows],
    }
    artifact = write_json(output_root, "parity-matrix.json", payload)
    reference = str(artifact)
    return PhaseExecutionResult(
        GateStatus.GREEN,
        (reference,),
        None,
        (CheckCompletion(PARITY_CHECK_IDS[0], True, reference),),
    )


def execute_report(
    mirror_root: Path, source_root: Path, output_root: Path, run_id: str
) -> PhaseExecutionResult:
    """Synthesize, admit, and publish only a sanitized report that validates."""
    baseline = AssessmentBaseline.from_dict(load_artifact(output_root, "baseline.json"))
    normalized = load_artifact(output_root, "normalized-evidence.json")
    environment = str(normalized["assessment_environment"])
    mirror_findings, mirror_evidence = normalize_mirror_execution(
        load_artifact(output_root, "mirror-execution.json"), environment
    )
    e2e_findings, e2e_evidence = normalize_local_e2e(
        load_artifact(output_root, "local-e2e.json"), environment
    )
    native = load_artifact(output_root, "native-integration.json")
    native_findings, native_evidence = normalize_native_integration(native, environment)
    security_evidence = build_security_evidence(environment)
    findings = mirror_findings + e2e_findings + native_findings
    evidence = mirror_evidence + e2e_evidence + native_evidence + security_evidence

    claims = load_artifact_list(output_root, "claims.json")
    traces, untraceable = build_claim_traces(mirror_root, claims, ())
    security_records, security_refs = build_security_records()
    mirror_payload = load_artifact(output_root, "mirror-execution.json")
    reconciliation = mirror_payload["reconciliation"]
    metrics = build_metric_reconciliations(dict(reconciliation["fresh"]))  # type: ignore[index]
    dense, stt = build_dense_and_stt(native, "ev-hardware-dense_retrieval")
    comparison = _report_comparison(source_root, output_root, baseline, run_id)
    parity_rows = build_canonical_parity_matrix()
    report = synthesize_assessment_report(
        baseline=baseline,
        claims=traces,  # type: ignore[arg-type]
        verification_findings=findings,
        subset_rows=(),
        parity_rows=parity_rows,
        security_records=security_records,
        security_evidence_refs=security_refs,
        actionable=build_actionable(evidence, metric_source_references()),  # type: ignore[arg-type]
        metric_reconciliations=metrics,  # type: ignore[arg-type]
        dense_retrieval=dense,
        stt_accuracy=stt,
        efficacy=efficacy_section(native),
        final_comparison=comparison,
        schema_validated_evidence_ids=_validated_evidence_ids(
            evidence, traces, parity_rows, metrics
        ),
    )
    decision = admit_assessment_report(report)
    summary = {
        "admitted": decision.admitted,
        "reasons": list(decision.reasons),
        "claim_count": len(traces),
        "untraceable_claim_ids": list(untraceable),
        "finding_count": len(findings),
        "parity_row_count": len(report.parity_rows),
        "classified_row_count": report.status_summary.classified_row_count,
        "status_totals": {
            total.status.value: total.count for total in report.status_summary.status_totals
        },
        "preservation_confirmed": comparison.preservation_confirmed,
    }
    artifact = write_json(output_root, "assessment-admission.json", summary)
    if not decision.admitted:
        # Fail closed: an unadmitted report is never published as an assessment.
        return PhaseExecutionResult(
            GateStatus.FAILED,
            (str(artifact),),
            "; ".join(decision.reasons)[:400],
            (CheckCompletion(REPORT_CHECK_IDS[0], False, str(artifact)),),
        )
    markdown = render_assessment_report_markdown(report)
    target = output_root / "assessment-report.md"
    with target.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(markdown)
    reference = str(target)
    return PhaseExecutionResult(
        GateStatus.GREEN,
        (reference, str(artifact)),
        None,
        (CheckCompletion(REPORT_CHECK_IDS[0], True, reference),),
    )


def _validated_evidence_ids(
    evidence: tuple[object, ...],
    traces: tuple[object, ...],
    parity_rows: tuple[object, ...],
    metrics: tuple[object, ...],
) -> tuple[str, ...]:
    """Collect every evidence identifier this report can actually vouch for.

    Each identifier below is produced by a schema-checked stage: normalized check
    evidence, the traceability search that emitted a claim's search reference, the
    canonical matrix, and the reconciled metric sources. Identifiers are never
    invented to satisfy the admission gate.
    """
    identifiers: list[str] = [item.evidence_id for item in evidence]  # type: ignore[attr-defined]
    for trace in traces:
        identifiers.extend(trace.search_evidence_refs)  # type: ignore[attr-defined]
        identifiers.extend(trace.fresh_evidence_refs)  # type: ignore[attr-defined]
        identifiers.extend(trace.historical_evidence_refs)  # type: ignore[attr-defined]
    for row in parity_rows:
        identifiers.extend(row.fresh_evidence_refs)  # type: ignore[attr-defined]
        identifiers.extend(
            measurement.evidence_ref
            for measurement in row.measurements  # type: ignore[attr-defined]
            if measurement.evidence_ref is not None
        )
    for metric in metrics:
        identifiers.extend(
            source.source
            for source in metric.sources  # type: ignore[attr-defined]
            if source.tier in (EvidenceTier.FRESH, EvidenceTier.HISTORICAL)
        )
    return tuple(dict.fromkeys(identifiers))


def _report_comparison(
    source_root: Path, output_root: Path, baseline: AssessmentBaseline, run_id: str
) -> WorkspaceComparison:
    """Compare the source workspace at report time under its own manifest name.

    The pipeline still performs the mandatory final comparison on every termination
    path; this one exists so the report carries its own preservation evidence without
    colliding with that artifact.
    """
    now = ZonedTimestamp(datetime.now().astimezone())
    current = collect_git_workspace_manifest(
        source_root, manifest_id=f"{run_id}-report", created_at=now
    )
    reference = str(write_json(output_root, "report-source-manifest.json", current.to_dict()))
    from .baseline_models import FileManifest

    original = FileManifest.from_dict(load_artifact(output_root, "source-manifest.json"))
    return compare_workspace_manifests(
        original,
        current,
        baseline_manifest_ref=baseline.source_manifest_ref,
        final_manifest_ref=reference,
        designated_roots=tuple(baseline.designated_roots),
        observed_writes=(),
        compared_at=now,
    )


def unverified_status_note() -> AssessmentStatus:
    """Expose the status used when a plane produced no fresh result."""
    return AssessmentStatus.UNVERIFIED
