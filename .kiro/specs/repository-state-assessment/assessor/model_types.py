"""Shared immutable value objects for auditable repository assessment records.

These types preserve exact command, time, measurement, status, and containment data.
Security invariant: policies are fail-closed and cannot authorize source mutation or egress.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


class AssessmentStatus(StrEnum):
    """The single primary classification allowed for an assessed scope."""

    VERIFIED_WORKING = "Verified_Working"
    VERIFIED_PARTIAL = "Verified_Partial"
    FRESH_FAILURE = "Fresh_Failure"
    INTEGRATION_FAILED = "Integration_Failed"
    NOT_IMPLEMENTED = "Not_Implemented"
    ENVIRONMENT_BLOCKED = "Environment_Blocked"
    HISTORICAL_ONLY = "Historical_Only"
    UNVERIFIED = "Unverified"
    NOT_APPLICABLE = "Not_Applicable"


class VerificationPlane(StrEnum):
    """A separately reported verification area."""

    PYTHON_ENGINE = "Python_Engine"
    TYPESCRIPT_UI = "TypeScript_UI"
    RUST_TAURI_SHELL = "Rust_Tauri_Shell"
    PRODUCT_BUILD = "Product_Build"
    LOCAL_E2E = "Local_E2E"
    HARDWARE_INTEGRATION = "Hardware_Integration"
    SECURITY_PRIVACY = "Security_Privacy"
    PACKAGING_RELEASE = "Packaging_Release"


class NetworkMode(StrEnum):
    """Permitted network behavior for an assessment operation."""

    NONE = "none"
    LOOPBACK_ONLY = "loopback_only"


class MeasurementUnit(StrEnum):
    """Supported units for numeric assessment measurements."""

    PERCENT = "percent"
    MILLISECONDS = "milliseconds"
    SECONDS = "seconds"
    BYTES = "bytes"
    COUNT = "count"
    RATIO = "ratio"
    WORDS_PER_MINUTE = "words_per_minute"


@dataclass(frozen=True, slots=True)
class ZonedTimestamp:
    """A timestamp whose UTC offset is present and serializable."""

    value: datetime

    def __post_init__(self) -> None:
        """Reject naive datetimes because evidence must be reproducible."""
        if self.value.tzinfo is None or self.value.utcoffset() is None:
            raise ValueError("timestamp must include a time-zone offset")


@dataclass(frozen=True, slots=True)
class ExactArgumentVector:
    """An immutable, lossless process argument array including the executable."""

    values: tuple[str, ...]

    def __post_init__(self) -> None:
        """Require an executable and preserve every argument as a string."""
        if not self.values:
            raise ValueError("exact argument vector must include an executable")
        if any(not isinstance(value, str) for value in self.values):
            raise TypeError("every exact argument must be a string")

    def render_windows(self) -> str:
        """Render argv using the Windows command-line quoting algorithm."""
        return subprocess.list2cmdline(self.values)


@dataclass(frozen=True, slots=True)
class Measurement:
    """An exact numeric result with an explicit unit and assessed scope."""

    name: str
    value: Decimal
    unit: MeasurementUnit
    assessed_scope: str

    def __post_init__(self) -> None:
        """Reject non-finite values while retaining valid numeric zero."""
        if not isinstance(self.value, Decimal):
            raise TypeError("measurement value must be Decimal")
        if not self.value.is_finite():
            raise ValueError("measurement value must be finite")


@dataclass(frozen=True, slots=True)
class SourceLocation:
    """A precise repository source range supporting a conclusion."""

    path: str
    start_line: int
    end_line: int

    def __post_init__(self) -> None:
        """Require a positive, ordered inclusive line range."""
        if self.start_line <= 0 or self.end_line < self.start_line:
            raise ValueError("source lines must be positive and ordered")


@dataclass(frozen=True, slots=True)
class OwnedProcess:
    """PID-reuse-safe identity for one assessment-created process."""

    pid: int
    created_at: ZonedTimestamp
    executable: str
    parent_pid: int | None = None

    def __post_init__(self) -> None:
        """Reject invalid process identifiers."""
        if self.pid <= 0 or (self.parent_pid is not None and self.parent_pid <= 0):
            raise ValueError("process identifiers must be positive")


@dataclass(frozen=True, slots=True)
class ProcessOwnership:
    """Ownership token and exact process set eligible for cleanup."""

    ownership_token: str
    mechanism: str
    processes: tuple[OwnedProcess, ...] = ()
    cleanup_completed: bool = False


@dataclass(frozen=True, slots=True)
class NetworkPolicy:
    """A deny-by-default network policy that never permits non-loopback egress."""

    mode: NetworkMode
    observed_or_permitted_loopback_endpoints: tuple[str, ...] = ()
    permits_non_loopback: bool = field(default=False, init=False)


@dataclass(frozen=True, slots=True)
class WritePolicy:
    """A fail-closed policy limiting writes to new assessment-owned roots."""

    designated_roots: tuple[str, ...]
    audit_required: bool = True
    permits_preexisting_mutation: bool = field(default=False, init=False)
    fail_closed: bool = field(default=True, init=False)

    def __post_init__(self) -> None:
        """Require at least one explicit assessment-owned write root."""
        if not self.designated_roots:
            raise ValueError("write policy requires a designated root")


def require_primary_status(status: AssessmentStatus) -> None:
    """Reject values that could bypass the one-status enum contract."""
    if not isinstance(status, AssessmentStatus):
        raise TypeError("primary_status must be one AssessmentStatus value")
