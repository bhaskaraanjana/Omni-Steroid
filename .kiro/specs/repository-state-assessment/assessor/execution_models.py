"""Verification plans and raw execution records for contained assessment commands.

Commands use immutable argument arrays; execution records retain owned-process identity.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .model_types import (
    ExactArgumentVector,
    NetworkPolicy,
    ProcessOwnership,
    SourceLocation,
    VerificationPlane,
    WritePolicy,
    ZonedTimestamp,
)


class Applicability(StrEnum):
    """Whether a planned check applies to the assessed host/configuration."""

    APPLICABLE = "applicable"
    NOT_APPLICABLE = "not_applicable"


class TerminationKind(StrEnum):
    """How an attempted command or procedure ended."""

    EXITED = "exited"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    PRECHECK_BLOCKED = "precheck_blocked"
    OMITTED = "omitted"
    CRASHED = "crashed"


@dataclass(frozen=True, slots=True)
class Prerequisite:
    """A named prerequisite and the procedure used to detect it."""

    name: str
    detection_procedure: tuple[str, ...]
    available: bool | None = None
    evidence_ref: str | None = None


@dataclass(frozen=True, slots=True)
class CommandSource:
    """Repository location and content hash that defined a command."""

    location: SourceLocation
    sha256: str


@dataclass(frozen=True, slots=True)
class CheckPlan:
    """A fully bounded command or numbered procedure awaiting admission."""

    check_id: str
    plane: VerificationPlane
    scope: str
    command_source: CommandSource | None
    exact_argv: ExactArgumentVector | None
    numbered_procedure: tuple[str, ...] | None
    cwd: str
    prerequisites: tuple[Prerequisite, ...]
    applicability: Applicability
    applicability_basis: str
    timeout_ms: int
    write_policy: WritePolicy
    network_policy: NetworkPolicy
    external_dependency: bool
    dependent_check_ids: tuple[str, ...]
    cleanup_procedure: tuple[str, ...]

    def __post_init__(self) -> None:
        """Require one executable form and a positive timeout."""
        if (self.exact_argv is None) == (self.numbered_procedure is None):
            raise ValueError("plan must define exactly one command or numbered procedure")
        if self.timeout_ms <= 0:
            raise ValueError("plan timeout_ms must be positive")


@dataclass(frozen=True, slots=True)
class Termination:
    """Exact process termination result, including preflight blocking."""

    kind: TerminationKind
    exit_code: int | None = None
    signal: int | None = None
    timeout_ms: int | None = None


@dataclass(frozen=True, slots=True)
class RawExecutionResult:
    """Unnormalized output and containment references from one fresh attempt."""

    check_id: str
    exact_argv: ExactArgumentVector | None
    numbered_procedure: tuple[str, ...] | None
    cwd: str
    started_at: ZonedTimestamp
    duration_ms: int
    termination: Termination
    stdout_ref: str | None
    stderr_ref: str | None
    process_ownership: ProcessOwnership
    write_audit_ref: str | None
    network_observation_ref: str | None

    def __post_init__(self) -> None:
        """Reject negative durations and ambiguous executable forms."""
        if self.duration_ms < 0:
            raise ValueError("execution duration_ms must be non-negative")
        if (self.exact_argv is None) == (self.numbered_procedure is None):
            raise ValueError("execution must retain exactly one command or numbered procedure")
