"""Task 4.7 contained-runner integration tests for Requirements 3.1, 3.13,
3.14, 4.7, 4.8, and 7.2.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

import psutil
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

class _SocketGuardContainment(_NetworkContainment):
    def __init__(self, run_root: Path) -> None:
        super().__init__()
        self.run_root = run_root
    def establish(self, plan: CheckPlan, _token: str) -> NetworkContainmentLease:
        self.establish_calls += 1
        record = self.run_root / "network" / "non-loopback.json"
        record.parent.mkdir(parents=True, exist_ok=True)
        guard = f"""
import ipaddress, json, pathlib, socket
_record = pathlib.Path({str(record)!r})
_original_connect = socket.socket.connect
def _guarded_connect(self, address):
    host = str(address[0])
    loopback = ipaddress.ip_address(host).is_loopback
    _record.write_text(json.dumps({{"host": host, "loopback": loopback,
        "disposition": "allowed" if loopback else "denied"}}), encoding="utf-8")
    if not loopback:
        raise PermissionError("non-loopback egress denied")
    return _original_connect(self, address)
socket.socket.connect = _guarded_connect
"""
        (Path(plan.cwd) / "sitecustomize.py").write_text(guard, encoding="utf-8")
        return NetworkContainmentLease(True, "network/non-loopback.json")

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

def test_timeout_reaps_child_and_grandchild_but_preserves_sentinel(tmp_path: Path) -> None:
    """Timeout reaps the complete owned three-level tree and leaves a prior sentinel alive."""
    pid_file = tmp_path / "integration space 雪" / "run" / "outputs" / "descendants.txt"
    grandchild = "import threading; threading.Event().wait()"
    child = """import os,pathlib,subprocess,sys,threading
p=subprocess.Popen([sys.executable,'-c',sys.argv[1]])
pathlib.Path(sys.argv[2]).write_text(f'{os.getpid()},{p.pid}')
threading.Event().wait()
"""
    root = "import subprocess,sys; p=subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2],sys.argv[3]]); p.wait()"
    sentinel = subprocess.Popen([sys.executable, "-c", grandchild])
    try:
        # The timeout must comfortably outlast three cold interpreter starts, or the tree is
        # reaped before the grandchild records its pid and the reaping assertions below have
        # nothing to check. Boundary precision is pinned separately by the boundary test.
        plan = _plan(
            tmp_path,
            (sys.executable, "-c", root, child, grandchild, str(pid_file)),
            timeout_ms=6_000,
        )
        result = ContainedProcessRunner(poll_interval_seconds=0.005).run(plan, _context(tmp_path))
        def descendants_ready() -> bool:
            parts = pid_file.read_text().split(",") if pid_file.exists() else []
            return len(parts) == 2 and all(part.isdecimal() for part in parts)
        assert _wait_until(descendants_ready)
        child_pid, grandchild_pid = map(int, pid_file.read_text().split(","))
        assert result.termination.kind is TerminationKind.TIMED_OUT
        owned_pids = {process.pid for process in result.process_ownership.processes}
        assert {child_pid, grandchild_pid} <= owned_pids
        assert sentinel.pid not in owned_pids
        assert result.process_ownership.cleanup_completed
        assert all(_wait_until(lambda pid=pid: not psutil.pid_exists(pid)) for pid in owned_pids)
        assert sentinel.poll() is None
    finally:
        sentinel.terminate()
        sentinel.wait(timeout=5)

def test_all_command_writes_and_output_stay_below_temporary_root(tmp_path: Path) -> None:
    """Writable homes, cwd, temp files, stdout, and stderr remain under the run root."""
    script = """import json,os,pathlib
paths=[]
for key in ('HOME','USERPROFILE','APPDATA','LOCALAPPDATA','TEMP','TMP'):
 p=pathlib.Path(os.environ[key])/f'{key}.txt'; p.write_text(key); paths.append(str(p.resolve()))
p=pathlib.Path('cwd.txt'); p.write_text('cwd'); paths.append(str(p.resolve()))
print(json.dumps(paths)); os.write(2,b'routed-stderr\\n')
"""
    plan = _plan(tmp_path, (sys.executable, "-c", script))
    result = ContainedProcessRunner().run(plan, _context(tmp_path))
    run_root = (tmp_path / "integration space 雪" / "run").resolve()
    written = json.loads(_artifact(tmp_path, result.stdout_ref).read_text(encoding="utf-8"))
    assert all(Path(path).is_relative_to(run_root) for path in written)
    assert _artifact(tmp_path, result.stderr_ref).read_bytes() == b"routed-stderr\n"
    outside = [
        path for path in tmp_path.rglob("*")
        if path.is_file() and not path.resolve().is_relative_to(run_root)
    ]
    assert outside == []

def test_non_loopback_connection_is_denied_and_recorded_without_egress(tmp_path: Path) -> None:
    """An attempted documentation-range connection is denied before networking and recorded."""
    script = """exec(open('sitecustomize.py', encoding='utf-8').read(), {})
import socket
try:
 socket.socket().connect(('203.0.113.1', 9))
except PermissionError as error:
 print(str(error))
else:
 raise SystemExit(99)
"""
    plan = _plan(
        tmp_path,
        (sys.executable, "-c", script),
        network_mode=NetworkMode.LOOPBACK_ONLY,
    )
    run_root = tmp_path / "integration space 雪" / "run"
    network = _SocketGuardContainment(run_root)
    result = ContainedProcessRunner().run(plan, _context(tmp_path, network))
    assert result.termination.kind is TerminationKind.EXITED
    assert result.termination.exit_code == 0
    assert _artifact(tmp_path, result.stdout_ref).read_text(encoding="utf-8") == "non-loopback egress denied\n"
    assert result.network_observation_ref == "network/non-loopback.json"
    observation = json.loads((run_root / result.network_observation_ref).read_text())
    assert observation == {"host": "203.0.113.1", "loopback": False, "disposition": "denied"}
    assert network.establish_calls == network.release_calls == 1
