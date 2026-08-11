"""Own the three-process Local E2E lifecycle without port-based cleanup.

The controller starts only explicit argv values, tracks each newly-created root and
its descendants by PID, creation time, and executable, and never discovers cleanup
targets from ports or unrelated process names.
"""

from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from .model_types import ProcessOwnership
from .owned_process_tree import capture_process_tree, cleanup_owned_processes
from .process_cleanup import CleanupMode


class E2EProcessRole(StrEnum):
    """The only process roles an assessment Local E2E run may start."""

    FRONTEND = "frontend"
    ENGINE = "engine"
    BROWSER = "browser"


@dataclass(frozen=True, slots=True)
class E2EProcessHandle:
    """A controller-local handle for one newly-created process root."""

    role: E2EProcessRole
    pid: int


@dataclass(frozen=True, slots=True)
class E2EProcessCompletion:
    """The terminating browser/scenario process outcome."""

    exit_code: int | None
    timed_out: bool = False


class SubprocessOwnedE2EController:
    """Start exact local fixture/production commands and clean only their trees."""

    def __init__(self, *, poll_interval_seconds: float = 0.05) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("poll interval must be positive")
        self._poll_interval = poll_interval_seconds
        self._processes: dict[E2EProcessHandle, subprocess.Popen[bytes]] = {}
        self._known_processes: dict[int, object] = {}

    def start(
        self,
        role: E2EProcessRole,
        command: object,
        environment: Mapping[str, str],
        stdout_path: Path,
        stderr_path: Path,
        ownership_token: str,
    ) -> E2EProcessHandle:
        """Start one exact command; the ownership token is inherited by descendants."""
        argv = command.exact_argv.values
        cwd = command.cwd
        child_environment = dict(environment)
        child_environment["OMNI_ASSESSMENT_OWNERSHIP_TOKEN"] = ownership_token
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stderr_path.parent.mkdir(parents=True, exist_ok=True)
        with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
            process = subprocess.Popen(  # noqa: S603
                argv,
                cwd=cwd,
                env=child_environment,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                shell=False,
                creationflags=(
                    subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
                ),
                start_new_session=os.name != "nt",
            )
        handle = E2EProcessHandle(role, process.pid)
        self._processes[handle] = process
        capture_process_tree(process.pid, self._known_processes)
        return handle

    def wait(
        self, handle: E2EProcessHandle, timeout_ms: int
    ) -> E2EProcessCompletion:
        """Wait only for the browser scenario process within the supplied bound."""
        if handle.role is not E2EProcessRole.BROWSER:
            raise ValueError("only the browser scenario process may be awaited")
        process = self._processes.get(handle)
        if process is None:
            raise ValueError("process handle is not owned by this controller")
        started = time.monotonic()
        while True:
            self._capture_all()
            exit_code = process.poll()
            if exit_code is not None:
                return E2EProcessCompletion(exit_code=exit_code)
            if int((time.monotonic() - started) * 1000) >= timeout_ms:
                return E2EProcessCompletion(exit_code=None, timed_out=True)
            time.sleep(self._poll_interval)

    def cleanup(
        self,
        handles: tuple[E2EProcessHandle, ...],
        ownership_token: str,
        mode: CleanupMode,
    ) -> ProcessOwnership:
        """Terminate only roots returned by this controller and observed descendants."""
        unknown = tuple(handle for handle in handles if handle not in self._processes)
        if unknown:
            raise ValueError("cleanup received a process not owned by this controller")
        self._capture_all()
        selected_pids = {handle.pid for handle in handles}
        identities = tuple(
            identity
            for identity in self._known_processes.values()
            if identity.pid in selected_pids or self._descends_from(identity, selected_pids)
        )
        ownership = cleanup_owned_processes(ownership_token, identities, mode)
        for handle in handles:
            self._processes.pop(handle, None)
        return ownership

    def _capture_all(self) -> None:
        for process in tuple(self._processes.values()):
            capture_process_tree(process.pid, self._known_processes)

    def _descends_from(self, identity: object, roots: set[int]) -> bool:
        parent_pid = identity.parent_pid
        seen: set[int] = set()
        while parent_pid is not None and parent_pid not in seen:
            if parent_pid in roots:
                return True
            seen.add(parent_pid)
            parent = self._known_processes.get(parent_pid)
            parent_pid = None if parent is None else parent.parent_pid
        return False
