"""Pure PID-reuse-safe selection of assessment-owned cleanup targets."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .model_types import OwnedProcess, ProcessOwnership


class CleanupMode(StrEnum):
    """Terminal paths that must all perform ownership-safe cleanup."""

    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"
    ABORT = "abort"


@dataclass(frozen=True, slots=True)
class ProcessSnapshot:
    """One live process plus the ownership token observed for it."""

    identity: OwnedProcess
    ownership_token: str | None = None


@dataclass(frozen=True, slots=True)
class CleanupSelection:
    """A complete partition of live processes into terminate and preserve sets."""

    mode: CleanupMode
    terminate: tuple[ProcessSnapshot, ...]
    preserve: tuple[ProcessSnapshot, ...]


def select_cleanup_processes(
    ownership: ProcessOwnership,
    live_processes: tuple[ProcessSnapshot, ...],
    mode: CleanupMode,
) -> CleanupSelection:
    """Select only live processes matching token and PID-reuse-safe identity."""
    owned_identities = frozenset(ownership.processes)
    terminate = tuple(
        process
        for process in live_processes
        if process.ownership_token == ownership.ownership_token
        and process.identity in owned_identities
    )
    terminate_set = frozenset(terminate)
    preserve = tuple(
        process for process in live_processes if process not in terminate_set
    )
    return CleanupSelection(mode=mode, terminate=terminate, preserve=preserve)
