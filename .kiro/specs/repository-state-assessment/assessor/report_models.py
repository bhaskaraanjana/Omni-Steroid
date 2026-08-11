"""Parity-matrix and ranked-finding records used by final report synthesis.

Rows expose every required column and carry one immutable primary assessment status.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from .model_types import (
    AssessmentStatus,
    Measurement,
    SourceLocation,
    VerificationPlane,
    require_primary_status,
)


class BenchmarkSet(StrEnum):
    """Canonical competitor capability set represented by a parity row."""

    GRANOLA = "Granola_Capability_Set"
    WISPR_FLOW = "Wispr_Flow_Capability_Set"


class FindingCategory(StrEnum):
    """Actionable finding category used by the ranked report list."""

    CONFIRMED_DEFECT = "confirmed_defect"
    VERIFICATION_GAP = "verification_gap"
    CAPABILITY_GAP = "capability_gap"
    DOCUMENTATION_DRIFT = "documentation_drift"
    RELEASE_RISK = "release_risk"


class NextActionDisposition(StrEnum):
    """The one next-action disposition assigned to a finding."""

    FIX = "fix"
    VALIDATE = "validate"
    DEFER = "defer"




@dataclass(frozen=True, slots=True)
class DenseRetrievalReportEntry:
    """Report dense retrieval availability without inferring a measurement."""

    dense_available: bool
    status: AssessmentStatus
    evidence_ref: str
    note: str

    def __post_init__(self) -> None:
        """Require an auditable status and explanation for either availability state."""
        if type(self.dense_available) is not bool:
            raise TypeError("dense_available must be a bool")
        require_primary_status(self.status)
        if not self.evidence_ref or not self.note.strip():
            raise ValueError("dense retrieval requires evidence and a note")


@dataclass(frozen=True, slots=True)
class EfficacySection:
    """User-facing efficacy measurements kept separate from test and coverage data."""

    rows: tuple[Measurement, ...]
    note: str

    def __post_init__(self) -> None:
        """Reject untyped rows and unexplained absence of efficacy measurements."""
        if any(not isinstance(row, Measurement) for row in self.rows):
            raise TypeError("efficacy rows must be Measurement values")
        if not self.note.strip():
            raise ValueError("efficacy section requires an explanatory note")


@dataclass(frozen=True, slots=True)
class VerificationFinding:
    """One verification check assigned to exactly one report plane."""

    check_id: str
    plane: VerificationPlane
    scope: str
    status: AssessmentStatus
    conclusion: str
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        """Keep every check typed, scoped, concluded, and evidence-backed."""
        if not isinstance(self.plane, VerificationPlane):
            raise TypeError("plane must be a VerificationPlane")
        require_primary_status(self.status)
        if not all((self.check_id.strip(), self.scope.strip(), self.conclusion.strip())):
            raise ValueError("verification finding identity, scope, and conclusion are required")
        if not self.evidence_refs or any(not ref for ref in self.evidence_refs):
            raise ValueError("verification finding requires non-empty evidence references")
@dataclass(frozen=True, slots=True)
class ParityMeasurement:
    """A quality dimension classified independently from feature presence."""

    dimension: str
    measurement: Measurement | None
    primary_status: AssessmentStatus
    evidence_ref: str | None

    def __post_init__(self) -> None:
        """Represent absent measurements explicitly without inferring presence."""
        require_primary_status(self.primary_status)
        if not self.dimension:
            raise ValueError("measurement dimension must not be empty")
        if self.measurement is None:
            if self.primary_status is not AssessmentStatus.UNVERIFIED:
                raise ValueError("an unmeasured dimension must be Unverified")
            if self.evidence_ref is not None:
                raise ValueError("an unmeasured dimension cannot cite measurement evidence")
            return
        if self.measurement.name != self.dimension:
            raise ValueError("measurement name must match its quality dimension")
        if not self.evidence_ref:
            raise ValueError("a measured dimension requires a Fresh_Evidence reference")


@dataclass(frozen=True, slots=True)
class ParityRow:
    """One complete benchmark/Omni capability comparison row."""

    row_id: str
    benchmark_set: BenchmarkSet
    benchmark_capability: str
    benchmark_source: SourceLocation | None
    benchmark_source_date: date | None
    benchmark_basis_status: AssessmentStatus
    omni_documentary_claim_refs: tuple[str, ...]
    implementation_locations: tuple[SourceLocation, ...]
    fresh_evidence_refs: tuple[str, ...]
    primary_status: AssessmentStatus
    limitation: str
    parity_conclusion: str
    measurements: tuple[ParityMeasurement, ...]

    def __post_init__(self) -> None:
        """Enforce separate, singular basis and Omni presence classifications."""
        require_primary_status(self.benchmark_basis_status)
        require_primary_status(self.primary_status)


@dataclass(frozen=True, slots=True)
class RankedFinding:
    """A uniquely ranked actionable defect, gap, drift item, or release risk."""

    rank: int
    finding_id: str
    category: FindingCategory
    impact: str
    primary_status: AssessmentStatus
    evidence_refs: tuple[str, ...]
    dependency_ids: tuple[str, ...]
    disposition: NextActionDisposition
    completion_evidence_required: str

    def __post_init__(self) -> None:
        """Require a positive rank and one valid primary status."""
        if self.rank <= 0:
            raise ValueError("finding rank must be positive")
        require_primary_status(self.primary_status)
