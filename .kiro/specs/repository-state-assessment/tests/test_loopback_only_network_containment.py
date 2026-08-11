"""Production loopback-only Python containment integration tests."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from assessor.contained_process_runner import (
    ContainedProcessRunner,
    ProcessRunBlocked,
    RunnerContext,
    WriteAuditOutcome,
)
from assessor.execution_models import Applicability, CheckPlan, TerminationKind
from assessor.loopback_only_network_containment import (
    LoopbackOnlyNetworkContainment,
    establish_network_containment,
)
from assessor.model_types import (
    ExactArgumentVector,
    NetworkMode,
    NetworkPolicy,
    VerificationPlane,
    WritePolicy,
)
from assessor.write_admission import WriteAdmissionDecision


class _WriteAuditor:
    available = True

    def start(self, _plan: CheckPlan, _token: str) -> object:
        return object()

    def finish(self, _handle: object) -> WriteAuditOutcome:
        return WriteAuditOutcome(True, "writes/audit.json")


def _plan(root: Path, argv: tuple[str, ...], check_id: str = "network-check") -> CheckPlan:
    mirror = root / "mirror"
    output = root / "outputs"
    mirror.mkdir(parents=True, exist_ok=True)
    output.mkdir(exist_ok=True)
    return CheckPlan(
        check_id=check_id,
        plane=VerificationPlane.PYTHON_ENGINE,
        scope="loopback containment fixture",
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


def _context(root: Path, containment: LoopbackOnlyNetworkContainment) -> RunnerContext:
    return RunnerContext(
        temporary_root=root,
        mirror_root=root / "mirror",
        safe_parent_environment={
            name: os.environ.get(name, "")
            for name in ("PATH", "PATHEXT", "SYSTEMROOT", "WINDIR")
        },
        write_admission=WriteAdmissionDecision(True, None),
        write_auditor=_WriteAuditor(),
        network_containment=containment,
    )


def _run_loopback_client(root: Path, family: socket.AddressFamily, host: str) -> None:
    server = socket.socket(family, socket.SOCK_STREAM)
    server.settimeout(5)
    server.bind((host, 0))
    server.listen(1)
    port = server.getsockname()[1]
    received: list[bytes] = []

    def accept_once() -> None:
        connection, _address = server.accept()
        with connection:
            received.append(connection.recv(4))

    thread = threading.Thread(target=accept_once)
    thread.start()
    script = (
        "import socket; "
        f"s=socket.socket({int(family)}, socket.SOCK_STREAM); "
        f"s.connect(({host!r}, {port})); s.sendall(b'ping'); s.close()"
    )
    containment = LoopbackOnlyNetworkContainment(root)
    result = ContainedProcessRunner().run(
        _plan(root, (sys.executable, "-c", script)), _context(root, containment)
    )
    thread.join(timeout=5)
    server.close()
    assert result.termination.kind is TerminationKind.EXITED
    assert result.termination.exit_code == 0
    assert received == [b"ping"]


def _observation_lines(root: Path, reference: str) -> list[dict[str, str]]:
    path = root / reference
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_real_ipv4_loopback_connection_is_allowed(tmp_path: Path) -> None:
    """A guarded child can connect to a test-owned IPv4 loopback listener."""
    _run_loopback_client(tmp_path / "run", socket.AF_INET, "127.0.0.1")


def test_real_ipv6_loopback_connection_is_allowed(tmp_path: Path) -> None:
    """A guarded child can connect to a test-owned IPv6 loopback listener."""
    _run_loopback_client(tmp_path / "run", socket.AF_INET6, "::1")


def test_non_loopback_is_denied_and_quarantined_without_connecting(tmp_path: Path) -> None:
    """The installed guard denies before its underlying connect primitive is called."""
    root = tmp_path / "run"
    plan = _plan(root, (sys.executable, "-c", "pass"))
    containment = LoopbackOnlyNetworkContainment(root)
    lease = containment.establish(plan, "denial-order")
    assert lease.enforced
    guard_path = dict(lease.environment_updates)["PYTHONPATH"]
    probe = """import json, socket, sys
calls = []
def probe_connect(self, address):
    calls.append(repr(address))
