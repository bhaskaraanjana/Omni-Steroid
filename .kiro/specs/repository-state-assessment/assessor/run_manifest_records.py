"""Define immutable events and reconstructed state for the append-only run manifest.

These records are the recovery model beneath pipeline orchestration. Superseded history
remains queryable while effective state never treats absent gates or checks as success.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .assessment_phase_gates import AssessmentPhase, GateStatus
from .model_types import OwnedProcess, ZonedTimestamp
from .run_models import PhaseState


class ManifestCorruption(RuntimeError):
    """Raised when durable state is missing, malformed, or internally inconsistent."""


class ManifestEvent(StrEnum):
    """Append-only event kinds understood by resume reconstruction."""

    RUN_STARTED = "run_started"
    PHASE_STARTED = "phase_started"
    PHASE_FINISHED = "phase_finished"
    CHECK = "check"
    OWNED_PROCESS = "owned_process"
    EVIDENCE = "evidence"
    FINAL_COMPARISON = "final_comparison"
    PARTIAL_REPORT = "partial_report"


class CheckState(StrEnum):
    """Manifest check state; interruption can only resolve to unverified."""

    RUNNING = "running"
    VERIFIED = "verified"
    UNVERIFIED = "unverified"


@dataclass(frozen=True, slots=True)
class RunIdentity:
    """Stable run roots and ownership token recorded in the first event."""

    run_id: str
    source_repository_root: str
    temporary_run_root: str
    permanent_output_root: str
    ownership_token: str

    def __post_init__(self) -> None:
        """Require every recovery-critical identity field."""
        if not all(
            (
                self.run_id,
                self.source_repository_root,
                self.temporary_run_root,
                self.permanent_output_root,
                self.ownership_token,
            )
        ):
            raise ValueError("run identity fields must all be present")


@dataclass(frozen=True, slots=True)
class ManifestRecord:
    """One immutable event in the durable run history."""

    sequence: int
    record_id: str
    run_id: str
    event: ManifestEvent
    recorded_at: ZonedTimestamp
    phase: AssessmentPhase | None = None
    phase_state: PhaseState | None = None
    gate: GateStatus | None = None
    check_id: str | None = None
    check_state: CheckState | None = None
    artifact_refs: tuple[str, ...] = ()
    reason: str | None = None
    supersedes: str | None = None
    process: OwnedProcess | None = None
    identity: RunIdentity | None = None
    comparison_preserved: bool | None = None
    execution_admitted: bool | None = None


@dataclass(frozen=True, slots=True)
class ReconstructedRunState:
    """Effective state rebuilt solely from the complete immutable event history."""

    identity: RunIdentity
    records: tuple[ManifestRecord, ...]
    effective_records: tuple[ManifestRecord, ...]

    def record(self, record_id: str) -> ManifestRecord:
        """Return one historical record, including a superseded original."""
        for record in self.records:
            if record.record_id == record_id:
                return record
        raise KeyError(record_id)

    def gate_record(self, phase: AssessmentPhase) -> ManifestRecord | None:
        """Return the effective terminal gate record for a phase, if observed."""
        matches = tuple(
            record
            for record in self.effective_records
            if record.event is ManifestEvent.PHASE_FINISHED and record.phase is phase
        )
        return matches[-1] if matches else None

    def gate_for(self, phase: AssessmentPhase) -> GateStatus | None:
        """Return an explicit gate only; absent phases remain absent."""
        record = self.gate_record(phase)
        return record.gate if record is not None else None

    def check_record(self, check_id: str) -> ManifestRecord | None:
        """Return the effective latest event for one check."""
        matches = tuple(
            record
            for record in self.effective_records
            if record.event is ManifestEvent.CHECK and record.check_id == check_id
        )
        return matches[-1] if matches else None

    def check_state(self, check_id: str) -> CheckState | None:
        """Return the effective check state without interpreting absence as verified."""
        record = self.check_record(check_id)
        return record.check_state if record is not None else None

    @property
    def running_checks(self) -> tuple[ManifestRecord, ...]:
        """Return checks requiring interruption recovery."""
        ids = tuple(
            dict.fromkeys(
                record.check_id
                for record in self.effective_records
                if record.check_id is not None
            )
        )
        return tuple(
            record
            for check_id in ids
            if (record := self.check_record(check_id)) is not None
            and record.check_state is CheckState.RUNNING
        )

    @property
    def owned_processes(self) -> tuple[OwnedProcess, ...]:
        """Return only identities explicitly recorded under this run's token."""
        return tuple(
            dict.fromkeys(
                record.process
                for record in self.effective_records
                if record.event is ManifestEvent.OWNED_PROCESS
                and record.process is not None
            )
        )

    @property
    def final_comparison_records(self) -> tuple[ManifestRecord, ...]:
        """Return every mandatory final-comparison event across resumes."""
        return tuple(
            record
            for record in self.records
            if record.event is ManifestEvent.FINAL_COMPARISON
        )
