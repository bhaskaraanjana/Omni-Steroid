"""Task 4.7 contained-runner integration tests for Requirements 3.1, 3.13,
3.14, 4.7, 4.8, and 7.2.
"""

from __future__ import annotations

import _thread
import os
import sys
import threading
import time
from pathlib import Path
from typing import Callable

import psutil
import pytest
from assessor.contained_process_runner import ProcessRunBlocked
from assessor.contained_process_runner import (
    ContainedProcessRunner,
    NetworkContainmentLease,
    RunnerContext,
    WriteAuditOutcome,
)
from assessor.execution_models import Applicability, CheckPlan, Prerequisite, TerminationKind
from assessor.model_types import (
    ExactArgumentVector,
    NetworkMode,
    NetworkPolicy,
    VerificationPlane,
    WritePolicy,
)
from assessor.write_admission import WriteAdmissionDecision

class _NetworkContainment:
    def __init__(self, *, enforced: bool = True) -> None:
        self.enforced = enforced
        self.establish_calls = 0
        self.release_calls = 0
    def establish(self, _plan: CheckPlan, _token: str) -> NetworkContainmentLease:
        self.establish_calls += 1
        return NetworkContainmentLease(self.enforced, "network/observation.json")
    def release(self, _lease: NetworkContainmentLease) -> None:
        self.release_calls += 1

class _WriteAuditor:
    available = True
    def __init__(self) -> None:
        self.starts = 0
        self.finishes = 0
    def start(self, _plan: CheckPlan, _token: str) -> object:
        self.starts += 1
        return object()
    def finish(self, _handle: object) -> WriteAuditOutcome:
        self.finishes += 1
        return WriteAuditOutcome(True, "writes/audit.json")

def _plan(
    base: Path,
    argv: tuple[str, ...],
    *,
    timeout_ms: int = 3_000,
    prerequisites: tuple[Prerequisite, ...] = (),
    network_mode: NetworkMode = NetworkMode.NONE,
) -> CheckPlan:
    run_root = base / "integration space 雪" / "run"
    mirror = run_root / "mirror"
    output = run_root / "outputs"
    mirror.mkdir(parents=True, exist_ok=True)
    output.mkdir(exist_ok=True)
    return CheckPlan(
        check_id="disposable-fixture",
        plane=VerificationPlane.PYTHON_ENGINE,
        scope="disposable contained-runner integration fixture",
        command_source=None,
        exact_argv=ExactArgumentVector(argv),
        numbered_procedure=None,
        cwd=str(mirror),
        prerequisites=prerequisites,
        applicability=Applicability.APPLICABLE,
        applicability_basis="synthetic fixture",
        timeout_ms=timeout_ms,
        write_policy=WritePolicy((str(output),)),
        network_policy=NetworkPolicy(network_mode),
        external_dependency=False,
        dependent_check_ids=(),
        cleanup_procedure=("terminate matching owned process tree",),
    )

def _context(
    base: Path,
    network: _NetworkContainment | None = None,
    auditor: _WriteAuditor | None = None,
) -> RunnerContext:
    run_root = base / "integration space 雪" / "run"
    return RunnerContext(
        temporary_root=run_root,
        mirror_root=run_root / "mirror",
        safe_parent_environment={
            "PATH": os.environ.get("PATH", ""),
            "PATHEXT": os.environ.get("PATHEXT", ""),
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
            "WINDIR": os.environ.get("WINDIR", ""),
        },
        write_admission=WriteAdmissionDecision(True, None),
        write_auditor=auditor or _WriteAuditor(),
        network_containment=network or _NetworkContainment(),
    )

def _artifact(base: Path, result_ref: str) -> Path:
    return base / "integration space 雪" / "run" / result_ref

