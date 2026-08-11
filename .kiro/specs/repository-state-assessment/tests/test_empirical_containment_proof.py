"""Boundary tests for empirically proven loopback containment."""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
from pathlib import Path

import pytest
from assessor.contained_process_protocols import (
    NetworkContainment,
    NetworkContainmentLease,
    WriteAuditOutcome,
)
from assessor.contained_process_runner import (
    ContainedProcessRunner,
    ProcessRunBlocked,
    RunnerContext,
)
from assessor.execution_models import Applicability, CheckPlan, TerminationKind
from assessor.loopback_only_network_containment import LoopbackOnlyNetworkContainment
from assessor.model_types import (
    ExactArgumentVector,
    NetworkMode,
    NetworkPolicy,
    VerificationPlane,
    WritePolicy,
)
from assessor.write_admission import WriteAdmissionDecision


class _WriteAuditor:
    """Minimal test double isolating network-containment behavior."""

    available = True

    def start(self, _plan: CheckPlan, _token: str) -> object:
        return object()

    def finish(self, _handle: object) -> WriteAuditOutcome:
        return WriteAuditOutcome(True, "write-audit/synthetic.json")


class _StaleMarkerContainment:
    """Decorator that inserts an invalid prior-lease marker before launch."""

    def __init__(self, delegate: LoopbackOnlyNetworkContainment, root: Path) -> None:
        self._delegate = delegate
        self._root = root

    def establish(
        self, plan: CheckPlan, token: str
    ) -> NetworkContainmentLease:
        lease = self._delegate.establish(plan, token)
        assert lease.observation_ref is not None
        stale = {
            "destination": "guard-startup",
            "disposition": "guard_loaded",
            "interpreter": sys.executable,
            "kind": "containment_proof",
            "pid": os.getpid(),
            "token": "different-stale-lease-token",
        }
        with (self._root / lease.observation_ref).open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(stale, sort_keys=True) + "\n")
        return lease

    def release(self, lease: NetworkContainmentLease) -> None:
        self._delegate.release(lease)


def _plan(root: Path, argv: tuple[str, ...], check_id: str = "proof") -> CheckPlan:
    mirror = root / "mirror"
    output = root / "outputs"
    mirror.mkdir(parents=True, exist_ok=True)
    output.mkdir(exist_ok=True)
    return CheckPlan(
        check_id=check_id,
        plane=VerificationPlane.PYTHON_ENGINE,
        scope="synthetic containment proof",
        command_source=None,
        exact_argv=ExactArgumentVector(argv),
        numbered_procedure=None,
        cwd=str(mirror),
        prerequisites=(),
        applicability=Applicability.APPLICABLE,
        applicability_basis="synthetic fixture",
        timeout_ms=5_000,
        write_policy=WritePolicy((str(output),)),
        network_policy=NetworkPolicy(NetworkMode.LOOPBACK_ONLY),
        external_dependency=False,
        dependent_check_ids=(),
        cleanup_procedure=("terminate owned process tree",),
    )


def _context(root: Path, containment: NetworkContainment) -> RunnerContext:
    inherited = {
        name: os.environ.get(name, "")
        for name in ("PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC")
    }
    return RunnerContext(
        temporary_root=root,
        mirror_root=root / "mirror",
        safe_parent_environment=inherited,
        write_admission=WriteAdmissionDecision(True, None),
        write_auditor=_WriteAuditor(),
        network_containment=containment,
    )


def _events(root: Path, reference: str) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in (root / reference).read_text(encoding="utf-8").splitlines()
    ]


def test_direct_interpreter_proves_guard_before_user_code(tmp_path: Path) -> None:
    """A valid marker admits the check and identifies its guarded interpreter."""
    root = tmp_path / "run"
    marker = root / "outputs" / "user-code-ran"
    script = f"from pathlib import Path; Path({str(marker)!r}).write_text('yes')"
    result = ContainedProcessRunner(poll_interval_seconds=0.005).run(
        _plan(root, (sys.executable, "-c", script)),
        _context(root, LoopbackOnlyNetworkContainment(root)),
    )
    assert result.termination.kind is TerminationKind.EXITED
    assert result.termination.exit_code == 0
    assert marker.read_text(encoding="utf-8") == "yes"
    assert result.network_observation_ref is not None
    proofs = [
        event for event in _events(root, result.network_observation_ref)
        if event["kind"] == "containment_proof"
    ]
    assert len(proofs) == 1
    proof_pid = proofs[0]["pid"]
    assert isinstance(proof_pid, int)
    assert proof_pid > 0
    assert Path(str(proofs[0]["interpreter"])).resolve() == Path(sys.executable).resolve()


