"""Persist the resumable run manifest as immutable, append-only JSONL events.

The store is the pipeline's sole recovery authority. Corrections append a record that
names its predecessor; existing manifest bytes and raw-evidence references are never
rewritten or deleted.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from .assessment_phase_gates import AssessmentPhase, GateStatus
from .model_types import OwnedProcess, ZonedTimestamp
from .run_manifest_records import (
    CheckState,
    ManifestCorruption,
    ManifestEvent,
    ManifestRecord,
    ReconstructedRunState,
    RunIdentity,
)
from .run_models import PhaseState


class AppendOnlyRunManifest:
    """Append and reconstruct one fsync-backed run manifest without mutation APIs."""

    def __init__(self, path: Path, clock: Callable[[], ZonedTimestamp]) -> None:
        self.path = path
        self._clock = clock

    @classmethod
    def create(
        cls, path: Path, identity: RunIdentity, clock: Callable[[], ZonedTimestamp]
    ) -> AppendOnlyRunManifest:
        """Create a new manifest exclusively and append its stable run identity."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8", newline="\n"):
            pass
        store = cls(path, clock)
        store._append(ManifestEvent.RUN_STARTED, identity=identity)
        return store

    @classmethod
    def open(cls, path: Path, clock: Callable[[], ZonedTimestamp]) -> AppendOnlyRunManifest:
        """Open an existing valid manifest for resume without side effects."""
        store = cls(path, clock)
        store.state()
        return store

    def append_phase_started(self, phase: AssessmentPhase) -> ManifestRecord:
        """Record phase entry before invoking any stage code."""
        return self._append(
            ManifestEvent.PHASE_STARTED, phase=phase, phase_state=PhaseState.RUNNING
        )

    def append_phase_finished(
        self,
        phase: AssessmentPhase,
        state: PhaseState,
        gate: GateStatus,
        refs: tuple[str, ...],
        reason: str | None,
        supersedes: str | None = None,
        execution_admitted: bool | None = None,
    ) -> ManifestRecord:
        """Append a terminal gate, optionally superseding an earlier decision."""
        return self._append(
            ManifestEvent.PHASE_FINISHED,
            phase=phase,
            phase_state=state,
            gate=gate,
            artifact_refs=refs,
            reason=reason,
            supersedes=supersedes,
            execution_admitted=execution_admitted,
        )

    def append_check(
        self,
        phase: AssessmentPhase,
        check_id: str,
        state: CheckState,
        evidence_ref: str | None = None,
        supersedes: str | None = None,
    ) -> ManifestRecord:
        """Append a check transition; unverified is distinct from failure and pass."""
        refs = (evidence_ref,) if evidence_ref else ()
        return self._append(
            ManifestEvent.CHECK,
            phase=phase,
            check_id=check_id,
            check_state=state,
            artifact_refs=refs,
            supersedes=supersedes,
        )

    def append_owned_process(self, phase: AssessmentPhase, process: OwnedProcess) -> ManifestRecord:
        """Persist a PID-reuse-safe identity before recovery may need it."""
        return self._append(ManifestEvent.OWNED_PROCESS, phase=phase, process=process)

    def append_evidence(self, reference: str, supersedes: str | None) -> ManifestRecord:
        """Append a raw or normalized evidence reference without altering its predecessor."""
        return self._append(
            ManifestEvent.EVIDENCE, artifact_refs=(reference,), supersedes=supersedes
        )

    def append_final_comparison(
        self, preserved: bool, refs: tuple[str, ...], reason: str
    ) -> ManifestRecord:
        """Append the mandatory source-comparison outcome for this termination."""
        return self._append(
            ManifestEvent.FINAL_COMPARISON,
            artifact_refs=refs,
            reason=reason,
            comparison_preserved=preserved,
        )

    def append_partial_report(self, reference: str, reason: str) -> ManifestRecord:
        """Append a visibly partial report reference for an incomplete run."""
        return self._append(ManifestEvent.PARTIAL_REPORT, artifact_refs=(reference,), reason=reason)

    def state(self) -> ReconstructedRunState:
        """Reconstruct effective run state from manifest bytes alone."""
        records = self._read_records()
        if (
            not records
            or records[0].event is not ManifestEvent.RUN_STARTED
            or records[0].identity is None
        ):
            raise ManifestCorruption("manifest must begin with run_started identity")
        superseded = {record.supersedes for record in records if record.supersedes is not None}
        effective = tuple(record for record in records if record.record_id not in superseded)
        return ReconstructedRunState(records[0].identity, records, effective)

    def _append(
        self,
        event: ManifestEvent,
        *,
        phase: AssessmentPhase | None = None,
        phase_state: PhaseState | None = None,
        gate: GateStatus | None = None,
        check_id: str | None = None,
        check_state: CheckState | None = None,
        artifact_refs: tuple[str, ...] = (),
        reason: str | None = None,
        supersedes: str | None = None,
        process: OwnedProcess | None = None,
        identity: RunIdentity | None = None,
        comparison_preserved: bool | None = None,
        execution_admitted: bool | None = None,
    ) -> ManifestRecord:
        records = self._read_records()
        run_id = identity.run_id if identity is not None else (records[0].run_id if records else "")
        sequence = len(records)
        if supersedes is not None and supersedes not in {item.record_id for item in records}:
            raise ValueError("supersedes must reference an existing manifest record")
        record = ManifestRecord(
            sequence,
            f"{run_id}:{sequence:06d}",
            run_id,
            event,
            self._clock(),
            phase,
            phase_state,
            gate,
            check_id,
            check_state,
            artifact_refs,
            reason,
            supersedes,
            process,
            identity,
            comparison_preserved,
            execution_admitted,
        )
        from .run_manifest_record_codec import encode_manifest_record

        payload = encode_manifest_record(record)
        descriptor = os.open(self.path, os.O_APPEND | os.O_WRONLY)
        try:
            # Append-only control: one encoded event is one OS append operation.
            if os.write(descriptor, payload) != len(payload):
                raise OSError("short manifest append")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return record

    def _read_records(self) -> tuple[ManifestRecord, ...]:
        if not self.path.is_file():
            raise ManifestCorruption("manifest does not exist")
        data = self.path.read_bytes()
        if data and not data.endswith(b"\n"):
            raise ManifestCorruption("manifest ends with an incomplete record")
        from .run_manifest_record_codec import decode_manifest_record

        records = tuple(
            decode_manifest_record(line, index) for index, line in enumerate(data.splitlines())
        )
        for index, record in enumerate(records):
            if record.sequence != index or record.record_id != f"{record.run_id}:{index:06d}":
                raise ManifestCorruption("manifest sequence is not contiguous")
        return records
