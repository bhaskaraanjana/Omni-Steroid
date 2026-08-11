"""Render the fixed assessment report sections from immutable report facts.

Each function owns one publication section so the top-level renderer can enforce the
required order without hiding measurement or evidence-preservation decisions.
"""

from __future__ import annotations

from .model_types import SourceLocation
from .report_synthesis import AssessmentReport, VerificationPlaneSection


def _location(value: SourceLocation | None) -> str:
    if value is None:
        return "unavailable"
    return f"{value.path}:{value.start_line}-{value.end_line}"


def render_baseline(report: AssessmentReport) -> list[str]:
    """Render the captured source baseline and preservation inputs."""
    baseline = report.baseline
    roots = ", ".join(baseline.designated_roots) or "none"
    untracked = ", ".join(baseline.untracked_paths) or "none"
    return [
        "## Baseline and preservation",
        f"- Run: `{baseline.run_id}`",
        f"- Repository root: `{baseline.repository_root}`",
        f"- Repository head: `{baseline.head.render()}`",
        f"- Started at: {baseline.started_at.value.isoformat()}",
        f"- Operating system: {baseline.operating_system.name} {baseline.operating_system.version}",
        f"- Source manifest: `{baseline.source_manifest_ref}`",
        f"- Mirror manifest: `{baseline.mirror_manifest_ref or 'not produced'}`",
        f"- Designated output roots: {roots}",
        f"- Baseline untracked paths: {untracked}",
    ]


def render_status_summary(report: AssessmentReport) -> list[str]:
    """Render independently reconciled classified-row totals."""
    lines = ["## Status summary"]
    lines.extend(
        f"- {total.status.value}: {total.count}"
        for total in report.status_summary.status_totals
    )
    lines.extend(
        (
            f"- Classified rows: {report.status_summary.classified_row_count}",
            f"- Row checksum: `{report.status_summary.row_id_checksum}`",
        )
    )
    return lines


def render_claims(report: AssessmentReport) -> list[str]:
    """Render documentary claims with their current classification and evidence."""
    lines = ["## Documentary claim traceability"]
    if not report.claims:
        return lines + ["- No documentary claims"]
    for trace in report.claims:
        claim = trace.claim
        evidence = trace.fresh_evidence_refs + trace.historical_evidence_refs
        lines.append(
            f"- `{claim.claim_id}` — {claim.exact_text} | source: {_location(claim.source)}; "
            f"classification: {trace.documentary_classification.value}; status: "
            f"{trace.primary_status.value}; evidence: {', '.join(evidence) or 'none'}; "
            f"conclusion: {trace.conclusion}; precedence: {trace.precedence_basis}"
        )
    return lines


def render_plane(section: VerificationPlaneSection) -> list[str]:
    """Render one verification plane as its own required level-two section."""
    lines = [f"## {section.plane.value}"]
    if not section.findings:
        return lines + ["- No classified checks"]
    for finding in section.findings:
        lines.append(
            f"- `{finding.check_id}` — {finding.scope}: {finding.status.value}; "
            f"{finding.conclusion} (evidence: {', '.join(finding.evidence_refs)})"
        )
    return lines


def render_metrics(report: AssessmentReport) -> list[str]:
    """Render selected metrics while retaining every competing source value."""
    lines = ["## Tests and coverage reconciliation"]
    for metric in report.metric_reconciliations:
        selected = metric.decision.selected
        selected_value = "unmeasured" if selected is None else selected.value
        selected_tier = "none" if selected is None else selected.tier.value
        lines.extend(
            (
                f"- **{metric.metric_id}**",
                f"  - Committed claim: {metric.committed_value}",
                f"  - Selected conclusion: {selected_value} ({selected_tier})",
                f"  - Precedence basis: {metric.decision.precedence_basis}",
            )
        )
        for source in metric.sources:
            collected = "undated" if source.collected_on is None else source.collected_on.isoformat()
            lines.append(
                f"  - Source [{source.tier.value}]: {source.value}; "
                f"reference: {source.source}; collected: {collected}"
            )
    return lines


def render_dense_retrieval(report: AssessmentReport) -> list[str]:
    """Render dense retrieval availability without inferring a score."""
    dense = report.dense_retrieval
    availability = "available" if dense.dense_available else "unavailable"
    return [
        "## Dense retrieval",
        f"- Availability: {availability}",
        f"- Status: {dense.status.value}",
        f"- Evidence: {dense.evidence_ref}",
        f"- Note: {dense.note}",
    ]


def render_stt(report: AssessmentReport) -> list[str]:
    """Render unmeasured and measured-zero STT results as distinct states."""
    entry = report.stt_accuracy
    rate = "unmeasured" if entry.word_error_rate_percent is None else f"{entry.word_error_rate_percent} percent"
    lines = [
        "## STT accuracy",
        f"- Word error rate: {rate}",
        f"- Status: {entry.primary_status.value}",
        f"- Evidence: {entry.evidence_reference}",
    ]
    if entry.blockers:
        lines.append(f"- Blocking conditions: {', '.join(entry.blockers)}")
    if entry.word_error_rate_percent is not None:
        lines.extend(
            (
                f"- Corpus items: {entry.corpus_item_count}",
                f"- Audio duration seconds: {entry.total_audio_duration_seconds}",
                f"- Language: {entry.language}",
                f"- Local model: {entry.local_model}",
                f"- Hardware: {entry.hardware}",
            )
        )
    return lines


