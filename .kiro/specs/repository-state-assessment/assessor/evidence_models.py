"""Normalized evidence records produced for executed, blocked, or omitted checks.

Every record is referentially complete and keeps raw artifacts separate from report output.
"""

from __future__ import annotations

from dataclasses import dataclass

from .baseline_models import HardwareInventory, OperatingSystemInventory, ToolVersion
from .execution_models import Prerequisite, Termination
from .model_types import (
    AssessmentStatus,
    ExactArgumentVector,
    Measurement,
    ProcessOwnership,
    SourceLocation,
    VerificationPlane,
    ZonedTimestamp,
    require_primary_status,
)


@dataclass(frozen=True, slots=True)
class AssessmentEnvironment:
    """Non-secret environment facts attached to an evidence record."""

    operating_system: OperatingSystemInventory
    hardware: tuple[HardwareInventory, ...]
    tool_versions: tuple[ToolVersion, ...]
    safe_variable_names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TestCounts:
    """Disjoint test outcomes that must never be conflated."""

    passed: int = 0
    failed: int = 0
    skipped: int = 0
    deselected: int = 0
    ignored: int = 0

    def __post_init__(self) -> None:
        """Reject negative outcome counts."""
        if min(self.passed, self.failed, self.skipped, self.deselected, self.ignored) < 0:
            raise ValueError("test counts must be non-negative")


@dataclass(frozen=True, slots=True)
class EvidenceArtifact:
    """An artifact path or an explicit marker that no artifact was generated."""

    kind: str
    path: str | None = None
    absent: bool = False

    def __post_init__(self) -> None:
        """Require exactly one of a path or an absent marker."""
        if (self.path is None) == (not self.absent):
            raise ValueError("artifact must provide either path or absent=true")


@dataclass(frozen=True, slots=True)
class RerunInstruction:
    """Complete prerequisites and observable result for reproducing a check."""

    prerequisites: tuple[str, ...]
    exact_argv: ExactArgumentVector | None
    numbered_procedure: tuple[str, ...] | None
    expected_observable: str

    def __post_init__(self) -> None:
        """Require exactly one rerun command or numbered procedure."""
        if (self.exact_argv is None) == (self.numbered_procedure is None):
            raise ValueError("rerun must define exactly one command or numbered procedure")

    def render_windows(self) -> str:
        """Render an exact Windows command, preserving quoted paths and cmd payloads."""
        if self.exact_argv is None:
            raise ValueError("numbered procedures do not have a Windows command line")
        return self.exact_argv.render_windows()


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    """Complete normalized evidence for one executed, blocked, or omitted check."""

    evidence_id: str
    check_id: str
    plane: VerificationPlane
    scope: str
    exact_argv: ExactArgumentVector | None
    numbered_procedure: tuple[str, ...] | None
    source_command_locations: tuple[SourceLocation, ...]
    cwd: str
    started_at: ZonedTimestamp
    duration_ms: int
    termination: Termination
    prerequisites: tuple[Prerequisite, ...]
    environment: AssessmentEnvironment
    source_revision: str
    stdout_ref: str | None
    stderr_ref: str | None
    relevant_output: tuple[str, ...]
    warnings: tuple[str, ...]
    test_counts: TestCounts
    measurements: tuple[Measurement, ...]
    artifacts: tuple[EvidenceArtifact, ...]
    network_observation_ref: str | None
    process_ownership: ProcessOwnership
    write_audit_ref: str | None
    primary_status: AssessmentStatus
    status_basis: str
    rerun: RerunInstruction

    def __post_init__(self) -> None:
        """Enforce one primary status, one procedure form, and valid duration."""
        require_primary_status(self.primary_status)
        if self.duration_ms < 0:
            raise ValueError("evidence duration_ms must be non-negative")
        if (self.exact_argv is None) == (self.numbered_procedure is None):
            raise ValueError("evidence must define exactly one command or numbered procedure")
