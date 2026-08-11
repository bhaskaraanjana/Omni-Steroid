"""Discover and terminate only PID-reuse-safe assessment-owned process trees.

Ownership begins at the newly launched root PID and expands only through observed
parent/descendant relationships. Cleanup rechecks PID creation time and executable
before signalling, preserving every pre-existing or PID-reused process.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

try:
    import psutil
except ImportError:  # Missing local prerequisite is reported before process launch.
    psutil = None  # type: ignore[assignment]

from .model_types import OwnedProcess, ProcessOwnership, ZonedTimestamp
from .process_cleanup import CleanupMode, ProcessSnapshot, select_cleanup_processes


class ProcessInspectionUnavailable(RuntimeError):
    """Raised when PID creation-time-safe process inspection is unavailable."""


def require_process_inspection() -> None:
    """Fail before launch when the locked process-inspection dependency is absent."""
    if psutil is None:
        raise ProcessInspectionUnavailable("psutil process inspection is unavailable")


def _identity(process: Any, parent_pid: int | None = None) -> OwnedProcess:
    created_at = ZonedTimestamp(
        datetime.fromtimestamp(process.create_time(), tz=UTC)
    )
    try:
        executable = process.exe()
    except (psutil.AccessDenied, psutil.ZombieProcess):
        executable = process.name()
    return OwnedProcess(
        pid=process.pid,
        created_at=created_at,
        executable=executable,
        parent_pid=process.ppid() if parent_pid is None else parent_pid,
    )


def capture_process_tree(root_pid: int, known: dict[int, OwnedProcess]) -> None:
    """Add the root and every currently observable descendant to ``known``."""
    require_process_inspection()
    try:
        root = psutil.Process(root_pid)
        processes = (root, *root.children(recursive=True))
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return
    for process in processes:
        if process.pid in known:
            continue
        try:
            known[process.pid] = _identity(process)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue


def _matching_live_process(identity: OwnedProcess) -> Any | None:
    try:
        process = psutil.Process(identity.pid)
        creation_matches = abs(
            process.create_time() - identity.created_at.value.timestamp()
        ) < 0.001
        try:
            executable = process.exe()
        except (psutil.AccessDenied, psutil.ZombieProcess):
            executable = process.name()
        executable_matches = os.path.normcase(executable) == os.path.normcase(
            identity.executable
        )
        return process if creation_matches and executable_matches else None
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return None


def cleanup_owned_processes(
    ownership_token: str,
    identities: tuple[OwnedProcess, ...],
    mode: CleanupMode,
    grace_seconds: float = 1.0,
) -> ProcessOwnership:
    """Terminate matching owned identities and report whether cleanup completed."""
    require_process_inspection()
    ownership = ProcessOwnership(
        ownership_token=ownership_token,
        mechanism="pid-parent-creation-time-and-executable",
        processes=identities,
    )
    live_by_snapshot: dict[ProcessSnapshot, Any] = {}
    for identity in identities:
        process = _matching_live_process(identity)
        if process is not None:
            snapshot = ProcessSnapshot(identity, ownership_token)
            live_by_snapshot[snapshot] = process
    selection = select_cleanup_processes(
        ownership, tuple(live_by_snapshot), mode
    )
    targets = [live_by_snapshot[snapshot] for snapshot in selection.terminate]
    for process in reversed(targets):
        try:
            process.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    _, alive = psutil.wait_procs(targets, timeout=grace_seconds)
    for process in alive:
        identity = next(item for item in identities if item.pid == process.pid)
        if _matching_live_process(identity) is None:
            continue
        try:
            process.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    psutil.wait_procs(alive, timeout=grace_seconds)
    cleanup_completed = not any(
        _matching_live_process(identity) is not None for identity in identities
    )
    return ProcessOwnership(
        ownership_token=ownership_token,
        mechanism=ownership.mechanism,
        processes=identities,
        cleanup_completed=cleanup_completed,
    )