socket.socket.connect = probe_connect
sys.path.insert(0, sys.argv[1])
import sitecustomize
sock = socket.socket()
for address in ((\"128.0.0.1\", 443), (\"2001:db8::1\", 443)):
    try:
        sock.connect(address)
    except PermissionError:
        pass
    else:
        raise SystemExit(90)
print(json.dumps(calls))
"""
    completed = subprocess.run(
        (sys.executable, "-S", "-c", probe, guard_path),
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    )
    containment.release(lease)
    assert json.loads(completed.stdout) == []
    assert lease.observation_ref is not None
    observations = _observation_lines(root, lease.observation_ref)
    denied = [item for item in observations if item["disposition"] == "denied"]
    assert [item["destination"] for item in denied] == [
        "('128.0.0.1', 443)",
        "('2001:db8::1', 443)",
    ]
    assert all(item["timestamp"] for item in denied)


def test_automatic_guard_denial_is_observable_in_quarantine(tmp_path: Path) -> None:
    """Normal Python startup imports the guard and records a safely invalid-port denial."""
    root = tmp_path / "run"
    script = """import socket
try:
    socket.socket().connect(('128.0.0.1', 70000))
except PermissionError:
    print('denied')
else:
    raise SystemExit(91)
"""
    result = ContainedProcessRunner().run(
        _plan(root, (sys.executable, "-c", script)),
        _context(root, LoopbackOnlyNetworkContainment(root)),
    )
    assert result.termination.exit_code == 0
    assert result.network_observation_ref is not None
    observations = _observation_lines(root, result.network_observation_ref)
    assert any(
        item["disposition"] == "denied" and "128.0.0.1" in item["destination"]
        for item in observations
    )


def test_guard_installation_failure_reports_unenforced_and_blocks(tmp_path: Path) -> None:
    """An unwritable guard location yields an omission and never launches the command."""
    root = tmp_path / "run"
    guard_parent = root / "network-containment"
    guard_parent.mkdir(parents=True)
    (guard_parent / "guards").write_text("collision", encoding="utf-8")
    marker = root / "outputs" / "launched.txt"
    plan = _plan(
        root,
        (sys.executable, "-c", f"from pathlib import Path; Path({str(marker)!r}).write_text('bad')"),
        "install-failure",
    )
    containment = LoopbackOnlyNetworkContainment(root)
    admission = establish_network_containment(containment, plan, "install-failure")
    assert not admission.lease.enforced
    assert admission.omission is not None
    with pytest.raises(ProcessRunBlocked, match="containment is unavailable"):
        ContainedProcessRunner().run(plan, _context(root, containment))
    assert not marker.exists()


def test_non_python_command_is_omitted_instead_of_executed(tmp_path: Path) -> None:
    """A Node command receives complete omission evidence and cannot be launched."""
    root = tmp_path / "run"
    marker = root / "outputs" / "node-launched.txt"
    plan = _plan(root, ("node", "-e", f"require('fs').writeFileSync({str(marker)!r}, 'bad')"), "node-check")
    containment = LoopbackOnlyNetworkContainment(root)
    admission = establish_network_containment(containment, plan, "node-check")
    assert not admission.lease.enforced
    assert admission.omission is not None
    assert admission.omission.operation_id == "node-check"
    assert admission.omission.command_or_procedure == plan.exact_argv.values
    assert admission.omission.affected_content == ()
    assert admission.omission.reason
    assert tuple(item.check_id for item in admission.omission.dependent_checks) == ("node-check",)
    with pytest.raises(ProcessRunBlocked, match="containment is unavailable"):
        ContainedProcessRunner().run(plan, _context(root, containment))
    assert not marker.exists()



def test_mirror_execution_omits_cmd_shell_before_runner() -> None:
    """The discovered desktop shell cannot provide Task 11.4 Python proof."""
    from assessor.mirror_execution_phase import _contained_argv

    assert _contained_argv(("cmd", "/c", "pnpm tauri build")) is None

def test_ipv4_and_ipv6_loopback_boundaries(tmp_path: Path) -> None:
    """Both IPv4 loopback edges and ::1 pass while adjacent/public ranges are denied."""
    root = tmp_path / "run"
    plan = _plan(root, (sys.executable, "-c", "pass"))
    containment = LoopbackOnlyNetworkContainment(root)
    lease = containment.establish(plan, "address-boundaries")
    guard_path = dict(lease.environment_updates)["PYTHONPATH"]
    probe = """import json, socket, sys
calls = []
def probe_connect(self, address):
    calls.append(address[0])
socket.socket.connect = probe_connect
sys.path.insert(0, sys.argv[1])
import sitecustomize
sock = socket.socket()
for host in ('127.0.0.1', '127.255.255.254', 'localhost', '::1'):
    sock.connect((host, 1))
for host in ('128.0.0.1', '2001:db8::1'):
    try:
        sock.connect((host, 1))
    except PermissionError:
        pass
    else:
        raise SystemExit(92)
print(json.dumps(calls))
"""
    completed = subprocess.run(
        (sys.executable, "-S", "-c", probe, guard_path),
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    )
    containment.release(lease)
    assert json.loads(completed.stdout) == [
        "127.0.0.1", "127.255.255.254", "localhost", "::1"
    ]
