"""Build the sanitized observation summary published after discovery/admission.

The summary is the run's own account of what it found and, more importantly, what it
refused to do: every omission, every unresolved tool, and the exact containment scope
that decides whether any repository process may execute at all.
"""

from __future__ import annotations

from dataclasses import asdict

from .assessment_phase_gates import ExecutionAdmission
from .discovery_models import RepositoryDiscoveryReport
from .observation_support import MIRROR_EXCLUDED_PREFIXES

CONTAINMENT_BLOCKER = (
    "no discovered command can attempt an empirical Python startup proof; "
    "all repository process execution remains omitted"
)
CONTAINMENT_STOP_REASON = (
    "no discovered command can attempt empirical Python startup proof; "
    "stopped before repository process execution"
)


def build_observation_summary(
    *,
    run_id: str,
    report: RepositoryDiscoveryReport,
    admission: ExecutionAdmission,
    files_hashed: int,
    claims_inventoried: int,
    omissions: tuple[dict[str, object], ...],
    proof_candidates: tuple[str, ...],
    blocked_prelaunch_count: int,
) -> dict[str, object]:
    """Return the complete sanitized summary for one discovery/admission phase."""
    resolutions = report.tool_resolutions
    containment_admitted = admission.loopback_enforcement_established
    return {
        "run_id": run_id,
        "counts": {
            "files_hashed": files_hashed,
            "claims_inventoried": claims_inventoried,
            "scenarios_found": len(report.scenarios),
            "checks_discovered": len(report.outcomes),
            "tools_resolved": sum(
                item.executable_path is not None and item.version is not None
                for item in resolutions
            ),
            "tools_unresolved": sum(
                item.executable_path is None or item.version is None
                for item in resolutions
            ),
            "omissions_recorded": len(omissions),
        },
        "admission": asdict(admission),
        "network_containment": {
            "adapter": "LoopbackOnlyNetworkContainment",
            "genuinely_guarded_check_ids": [],
            "proof_candidate_check_ids": list(proof_candidates),
            "scope": "Python interpreters that emit a valid per-lease startup proof",
            "blocked_prelaunch_count": blocked_prelaunch_count,
        },
        "blockers": [] if containment_admitted else [CONTAINMENT_BLOCKER],
        "mirror_exclusion_policy": [
            {
                "prefix": prefix,
                "reason": "dependency, cache, Git metadata, build, or "
                "prior assessment output excluded",
            }
            for prefix in MIRROR_EXCLUDED_PREFIXES
        ],
        "omissions": list(omissions),
    }
