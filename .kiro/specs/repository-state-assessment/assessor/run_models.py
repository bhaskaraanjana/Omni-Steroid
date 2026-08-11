"""Resumable run-manifest and final workspace-comparison records.

These records support owned-process recovery and prove source preservation on termination.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .model_types import ProcessOwnership, ZonedTimestamp


class RunPhase(StrEnum):
    """A phase in the assessment's gated execution flow."""

    BASELINE = "baseline"
    CLAIMS = "claims"
    DISCOVERY_ADMISSION = "discovery_admission"
    MIRROR_EXECUTION = "mirror_execution"
    NORMALIZATION = "normalization"
    PARITY = "parity"
    REPORT = "report"
    FINAL_COMPARISON = "final_comparison"


class PhaseState(StrEnum):
    """Durable state of an assessment run phase."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    INTERRUPTED = "interrupted"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class RunPhaseRecord:
    """Timing, state, and immutable artifact references for one phase."""

    phase: RunPhase
    state: PhaseState
    started_at: ZonedTimestamp | None = None
    finished_at: ZonedTimestamp | None = None
    artifact_refs: tuple[str, ...] = ()
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class RunManifest:
    """Durable run identity, phase state, ownership, and immutable record references."""

    run_id: str
    source_repository_root: str
    temporary_run_root: str
    permanent_output_root: str
    started_at: ZonedTimestamp
    updated_at: ZonedTimestamp
    phases: tuple[RunPhaseRecord, ...]
    process_ownership: ProcessOwnership
    evidence_refs: tuple[str, ...]
    superseding_record_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FileDifference:
    """A detected path, metadata, or byte-hash difference at final comparison."""

    path: str
    difference_kind: str
    baseline_value: str | None
    final_value: str | None


@dataclass(frozen=True, slots=True)
class WorkspaceComparison:
    """Final preservation comparison for pre-existing paths, bytes, and writes."""

    baseline_manifest_ref: str
    final_manifest_ref: str
    tracked_paths_identical: bool
    untracked_paths_identical: bool
    production_bytes_identical: bool
    differences: tuple[FileDifference, ...]
    writes_outside_designated_roots: tuple[str, ...]
    compared_at: ZonedTimestamp | None = None

    @property
    def preservation_confirmed(self) -> bool:
        """Return true only when every preservation dimension is unchanged."""
        return (
            self.tracked_paths_identical
            and self.untracked_paths_identical
            and self.production_bytes_identical
            and not self.differences
            and not self.writes_outside_designated_roots
        )