def _wait_until(predicate: Callable[[], bool], timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    wake = threading.Event()
    while not predicate():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        wake.wait(min(0.01, remaining))
    return True

def test_success_preserves_exact_large_unicode_output_and_quoted_argv(tmp_path: Path) -> None:
    """A fresh exit-zero command preserves exact bytes, argv, and quarantined routes."""
    marker = tmp_path / "integration space 雪" / "run" / "outputs" / "argv.txt"
    quoted = "space value with \"double\", 'single', and 雪"
    script = """
import pathlib, sys
payload = b"A" * 131073 + "|snow=雪|\\n".encode()
error = "stderr—雪\\n".encode()
sys.stdout.buffer.write(payload); sys.stdout.close()
sys.stderr.buffer.write(error); sys.stderr.flush()
pathlib.Path(sys.argv[2]).write_text(sys.argv[1], encoding="utf-8")
"""
    argv = (sys.executable, "-c", script, quoted, str(marker))
    plan = _plan(tmp_path, argv)
    result = ContainedProcessRunner(poll_interval_seconds=0.005).run(plan, _context(tmp_path))
    assert result.exact_argv == ExactArgumentVector(argv)
    assert result.termination.kind is TerminationKind.EXITED
    assert result.termination.exit_code == 0
    assert 0 <= result.duration_ms < plan.timeout_ms
    assert _artifact(tmp_path, result.stdout_ref).read_bytes() == (
        b"A" * 131073 + "|snow=雪|\n".encode()
    )
    assert _artifact(tmp_path, result.stderr_ref).read_bytes() == "stderr—雪\n".encode()
    assert marker.read_text(encoding="utf-8") == quoted

def test_failure_preserves_exact_nonzero_exit_and_empty_output(tmp_path: Path) -> None:
    """A silent product failure remains exact exit 197 rather than becoming blocked or zero."""
    plan = _plan(tmp_path, (sys.executable, "-c", "import os; os._exit(197)"))
    result = ContainedProcessRunner(poll_interval_seconds=0.005).run(plan, _context(tmp_path))
    assert result.termination.kind is TerminationKind.EXITED
    assert result.termination.exit_code == 197
    assert _artifact(tmp_path, result.stdout_ref).read_bytes() == b""
    assert _artifact(tmp_path, result.stderr_ref).read_bytes() == b""

def test_timeout_is_recorded_at_boundary_and_terminates_command(tmp_path: Path) -> None:
    """A ready command blocked beyond 600 ms is timed out at, not below, its boundary."""
    ready = tmp_path / "integration space 雪" / "run" / "outputs" / "ready.txt"
    script = "import pathlib,sys,threading; pathlib.Path(sys.argv[1]).write_text('ready'); threading.Event().wait()"
    plan = _plan(tmp_path, (sys.executable, "-c", script, str(ready)), timeout_ms=600)
    result = ContainedProcessRunner(poll_interval_seconds=0.005).run(plan, _context(tmp_path))
    assert _wait_until(lambda: ready.exists() and ready.read_text(encoding="utf-8") == "ready")
    assert result.termination.kind is TerminationKind.TIMED_OUT
    assert result.termination.exit_code is None
    assert result.termination.timeout_ms == 600
    assert 600 <= result.duration_ms < 850
    assert result.process_ownership.cleanup_completed

def test_keyboard_interrupt_runs_cleanup_and_outer_finally(tmp_path: Path) -> None:
    """KeyboardInterrupt after child readiness records cancellation and runs both cleanups."""
    marker = tmp_path / "integration space 雪" / "run" / "outputs" / "pid.txt"
    script = "import os,pathlib,sys,threading; pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); threading.Event().wait()"
    plan = _plan(tmp_path, (sys.executable, "-c", script, str(marker)), timeout_ms=10_000)
    network, auditor = _NetworkContainment(), _WriteAuditor()
    trigger_errors: list[str] = []
    def interrupt_when_ready() -> None:
        if not _wait_until(marker.exists):
            trigger_errors.append("child readiness marker was not observed")
            return
        _thread.interrupt_main()
    interrupter = threading.Thread(target=interrupt_when_ready, daemon=True)
    interrupter.start()
    result = ContainedProcessRunner(poll_interval_seconds=0.005).run(
        plan, _context(tmp_path, network, auditor)
    )
    interrupter.join(timeout=2)
    pid = int(marker.read_text(encoding="utf-8"))
    assert trigger_errors == []
    assert not interrupter.is_alive()
    assert result.termination.kind is TerminationKind.CANCELLED
    assert result.termination.exit_code is None
    assert result.process_ownership.cleanup_completed
    assert _wait_until(lambda: not psutil.pid_exists(pid))
    assert network.establish_calls == network.release_calls == 1
    assert auditor.starts == auditor.finishes == 1

def test_missing_executable_is_preflight_blocked_not_product_failure(tmp_path: Path) -> None:
    """A confirmed absent executable is blocked before launch and has no failure output."""
    missing = "definitely-missing-omni-assessment-tool.exe"
    prerequisite = Prerequisite(missing, ("where", missing), False, "preflight/tool.json")
    plan = _plan(tmp_path, (missing, "--version"), prerequisites=(prerequisite,))
    network = _NetworkContainment()
    with pytest.raises(
        ProcessRunBlocked,
        match=r"^named prerequisites unavailable: definitely-missing-omni-assessment-tool\.exe$",
    ):
        ContainedProcessRunner().run(plan, _context(tmp_path, network))
    assert network.establish_calls == network.release_calls == 0
    assert not (tmp_path / "integration space 雪" / "run" / "raw").exists()
