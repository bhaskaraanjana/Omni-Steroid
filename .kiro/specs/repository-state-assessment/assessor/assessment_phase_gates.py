"""Define the ordered assessment phases and their fail-closed gate outcomes.

This is the pipeline's policy layer: later phases are admissible only when every
predecessor has an explicit green record. Missing and inconclusive never imply pass.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class AssessmentPhase(StrEnum):
    """The ordered phases exposed by the assessment CLI."""

    BASELINE = "baseline"
    CLAIMS = "claims"
    DISCOVERY_ADMISSION = "discovery/admission"
    MIRROR_EXECUTION = "mirror execution"
    LOCAL_E2E = "local e2e"
    NATIVE_INTEGRATION = "native integration"
    NORMALIZATION = "normalization"
    PARITY = "parity"
    REPORT = "report"


@dataclass(frozen=True, slots=True)
class ExecutionAdmission:
    """Five safety proofs required before any mirror process may execute."""

    mirror_verified: bool
    write_containment_established: bool
    redaction_established: bool
    source_comparison_available: bool
    loopback_enforcement_established: bool

    @property
    def admitted(self) -> bool:
        """Fail closed unless every execution safety control is established."""
        return all(
            (
                self.mirror_verified,
                self.write_containment_established,
                self.redaction_established,
                self.source_comparison_available,
                self.loopback_enforcement_established,
            )
        )


class GateStatus(StrEnum):
    """An explicit gate decision; only green authorizes the next phase."""

    GREEN = "green"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"


@dataclass(frozen=True, slots=True)
class CheckCompletion:
    """One planned check's terminal verification disposition."""

    check_id: str
    verified: bool
    evidence_ref: str | None = None

    def __post_init__(self) -> None:
        """Reject reassuring completion without an evidence reference."""
        if not self.check_id.strip():
            raise ValueError("check_id must be present")
        if self.verified and not self.evidence_ref:
            raise ValueError("a verified check requires evidence")


@dataclass(frozen=True, slots=True)
class PhaseExecutionResult:
    """Artifacts, checks, and hard-gate outcome returned by one existing stage."""

    gate: GateStatus
    artifact_refs: tuple[str, ...]
    reason: str | None
    checks: tuple[CheckCompletion, ...] = ()
    execution_admission: ExecutionAdmission | None = None

    def __post_init__(self) -> None:
        """Require positive proof for green and an explanation otherwise."""
        if self.gate is GateStatus.GREEN and not self.artifact_refs:
            # Gate control: an absent artifact cannot become a confident pass.
            raise ValueError("a green phase gate requires at least one artifact")
        if self.gate is not GateStatus.GREEN and not self.reason:
            # Gate control: every stop must remain visible in the partial report.
            raise ValueError("a non-green phase gate requires a reason")
        check_ids = tuple(check.check_id for check in self.checks)
        if len(check_ids) != len(set(check_ids)):
            raise ValueError("phase check completions must be unique")


def predecessor_phases(phase: AssessmentPhase) -> tuple[AssessmentPhase, ...]:
    """Return every phase that must already have an explicit green gate."""
    phases = tuple(AssessmentPhase)
    return phases[: phases.index(phase)]


def parse_phase(value: str) -> AssessmentPhase:
    """Parse CLI spelling variants without accepting an unknown phase."""
    normalized = value.strip().casefold().replace("_", " ").replace("-", " ")
    aliases = {
        "baseline": AssessmentPhase.BASELINE,
        "claims": AssessmentPhase.CLAIMS,
        "discovery/admission": AssessmentPhase.DISCOVERY_ADMISSION,
        "discovery admission": AssessmentPhase.DISCOVERY_ADMISSION,
        "mirror execution": AssessmentPhase.MIRROR_EXECUTION,
        "local e2e": AssessmentPhase.LOCAL_E2E,
        "native integration": AssessmentPhase.NATIVE_INTEGRATION,
        "normalization": AssessmentPhase.NORMALIZATION,
        "parity": AssessmentPhase.PARITY,
        "report": AssessmentPhase.REPORT,
    }
    try:
        return aliases[normalized]
    except KeyError as error:
        raise ValueError(f"unknown assessment phase: {value}") from error
