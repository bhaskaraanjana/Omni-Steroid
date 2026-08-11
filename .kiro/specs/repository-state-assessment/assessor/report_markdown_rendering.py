"""Render admitted assessment data in the required deterministic section order."""

from __future__ import annotations

from .report_markdown_sections import (
    render_baseline,
    render_claims,
    render_dense_retrieval,
    render_efficacy,
    render_evidence_index,
    render_final_comparison,
    render_metrics,
    render_parity_matrix,
    render_plane,
    render_ranked_actions,
    render_security,
    render_status_summary,
    render_stt,
)
from .report_synthesis import AssessmentReport


def render_assessment_report_markdown(report: AssessmentReport) -> str:
    """Render every fixed report section once without inferring absent measurements."""
    sections = [
        render_baseline(report),
        render_status_summary(report),
        render_claims(report),
        *(render_plane(section) for section in report.plane_sections),
        render_metrics(report),
        render_dense_retrieval(report),
        render_stt(report),
        render_parity_matrix(report),
        render_security(report),
        render_evidence_index(report),
        render_ranked_actions(report),
        render_efficacy(report),
        render_final_comparison(report),
    ]
    lines = ["# Repository State Assessment"]
    for section in sections:
        lines.extend(("", *section))
    return "\n".join(lines) + "\n"