def test_site_suppression_is_blocked_before_user_code(tmp_path: Path) -> None:
    """A command unable to load the guard is refused without running its payload."""
    root = tmp_path / "run"
    marker = root / "outputs" / "must-not-run"
    script = f"from pathlib import Path; Path({str(marker)!r}).write_text('bad')"
    with pytest.raises(ProcessRunBlocked, match="containment is unavailable"):
        ContainedProcessRunner().run(
            _plan(root, (sys.executable, "-S", "-c", script), "site-disabled"),
            _context(root, LoopbackOnlyNetworkContainment(root)),
        )
    assert not marker.exists()


def test_stale_or_ambiguous_lease_marker_is_rejected(tmp_path: Path) -> None:
    """A stale token cannot release guarded user code for the current lease."""
    root = tmp_path / "run"
    marker = root / "outputs" / "must-not-run"
    script = f"from pathlib import Path; Path({str(marker)!r}).write_text('bad')"
    delegate = LoopbackOnlyNetworkContainment(root)
    containment = _StaleMarkerContainment(delegate, root)
    with pytest.raises(ProcessRunBlocked, match="proof marker"):
        ContainedProcessRunner(poll_interval_seconds=0.005).run(
            _plan(root, (sys.executable, "-c", script), "stale-proof"),
            _context(root, containment),
        )
    assert not marker.exists()


def test_launcher_is_admitted_only_after_nested_interpreter_proves_guard(
    tmp_path: Path,
) -> None:
    """The executable name need not be Python when a guarded child proves loading."""
    root = tmp_path / "run"
    marker = root / "outputs" / "launcher-ran"
    code = f"from pathlib import Path; Path({str(marker)!r}).write_text('yes')"
    argv: tuple[str, ...]
    if os.name == "nt":
        shell = os.environ["COMSPEC"]
        mirror = root / "mirror"
        mirror.mkdir(parents=True)
        payload = mirror / "payload.py"
        payload.write_text(code, encoding="utf-8")
        launcher = mirror / "launcher.cmd"
        launcher.write_text(
            f'@echo off\n"{sys.executable}" "{payload}"\n', encoding="utf-8"
        )
        argv = (shell, "/d", "/c", str(launcher))
    else:
        import shlex
        argv = ("/bin/sh", "-c", f"exec {shlex.quote(sys.executable)} -c {shlex.quote(code)}")
    result = ContainedProcessRunner(poll_interval_seconds=0.005).run(
        _plan(root, argv, "launcher-proof"),
        _context(root, LoopbackOnlyNetworkContainment(root)),
    )
    assert result.termination.exit_code == 0
    assert marker.read_text(encoding="utf-8") == "yes"


def test_loopback_allowed_and_non_loopback_denied_with_proof(tmp_path: Path) -> None:
    """A proven guard permits loopback and denies a synthetic non-loopback address."""
    root = tmp_path / "run"
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    received: list[bytes] = []
    thread = threading.Thread(
        target=lambda: received.append(server.accept()[0].recv(4)), daemon=True
    )
    thread.start()
    port = server.getsockname()[1]
    script = f"""import socket
s=socket.create_connection(('127.0.0.1',{port})); s.sendall(b'ping'); s.close()
try:
 socket.socket().connect(('192.0.2.1', 70000))
except PermissionError:
 print('denied')
else:
 raise SystemExit(93)
"""
    result = ContainedProcessRunner(poll_interval_seconds=0.005).run(
        _plan(root, (sys.executable, "-c", script), "network-boundary"),
        _context(root, LoopbackOnlyNetworkContainment(root)),
    )
    thread.join(timeout=5)
    server.close()
    assert received == [b"ping"]
    assert result.termination.exit_code == 0
    assert result.network_observation_ref is not None
    dispositions = [event["disposition"] for event in _events(root, result.network_observation_ref)]
    assert dispositions.count("guard_loaded") == 1
    assert "allowed" in dispositions
    assert "denied" in dispositions
