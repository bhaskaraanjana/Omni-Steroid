"""Render an unmistakably partial assessment when a hard gate or stop is reached.

This fallback is outside the admitted final-report phase. It never fills absent phases
with success and records whether the mandatory final comparison confirmed preservation.
"""

from __future__ import annotations

from .assessment_phase_gates import AssessmentPhase
from .run_manifest_append_store import ReconstructedRunState


def render_partial_assessment_report(
    state: ReconstructedRunState,
    reason: str,
    comparison_preserved: bool,
) -> str:
    """Render exact observed gates and label every absent phase as not reached."""
    lines = [
        "# PARTIAL Repository State Assessment",
        "",
        "Status: PARTIAL",
        "",
        f"Reason: {reason}",
        "",
        "| Phase | Gate |",
        "|---|---|",
    ]
    for phase in AssessmentPhase:
        gate = state.gate_for(phase)
        lines.append(f"| {phase.value} | {gate.value if gate else 'not reached'} |")
    lines.extend(
        (
            "",
            "Final source comparison: "
            + ("preservation confirmed" if comparison_preserved else "UNCONFIRMED"),
            "",
            "Unreached and interrupted checks are unverified; they are not passes or failures.",
        )
    )
    return "\n".join(lines) + "\n"
