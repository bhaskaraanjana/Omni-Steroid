"""Launch one fresh command under fail-closed process, write, and network containment.

Raw stdout/stderr stay quarantined below the temporary run root. The runner never
uses a shell, mutates argv, reuses a process, or trusts PID alone during cleanup.
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from .contained_process_environment import (
    build_contained_environment,
    require_terminating_command,
)
from .contained_process_protocols import (
    NetworkContainment,
    NetworkContainmentLease,
    WriteAuditor,
    WriteAuditOutcome,
)
from .contained_runner_support import ProcessRunBlocked as ProcessRunBlocked
from .contained_runner_support import existing_directory, safe_file_part
from .containment_proof import decide_containment_proof
from .execution_models import (
    Applicability,
    CheckPlan,
    RawExecutionResult,
    Termination,
    TerminationKind,
)
from .model_types import OwnedProcess, ZonedTimestamp
from .owned_process_tree import (
    ProcessInspectionUnavailable,
    capture_process_tree,
    cleanup_owned_processes,
    require_process_inspection,
)
from .process_cleanup import CleanupMode
from .write_admission import WriteAdmissionDecision


@dataclass(frozen=True, slots=True)
class RunnerContext:
    """Assessment-owned roots and explicit containment dependencies for one run."""

    temporary_root: Path
    mirror_root: Path
    safe_parent_environment: Mapping[str, str]
    write_admission: WriteAdmissionDecision
    write_auditor: WriteAuditor
    network_containment: NetworkContainment


class ContainedProcessRunner:
    """Execute exact admitted commands once and clean their owned process trees."""

    def __init__(self, *, poll_interval_seconds: float = 0.05) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("poll interval must be positive")
        self._poll_interval = poll_interval_seconds
        self._active: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    def cancel(self, check_id: str) -> bool:
        """Request cancellation of the currently active attempt for ``check_id``."""
        with self._lock:
            event = self._active.get(check_id)
            if event is None:
                return False
            event.set()
            return True

    def run(self, plan: CheckPlan, context: RunnerContext) -> RawExecutionResult:
        """Launch one exact argv and return raw quarantined execution metadata."""
        temporary_root, mirror_root = self._preflight(plan, context)
        ownership_token = f"{safe_file_part(plan.check_id)}-{uuid4().hex}"
        environment = build_contained_environment(
            temporary_root, ownership_token, context.safe_parent_environment
        )
        lease = context.network_containment.establish(plan, ownership_token)
        if not lease.enforced:
            context.network_containment.release(lease)
            raise ProcessRunBlocked("enforceable non-loopback network containment is unavailable")
        try:
            for name, value in lease.environment_updates:
                if name != "PYTHONPATH" or not value:  # Control: guard-only update.
                    raise ProcessRunBlocked(
                        "network containment returned an unsafe environment update"
                    )
                environment[name] = value  # Control: child guard injection.
        except ProcessRunBlocked:
            context.network_containment.release(lease)
            raise
        audit_handle: object | None = None
        try:
            audit_handle = context.write_auditor.start(plan, ownership_token)
            return self._execute(
                plan,
                context,
                temporary_root,
                mirror_root,
                ownership_token,
                environment,
                lease,
                audit_handle,
            )
        finally:
            context.network_containment.release(lease)

    def _preflight(self, plan: CheckPlan, context: RunnerContext) -> tuple[Path, Path]:
        try:
            require_terminating_command(plan)
            require_process_inspection()
        except (ValueError, ProcessInspectionUnavailable) as error:
            raise ProcessRunBlocked(str(error)) from error
        if plan.applicability is not Applicability.APPLICABLE:
            raise ProcessRunBlocked("check is not applicable to this host or configuration")
        unavailable = tuple(item.name for item in plan.prerequisites if item.available is False)
        if unavailable:
            raise ProcessRunBlocked(f"named prerequisites unavailable: {', '.join(unavailable)}")
        if plan.external_dependency:
            raise ProcessRunBlocked("live external dependencies are prohibited")
        if not context.write_admission.admitted:
            reason = (
                context.write_admission.omission.reason
                if context.write_admission.omission is not None
                else "write admission denied"
            )
            raise ProcessRunBlocked(reason)
        if not context.write_auditor.available:
            raise ProcessRunBlocked("complete owned-tree write auditing is unavailable")
        temporary_root = existing_directory(context.temporary_root, "temporary root")
        mirror_root = existing_directory(context.mirror_root, "mirror root")
        cwd = existing_directory(Path(plan.cwd), "command working directory")
        if not cwd.is_relative_to(mirror_root):
            raise ProcessRunBlocked("command working directory escapes the execution mirror")
        for root_text in plan.write_policy.designated_roots:
            root = Path(root_text).resolve(strict=False)
            if root == temporary_root or not root.is_relative_to(temporary_root):
                raise ProcessRunBlocked("declared write root escapes the temporary run root")
        return temporary_root, mirror_root

    def _execute(
        self,
        plan: CheckPlan,
        context: RunnerContext,
        temporary_root: Path,
        _mirror_root: Path,
        ownership_token: str,
        environment: Mapping[str, str],
        lease: NetworkContainmentLease,
        audit_handle: object,
    ) -> RawExecutionResult:
        exact_argv = plan.exact_argv
        if exact_argv is None:  # Control: procedures never reach subprocess launch.
            raise ProcessRunBlocked("contained subprocess requires exact argv")
        raw_directory = temporary_root / "raw"
        raw_directory.mkdir(exist_ok=True)
        stem = f"{safe_file_part(plan.check_id)}-{ownership_token.rsplit('-', 1)[-1]}"
        stdout_path = raw_directory / f"{stem}.stdout"
        stderr_path = raw_directory / f"{stem}.stderr"
        cancel_event = threading.Event()
        self._register(plan.check_id, cancel_event)
        known_processes: dict[int, OwnedProcess] = {}
        process: subprocess.Popen[bytes] | None = None
        started_at = ZonedTimestamp(datetime.now().astimezone())
        started_monotonic = time.monotonic()
        termination = Termination(TerminationKind.CRASHED, timeout_ms=plan.timeout_ms)
        command_duration_ms = 0
        cleanup_mode = CleanupMode.FAILURE
        proof_granted = not lease.proof_required  # Control: external adapters attest separately.
        proof_deadline_ms = min(plan.timeout_ms, 5_000)  # Control: bounded startup proof wait.
        blocked_reason: str | None = None
        try:
            with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
                # Exact repository argv, admitted above; shell expansion stays disabled.
                process = subprocess.Popen(  # noqa: S603
                    exact_argv.values,
                    cwd=plan.cwd,
                    env=dict(environment),
                    stdin=subprocess.DEVNULL,
                    stdout=stdout,
                    stderr=stderr,
                    shell=False,
                    creationflags=(
                        subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
                    ),
                    start_new_session=os.name != "nt",
                )
                capture_process_tree(process.pid, known_processes)
                while True:
                    capture_process_tree(process.pid, known_processes)
                    exit_code = process.poll()
                    elapsed_ms = int((time.monotonic() - started_monotonic) * 1000)
                    if not proof_granted:
                        decision = decide_containment_proof(
                            temporary_root,
                            lease,
                            {
                                pid: identity.executable
                                for pid, identity in known_processes.items()
                            },
                            elapsed_ms,
                            exit_code is not None,
                            proof_deadline_ms,
                        )
                        proof_granted = decision.granted
                        blocked_reason = decision.blocked_reason
                        if blocked_reason is not None:
                            termination = Termination(
                                TerminationKind.CRASHED, timeout_ms=plan.timeout_ms
                            )
                            cleanup_mode = CleanupMode.ABORT
                            command_duration_ms = elapsed_ms
                            break
                    if exit_code is not None:
                        termination = Termination(
                            TerminationKind.EXITED, exit_code, timeout_ms=plan.timeout_ms
                        )
                        cleanup_mode = (
                            CleanupMode.SUCCESS
                            if exit_code == 0
                            else CleanupMode.FAILURE
                        )
                        command_duration_ms = elapsed_ms
                        break
                    if cancel_event.is_set():
                        termination = Termination(
                            TerminationKind.CANCELLED, timeout_ms=plan.timeout_ms
                        )
                        cleanup_mode = CleanupMode.ABORT
                        command_duration_ms = elapsed_ms
                        break
                    if elapsed_ms >= plan.timeout_ms:
                        termination = Termination(
                            TerminationKind.TIMED_OUT, timeout_ms=plan.timeout_ms
                        )
                        cleanup_mode = CleanupMode.TIMEOUT
                        command_duration_ms = elapsed_ms
                        break
                    time.sleep(self._poll_interval)
        except KeyboardInterrupt:
            termination = Termination(TerminationKind.CANCELLED, timeout_ms=plan.timeout_ms)
            cleanup_mode = CleanupMode.ABORT
            command_duration_ms = int((time.monotonic() - started_monotonic) * 1000)
        finally:
            if process is not None:
                capture_process_tree(process.pid, known_processes)
            identities = tuple(known_processes.values())
            ownership = cleanup_owned_processes(
                ownership_token, identities, cleanup_mode
            )
            self._unregister(plan.check_id)
        try:
            audit = context.write_auditor.finish(audit_handle)
        except Exception:
            audit = WriteAuditOutcome(False, None)
        if not audit.compliant:
            termination = Termination(TerminationKind.CRASHED, timeout_ms=plan.timeout_ms)
        if blocked_reason is not None:  # Control: unproven execution is omitted, not failed.
            raise ProcessRunBlocked(blocked_reason)
        return RawExecutionResult(
            check_id=plan.check_id,
            exact_argv=plan.exact_argv,
            numbered_procedure=None,
            cwd=plan.cwd,
            started_at=started_at,
            duration_ms=command_duration_ms,
            termination=termination,
            stdout_ref=stdout_path.relative_to(temporary_root).as_posix(),
            stderr_ref=stderr_path.relative_to(temporary_root).as_posix(),
            process_ownership=ownership,
            write_audit_ref=audit.audit_ref,
            network_observation_ref=lease.observation_ref,
        )

    def _register(self, check_id: str, event: threading.Event) -> None:
        with self._lock:
            if check_id in self._active:
                raise ProcessRunBlocked(f"check already has an active attempt: {check_id}")
            self._active[check_id] = event

    def _unregister(self, check_id: str) -> None:
        with self._lock:
            self._active.pop(check_id, None)
