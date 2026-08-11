"""Task 11.6 native-integration phase and no-egress containment tests.

These are adversarial by intent: the phase must never turn a missing prerequisite
or a containment refusal into a product failure, must never execute scoped
behavior during preflight, and must never let a `NetworkMode.NONE` procedure reach
the network — including loopback, which the weaker adapter would have allowed.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
from pathlib import Path

import pytest
from assessor.assessment_phase_gates import AssessmentPhase, GateStatus, parse_phase
from assessor.contained_process_runner import (
    ContainedProcessRunner,
    ProcessRunBlocked,
    RunnerContext,
    WriteAuditOutcome,
)
from assessor.execution_models import Applicability, CheckPlan, TerminationKind
from assessor.hardware_status import HardwareScope
from assessor.loopback_only_network_containment import LoopbackOnlyNetworkContainment
from assessor.model_types import (
    AssessmentStatus,
    ExactArgumentVector,
    NetworkMode,
    NetworkPolicy,
    VerificationPlane,
    WritePolicy,
)
from assessor.native_integration_phase import (
    NATIVE_CHECK_IDS,
    execute_native_integration,
)
from assessor.no_egress_network_containment import NoEgressNetworkContainment
from assessor.observed_write_auditor import ObservedWriteAuditor
from assessor.write_admission import WriteAdmissionDecision


class _WriteAuditor:
    available = True

    def start(self, _plan: CheckPlan, _token: str) -> object:
        return object()

    def finish(self, _handle: object) -> WriteAuditOutcome:
        return WriteAuditOutcome(True, "writes/audit.json")


def _plan(root: Path, argv: tuple[str, ...], mode: NetworkMode) -> CheckPlan:
    mirror = root / "mirror"
    output = root / "outputs"
    mirror.mkdir(parents=True, exist_ok=True)
    output.mkdir(exist_ok=True)
    return CheckPlan(
        check_id="native-containment-fixture",
        plane=VerificationPlane.HARDWARE_INTEGRATION,
        scope="no-egress containment fixture",
        command_source=None,
        exact_argv=ExactArgumentVector(argv),
        numbered_procedure=None,
        cwd=str(mirror),
        prerequisites=(),
        applicability=Applicability.APPLICABLE,
        applicability_basis="synthetic fixture",
        timeout_ms=20_000,
        write_policy=WritePolicy((str(output),)),
        network_policy=NetworkPolicy(mode),
        external_dependency=False,
        dependent_check_ids=(),
        cleanup_procedure=("terminate owned process tree",),
    )


def _context(root: Path, containment: object) -> RunnerContext:
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


def test_native_integration_phase_is_ordered_between_local_e2e_and_normalization() -> None:
    phases = tuple(AssessmentPhase)
    assert phases.index(AssessmentPhase.LOCAL_E2E) + 1 == phases.index(
        AssessmentPhase.NATIVE_INTEGRATION
    )
    assert phases.index(AssessmentPhase.NATIVE_INTEGRATION) + 1 == phases.index(
        AssessmentPhase.NORMALIZATION
    )
    assert parse_phase("native-integration") is AssessmentPhase.NATIVE_INTEGRATION
    assert parse_phase("NATIVE_INTEGRATION") is AssessmentPhase.NATIVE_INTEGRATION


def test_no_egress_adapter_refuses_a_loopback_only_plan(tmp_path: Path) -> None:
    plan = _plan(tmp_path, (sys.executable, "-c", "pass"), NetworkMode.LOOPBACK_ONLY)
    lease = NoEgressNetworkContainment(tmp_path).establish(plan, "token-a")
    assert lease.enforced is False


def test_loopback_adapter_refuses_a_no_egress_plan(tmp_path: Path) -> None:
    plan = _plan(tmp_path, (sys.executable, "-c", "pass"), NetworkMode.NONE)
    lease = LoopbackOnlyNetworkContainment(tmp_path).establish(plan, "token-b")
    assert lease.enforced is False


def test_no_egress_guard_permits_the_same_process_self_pipe(tmp_path: Path) -> None:
    """asyncio's Windows self-pipe is same-process IPC and must survive the guard."""
    script = (
        "import asyncio, sys\n"
        "async def main():\n"
        "    await asyncio.sleep(0)\n"
        "    return 'ran'\n"
        "print(asyncio.run(main()))\n"
    )
    result = ContainedProcessRunner().run(
        _plan(tmp_path, (sys.executable, "-c", script), NetworkMode.NONE),
        _context(tmp_path, NoEgressNetworkContainment(tmp_path)),
    )
    assert result.termination.kind is TerminationKind.EXITED
    assert result.termination.exit_code == 0
    stdout = (tmp_path / str(result.stdout_ref)).read_text(encoding="utf-8")
    assert "ran" in stdout


def test_no_egress_guard_denies_another_process_loopback_and_records_the_attempt(
    tmp_path: Path,
) -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.settimeout(5)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    accepted: list[bool] = []

    def accept_once() -> None:
        try:
            connection, _address = server.accept()
            with connection:
                accepted.append(True)
        except OSError:
            pass

    thread = threading.Thread(target=accept_once)
    thread.start()
    script = (
        "import socket, sys\n"
        "s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
        "try:\n"
        f"    s.connect(('127.0.0.1', {port}))\n"
        "except PermissionError as error:\n"
        "    print('denied:' + str(error)); sys.exit(0)\n"
        "print('connected'); sys.exit(3)\n"
    )
    result = ContainedProcessRunner().run(
        _plan(tmp_path, (sys.executable, "-c", script), NetworkMode.NONE),
        _context(tmp_path, NoEgressNetworkContainment(tmp_path)),
    )
    thread.join(timeout=2)
    server.close()
    assert result.termination.kind is TerminationKind.EXITED
    assert result.termination.exit_code == 0
    assert accepted == []
    stdout = (tmp_path / str(result.stdout_ref)).read_text(encoding="utf-8")
    assert stdout.startswith("denied:")
    observations = (tmp_path / str(result.network_observation_ref)).read_text(encoding="utf-8")
    attempts = [
        json.loads(line)
        for line in observations.splitlines()
        if json.loads(line)["kind"] == "network_attempt"
    ]
    assert attempts and all(item["disposition"] == "denied" for item in attempts)


