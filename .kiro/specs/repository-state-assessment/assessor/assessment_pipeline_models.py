"""Typed inputs and outputs for phase-gated assessment orchestration.

These models form the narrow adapter boundary between existing pipeline stages and the
orchestrator while preserving explicit cancellation and durable process ownership.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass

from .assessment_phase_gates import AssessmentPhase, PhaseExecutionResult
from .model_types import OwnedProcess, ProcessOwnership
from .process_cleanup import CleanupMode
from .run_manifest_append_store import AppendOnlyRunManifest

PhaseExecutor = Callable[["PhaseExecutionContext"], PhaseExecutionResult]
CleanupExecutor = Callable[[str, tuple[OwnedProcess, ...], CleanupMode], ProcessOwnership]


class PipelineCancellation:
    """Thread-safe explicit cancellation signal checked between and within phases."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        """Request bounded cancellation without signalling unrelated processes."""
        self._event.set()

    @property
    def requested(self) -> bool:
        """Return whether explicit cancellation has been requested."""
        return self._event.is_set()


@dataclass(frozen=True, slots=True)
class PipelineOptions:
    """Caller-selected phase bound and observation-only safety mode."""

    phase_limit: AssessmentPhase | None = None
    observation_only: bool = False

    @property
    def effective_limit(self) -> AssessmentPhase:
        """Stop observation-only runs before the process-execution phase."""
        requested = self.phase_limit or AssessmentPhase.REPORT
        observation_limit = AssessmentPhase.DISCOVERY_ADMISSION
        if self.observation_only and tuple(AssessmentPhase).index(requested) > tuple(
            AssessmentPhase
        ).index(observation_limit):
            return observation_limit
        return requested


@dataclass(frozen=True, slots=True)
class PhaseAction:
    """One existing stage adapter plus the checks it may interrupt."""

    phase: AssessmentPhase
    planned_check_ids: tuple[str, ...]
    execute: PhaseExecutor

    def __post_init__(self) -> None:
        """Reject duplicate check identities before any phase starts."""
        if len(self.planned_check_ids) != len(set(self.planned_check_ids)):
            raise ValueError("planned check identifiers must be unique")


@dataclass(frozen=True, slots=True)
class PhaseExecutionContext:
    """Restricted stage context for durable ownership and cancellation observation."""

    phase: AssessmentPhase
    cancellation: PipelineCancellation
    _store: AppendOnlyRunManifest

    @property
    def cancellation_requested(self) -> bool:
        """Let long-running adapters stop at their own bounded polling points."""
        return self.cancellation.requested

    def record_owned_process(self, process: OwnedProcess) -> None:
        """Persist process identity before a crash can require recovery cleanup."""
        # Ownership control 4.7/4.8: only this run's recorded identities are eligible.
        self._store.append_owned_process(self.phase, process)


@dataclass(frozen=True, slots=True)
class PipelineResult:
    """Terminal orchestration result, including honest partial-report disposition."""

    partial: bool
    termination_reason: str
    reached_phases: tuple[AssessmentPhase, ...]
    partial_report_ref: str | None
    comparison_preserved: bool
