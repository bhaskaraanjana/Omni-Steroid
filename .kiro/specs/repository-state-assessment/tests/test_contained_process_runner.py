"""Contained process runner examples for exact launch and fail-closed cleanup.

**Validates: Requirements 3.1, 3.13-3.15, 3.17, 4.4, 4.7, 4.8, 4.10, 7.1, 7.2**
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import psutil
import pytest
from assessor.contained_process_runner import (
    ContainedProcessRunner,
    NetworkContainmentLease,
    ProcessRunBlocked,
    RunnerContext,
    WriteAuditOutcome,
)
from assessor.execution_models import Applicability, CheckPlan
from assessor.model_types import (
    ExactArgumentVector,
    NetworkMode,
    NetworkPolicy,
    VerificationPlane,
    WritePolicy,
)
from assessor.preservation import OmissionEvidence
from assessor.write_admission import WriteAdmissionDecision


class _NetworkContainment:
    def __init__(self, enforced: bool = True) -> None:
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

    def start(self, _plan: CheckPlan, _token: str) -> object:
        return object()

    def finish(self, _handle: object) -> WriteAuditOutcome:
        return WriteAuditOutcome(True, "writes/audit.json")


def _plan(tmp_path: Path, argv: tuple[str, ...], timeout_ms: int = 3_000) -> CheckPlan:
    mirror = tmp_path / "run" / "mirror"
    output = tmp_path / "run" / "outputs"
    mirror.mkdir(parents=True, exist_ok=True)
    output.mkdir(exist_ok=True)
    return CheckPlan(
        check_id="fixture-command",
        plane=VerificationPlane.PYTHON_ENGINE,
        scope="contained fixture command",
        command_source=None,
        exact_argv=ExactArgumentVector(argv),
        numbered_procedure=None,
        cwd=str(mirror),
        prerequisites=(),
        applicability=Applicability.APPLICABLE,
        applicability_basis="fixture",
        timeout_ms=timeout_ms,
        write_policy=WritePolicy((str(output),)),
        network_policy=NetworkPolicy(NetworkMode.NONE),
        external_dependency=False,
        dependent_check_ids=(),
        cleanup_procedure=("terminate matching owned process tree",),
    )


def _context(tmp_path: Path, network: _NetworkContainment) -> RunnerContext:
    run_root = tmp_path / "run"
    return RunnerContext(
        temporary_root=run_root,
        mirror_root=run_root / "mirror",
        safe_parent_environment={
            "PATH": os.environ.get("PATH", ""),
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
            "PROVIDER_API_KEY": "must-not-be-inherited",
            "UNRELATED": "must-not-be-inherited",
        },
        write_admission=WriteAdmissionDecision(True, None),
        write_auditor=_WriteAuditor(),
        network_containment=network,
    )


def test_runs_exact_argv_once_with_quarantined_output_and_safe_environment(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "run" / "outputs" / "launch-count.txt"
    script = (
        "import json, os, pathlib; "
        "p=pathlib.Path(__import__('sys').argv[1]); "
        "p.write_text((p.read_text() if p.exists() else '') + 'x'); "
        "print(json.dumps({'cwd': os.getcwd(), 'secret': os.getenv('PROVIDER_API_KEY'), "
        "'unrelated': os.getenv('UNRELATED'), 'temp': os.environ['TEMP'], "
        "'uv': os.environ['UV_CACHE_DIR'], 'cargo': os.environ['CARGO_TARGET_DIR']}))"
    )
    argv = (sys.executable, "-c", script, str(marker))
    plan = _plan(tmp_path, argv)
    network = _NetworkContainment()

    result = ContainedProcessRunner().run(plan, _context(tmp_path, network))

    assert result.exact_argv == ExactArgumentVector(argv)
    assert result.cwd == plan.cwd
    assert result.termination.exit_code == 0
    assert marker.read_text() == "x"
    assert result.process_ownership.cleanup_completed
    assert network.establish_calls == network.release_calls == 1
    stdout = tmp_path / "run" / result.stdout_ref
    payload = json.loads(stdout.read_text(encoding="utf-8"))
    assert payload["cwd"] == str(Path(plan.cwd).resolve())
    assert payload["secret"] is None and payload["unrelated"] is None
    for key in ("temp", "uv", "cargo"):
        assert Path(payload[key]).resolve().is_relative_to((tmp_path / "run").resolve())


@pytest.mark.parametrize(
    "argv",
    [
        ("pnpm", "run", "dev"),
        ("pnpm", "dev"),
        ("vitest", "--watch"),
        ("uvicorn", "engine.server:app", "--reload"),
    ],
)
def test_watch_and_development_server_modes_are_blocked_before_launch(
    tmp_path: Path, argv: tuple[str, ...]
) -> None:
    network = _NetworkContainment()
    with pytest.raises(ProcessRunBlocked, match="non-terminating"):
        ContainedProcessRunner().run(_plan(tmp_path, argv), _context(tmp_path, network))
    assert network.establish_calls == 0


def test_unenforced_network_containment_blocks_before_launch(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "run" / "outputs" / "must-not-exist"
    plan = _plan(
        tmp_path,
        (
            sys.executable,
            "-c",
            "open(__import__('sys').argv[1], 'w').close()",
            str(marker),
        ),
    )
    network = _NetworkContainment(enforced=False)
    with pytest.raises(ProcessRunBlocked, match="network containment"):
        ContainedProcessRunner().run(plan, _context(tmp_path, network))
    assert not marker.exists()


def test_timeout_cleans_owned_descendants_and_preserves_preexisting_process(
    tmp_path: Path,
) -> None:
    sentinel = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    child_pid = None
    try:
        script = (
            "import subprocess, sys, time; "
            "p=subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
            "print(p.pid, flush=True); time.sleep(30)"
        )
        plan = _plan(tmp_path, (sys.executable, "-c", script), timeout_ms=800)
        result = ContainedProcessRunner(poll_interval_seconds=0.02).run(
            plan, _context(tmp_path, _NetworkContainment())
        )
        stdout = tmp_path / "run" / result.stdout_ref
        child_pid = int(stdout.read_text(encoding="utf-8").strip())
        assert result.termination.kind.value == "timed_out"
        assert result.process_ownership.cleanup_completed
        assert len(result.process_ownership.processes) >= 2
        assert not psutil.pid_exists(child_pid)
        assert sentinel.poll() is None
    finally:
        sentinel.terminate()
        sentinel.wait(timeout=5)
        if child_pid is not None and psutil.pid_exists(child_pid):
            psutil.Process(child_pid).kill()


def test_denied_write_admission_blocks_before_network_or_process_launch(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "run" / "outputs" / "must-not-launch"
    argv = (sys.executable, "-c", "open(__import__('sys').argv[1], 'w').close()", str(marker))
    plan = _plan(tmp_path, argv)
    network = _NetworkContainment()
    context = replace(
        _context(tmp_path, network),
        write_admission=WriteAdmissionDecision(
            False,
            OmissionEvidence(
                operation_id=plan.check_id,
                command_or_procedure=argv,
                affected_content=(),
                reason="planned write escaped designated roots",
                dependent_checks=(),
            ),
        ),
    )

    with pytest.raises(ProcessRunBlocked, match="escaped designated roots"):
        ContainedProcessRunner().run(plan, context)

    assert network.establish_calls == 0
    assert not marker.exists()