def test_unguardable_command_is_blocked_before_launch(tmp_path: Path) -> None:
    plan = _plan(tmp_path, ("node", "-e", "0"), NetworkMode.NONE)
    with pytest.raises(ProcessRunBlocked):
        ContainedProcessRunner().run(
            plan, _context(tmp_path, NoEgressNetworkContainment(tmp_path))
        )


def _mirror_fixture(root: Path) -> Path:
    mirror = root / "mirror"
    (mirror / "migrations").mkdir(parents=True)
    (mirror / "migrations/0004_index_layer.sql").write_text("-- schema", encoding="utf-8")
    return mirror


def test_a_second_phase_auditor_on_the_same_run_tree_stays_available(tmp_path: Path) -> None:
    """Regression: two phases audit one run tree, so their evidence roots must differ.

    Sharing the default root made the second auditor unavailable, which blocked every
    admitted native scope for a reason that had nothing to do with the host.
    """
    first = ObservedWriteAuditor(tmp_path)
    second = ObservedWriteAuditor(tmp_path, observation_name="write-audit-native")
    assert first.available is True
    assert second.available is True
    assert ObservedWriteAuditor(tmp_path).available is False


def test_admitted_scopes_execute_when_containment_and_auditing_are_available(
    tmp_path: Path,
) -> None:
    mirror = _mirror_fixture(tmp_path)
    output = tmp_path / "output"
    output.mkdir()
    ObservedWriteAuditor(tmp_path)  # occupy the mirror-execution phase's evidence root
    execute_native_integration(mirror, tmp_path, output, interpreter=sys.executable)
    payload = json.loads((output / "native-integration.json").read_text(encoding="utf-8"))
    admitted = [
        item for item in payload["scopes"] if item["prerequisites_available"] is True
    ]
    assert admitted, "the fixture host must admit at least one scope"
    assert all(item["execution_attempted"] is True for item in admitted), [
        (item["scope"], item["blockers"]) for item in admitted
    ]


def test_phase_covers_every_scope_exactly_once_without_scoped_behavior(
    tmp_path: Path,
) -> None:
    mirror = _mirror_fixture(tmp_path)
    output = tmp_path / "output"
    output.mkdir()
    result = execute_native_integration(mirror, tmp_path, output, interpreter="")
    assert result.gate is GateStatus.GREEN
    payload = json.loads((output / "native-integration.json").read_text(encoding="utf-8"))
    scopes = [item["scope"] for item in payload["scopes"]]
    assert sorted(scopes) == sorted(scope.value for scope in HardwareScope)
    assert len(scopes) == len(set(scopes)) == len(NATIVE_CHECK_IDS)
    assert payload["preflights_completed_before_scoped_behavior"] is True
    assert payload["audio_persisted"] is False
    assert payload["downloads_performed"] == 0
    assert payload["permission_or_firewall_changes"] == 0
    assert payload["pre_existing_processes_touched"] == 0
    for record in payload["scopes"]:
        assert record["preflight"], record["scope"]
        assert all(
            item["scoped_behavior_executed"] is False for item in record["preflight"]
        )
        assert record["safety"]["persist_audio"] is False
        assert record["safety"]["synthetic_non_private_only"] is True


def test_blocked_prerequisites_never_become_product_failures(tmp_path: Path) -> None:
    mirror = _mirror_fixture(tmp_path)
    output = tmp_path / "output"
    output.mkdir()
    execute_native_integration(mirror, tmp_path, output, interpreter="")
    payload = json.loads((output / "native-integration.json").read_text(encoding="utf-8"))
    blocked = [
        item for item in payload["scopes"] if item["prerequisites_available"] is False
    ]
    assert blocked, "the fixture host must block at least one scope"
    for record in blocked:
        assert record["status"] == AssessmentStatus.ENVIRONMENT_BLOCKED.value
        assert record["execution_attempted"] is False
        assert record["malfunction_observed"] is False
        assert record["blockers"]
    # Only a procedure that genuinely started may ever be called a product failure.
    for record in payload["scopes"]:
        if record["malfunction_observed"]:
            assert record["execution_attempted"] is True
    for scope in payload["product_failure_scopes"]:
        matching = next(item for item in payload["scopes"] if item["scope"] == scope)
        assert matching["execution_attempted"] is True


def test_unlaunchable_interpreter_is_blocked_not_called_a_product_failure(
    tmp_path: Path,
) -> None:
    mirror = _mirror_fixture(tmp_path)
    output = tmp_path / "output"
    output.mkdir()
    absent = tmp_path / "absent-python.exe"
    execute_native_integration(mirror, tmp_path, output, interpreter=str(absent))
    payload = json.loads((output / "native-integration.json").read_text(encoding="utf-8"))
    admitted = [
        item for item in payload["scopes"] if item["prerequisites_available"] is True
    ]
    assert admitted, "the fixture host must admit at least one scope"
    for record in admitted:
        assert record["execution_attempted"] is False
        assert record["malfunction_observed"] is False
        assert record["status"] == AssessmentStatus.UNVERIFIED.value
        assert record["blockers"]
    assert payload["product_failure_scopes"] == []