def render_parity_matrix(report: AssessmentReport) -> list[str]:
    """Render every canonical parity row and its independent measurement states."""
    lines = ["## Capability parity matrix"]
    for row in report.parity_rows:
        measurements = ", ".join(
            f"{item.dimension}={item.measurement.value if item.measurement is not None else 'unmeasured'}"
            for item in row.measurements
        ) or "none"
        lines.append(
            f"- `{row.row_id}` — {row.benchmark_set.value} / {row.benchmark_capability}; "
            f"benchmark source: {_location(row.benchmark_source)}; benchmark date: "
            f"{row.benchmark_source_date or 'undated'}; basis: {row.benchmark_basis_status.value}; "
            f"Omni status: {row.primary_status.value}; claim refs: "
            f"{', '.join(row.omni_documentary_claim_refs) or 'none'}; implementation: "
            f"{', '.join(_location(item) for item in row.implementation_locations) or 'none'}; "
            f"fresh evidence: {', '.join(row.fresh_evidence_refs) or 'none'}; "
            f"limitation: {row.limitation or 'none'}; conclusion: {row.parity_conclusion}; "
            f"measurements: {measurements}"
        )
    return lines


def render_security(report: AssessmentReport) -> list[str]:
    """Render each security control with all five verification method flags."""
    lines = ["## Security and privacy controls"]
    evidence_by_control = dict(report.security_evidence_refs)
    for record in report.security_records.records:
        methods = record.methods
        lines.append(
            f"- {record.control.value}: hermetic={methods.hermetic}, mocked={methods.mocked}, "
            f"local_loopback={methods.local_loopback}, hardware_backed={methods.hardware_backed}, "
            f"static_only={methods.static_only}; evidence: "
            f"{evidence_by_control.get(record.control, 'missing')}; output: "
            f"{'; '.join(record.relevant_output) or 'none'}; artifacts: "
            f"{', '.join(item.artifact_id for item in record.artifacts) or 'none'}"
        )
    withheld = ", ".join(report.security_records.withheld_artifact_ids) or "none"
    lines.append(f"- Withheld sensitive artifact IDs: {withheld}")
    return lines


def render_evidence_index(report: AssessmentReport) -> list[str]:
    """Render cited evidence with complete prerequisites, reruns, and outcomes."""
    lines = ["## Evidence index and rerun instructions"]
    for evidence in report.actionable.evidence:
        rerun = evidence.rerun
        prerequisites = ", ".join(rerun.prerequisites) or "none"
        if rerun.exact_argv is not None:
            procedure = " ".join(rerun.exact_argv.values)
        else:
            procedure = "; ".join(rerun.numbered_procedure or ())
        lines.append(
            f"- `{evidence.evidence_id}` — {evidence.primary_status.value}; prerequisites: "
            f"{prerequisites}; rerun: `{procedure}`; expected observable: "
            f"{rerun.expected_observable}; environment: {evidence.assessment_environment}; "
            f"unavailable prerequisite: {evidence.unavailable_prerequisite or 'none'}; "
            f"detection evidence: {evidence.detection_evidence or 'none'}"
        )
    for source in report.actionable.sources:
        lines.append(f"- Source `{source.source_id}`: {_location(source.location)}")
    # The report carries no E2E artifact paths, so absence must be explicit rather than ambiguous.
    lines.extend(
        (
            "- Screenshot: explicitly absent (no artifact generated)",
            "- Trace: explicitly absent (no artifact generated)",
        )
    )
    return lines


def render_ranked_actions(report: AssessmentReport) -> list[str]:
    """Render dependency-ordered findings with exactly one disposition each."""
    lines = ["## Ranked next actions"]
    if not report.actionable.findings:
        return lines + ["- None"]
    for finding in report.actionable.findings:
        dependencies = ", ".join(finding.dependency_ids) or "none"
        lines.append(
            f"- {finding.rank}. `{finding.finding_id}` — {finding.disposition.value}: "
            f"{finding.impact}; dependencies: {dependencies}; completion evidence: "
            f"{finding.completion_evidence_required}"
        )
    return lines


def render_efficacy(report: AssessmentReport) -> list[str]:
    """Render user-facing efficacy separately from test and coverage metrics."""
    lines = ["## User-facing efficacy (separate from tests and coverage)"]
    if report.efficacy.rows:
        lines.extend(
            f"- {row.name}: {row.value} {row.unit.value} ({row.assessed_scope})"
            for row in report.efficacy.rows
        )
    else:
        lines.append("- Measurements: unmeasured")
    lines.append(f"- Note: {report.efficacy.note}")
    return lines


def render_final_comparison(report: AssessmentReport) -> list[str]:
    """Render the final source-workspace preservation decision and differences."""
    comparison = report.final_comparison
    lines = [
        "## Final source-workspace comparison",
        f"- Baseline manifest: `{comparison.baseline_manifest_ref}`",
        f"- Final manifest: `{comparison.final_manifest_ref}`",
        f"- Tracked paths identical: {comparison.tracked_paths_identical}",
        f"- Untracked paths identical: {comparison.untracked_paths_identical}",
        f"- Production bytes identical: {comparison.production_bytes_identical}",
        f"- Preservation confirmed: {comparison.preservation_confirmed}",
        f"- Writes outside designated roots: {', '.join(comparison.writes_outside_designated_roots) or 'none'}",
        f"- Compared at: {comparison.compared_at.value.isoformat() if comparison.compared_at else 'unmeasured'}",
    ]
    lines.extend(f"- Difference: {difference}" for difference in comparison.differences)
    return lines
