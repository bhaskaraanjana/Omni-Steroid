"""Typed contracts for one owned Local E2E scenario attempt.

These are the data shapes and the controller protocol the Local E2E orchestrator
plans against: the exact commands to start, the quarantined output references, and
the scenario outcome carried onward as evidence. They sit between preflight
admission and process orchestration, and hold no execution behaviour themselves.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .e2e_process_controller import (
    E2EProcessCompletion,
    E2EProcessHandle,
    E2EProcessRole,
)
from .evidence_models import EvidenceArtifact
from .execution_models import TerminationKind
from .model_types import ExactArgumentVector, ProcessOwnership
from .playwright_preflight_admission import PlaywrightAdmissionResult
from .process_cleanup import CleanupMode


@dataclass(frozen=True, slots=True)
class E2ECommand:
    """One exact command whose working directory must be inside the mirror."""

    exact_argv: ExactArgumentVector
    cwd: str


@dataclass(frozen=True, slots=True)
class E2EOrchestrationPlan:
    """All admitted commands and paths required for one local scenario attempt."""

    admission: PlaywrightAdmissionResult
    scenario_id: str
    scenario_name: str
    temporary_root: Path
    mirror_root: Path
    frontend: E2ECommand
    engine: E2ECommand
    browser: E2ECommand
    configured_browser_executable_path: str
    timeout_ms: int

    def __post_init__(self) -> None:
        if self.timeout_ms <= 0:
            raise ValueError("E2E timeout must be positive")


@dataclass(frozen=True, slots=True)
class E2EOutputReferences:
    """Quarantined output references for every Local E2E participant."""

    scenario_output_ref: str
    frontend_output_ref: str
    engine_output_ref: str
    browser_output_ref: str


@dataclass(frozen=True, slots=True)
class E2EOrchestrationResult:
    """One scenario outcome with diagnostics, artifacts, and cleanup evidence."""

    scenario_id: str
    scenario_name: str
    termination: TerminationKind
    exit_code: int | None
    outputs: E2EOutputReferences
    failure_output: tuple[str, ...]
    artifacts: tuple[EvidenceArtifact, ...]
    process_ownership: ProcessOwnership

    @property
    def failed(self) -> bool:
        """Return whether the browser attempt did not exit successfully."""
        return self.termination is not TerminationKind.EXITED or self.exit_code != 0


class OwnedE2EController(Protocol):
    """Minimal ownership-safe process lifecycle used by the orchestrator."""

    def start(
        self,
        role: E2EProcessRole,
        command: E2ECommand,
        environment: Mapping[str, str],
        stdout_path: Path,
        stderr_path: Path,
        ownership_token: str,
    ) -> E2EProcessHandle:
        """Start one exact assessment-owned process."""

    def wait(
        self, handle: E2EProcessHandle, timeout_ms: int
    ) -> E2EProcessCompletion:
        """Wait for the terminating browser scenario process."""

    def cleanup(
        self,
        handles: tuple[E2EProcessHandle, ...],
        ownership_token: str,
        mode: CleanupMode,
    ) -> ProcessOwnership:
        """Clean only processes represented by assessment-owned handles."""
