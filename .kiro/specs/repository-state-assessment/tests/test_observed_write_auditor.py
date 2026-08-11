"""Boundary tests for the production observed-write auditor."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import pytest
from assessor.contained_process_protocols import NetworkContainmentLease
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
from assessor.observed_write_auditor import ObservedWriteAuditor
from assessor.write_admission import WriteAdmissionDecision


class _NetworkContainment:
    """Pre-established test containment used to isolate write-audit preflight."""

    def __init__(self) -> None:
        self.establish_calls = 0

    def establish(self, _plan: CheckPlan, _token: str) -> NetworkContainmentLease:
        self.establish_calls += 1
        return NetworkContainmentLease(True, "network/synthetic.json")

    def release(self, _lease: NetworkContainmentLease) -> None:
        return None


def _plan(
    root: Path,
    designated: Path,
    argv: tuple[str, ...] | None = None,
    network_mode: NetworkMode = NetworkMode.NONE,
) -> CheckPlan:
    mirror = root / "mirror"
    mirror.mkdir(parents=True, exist_ok=True)
    designated.mkdir(parents=True, exist_ok=True)
    return CheckPlan(
        check_id="write-audit",
        plane=VerificationPlane.PYTHON_ENGINE,
        scope="synthetic write audit",
        command_source=None,
        exact_argv=ExactArgumentVector(argv or (sys.executable, "-c", "pass")),
        numbered_procedure=None,
        cwd=str(mirror),
        prerequisites=(),
        applicability=Applicability.APPLICABLE,
        applicability_basis="synthetic fixture",
        timeout_ms=3_000,
        write_policy=WritePolicy((str(designated),)),
        network_policy=NetworkPolicy(network_mode),
        external_dependency=False,
        dependent_check_ids=(),
        cleanup_procedure=("terminate owned process tree",),
    )


def _audit_payload(root: Path, reference: str) -> object:
    return json.loads((root / reference).read_text(encoding="utf-8"))


def test_safe_write_records_created_path_and_correct_hash(tmp_path: Path) -> None:
    """A created file inside the designated root is compliant and content-addressed."""
    root = tmp_path / "run"
    designated = root / "outputs"
    plan = _plan(root, designated)
    auditor = ObservedWriteAuditor(root)
    assert auditor.available is True
    handle = auditor.start(plan, "safe-write")
    written = designated / "result.txt"
    written.write_bytes(b"synthetic result\n")
    outcome = auditor.finish(handle)
    assert outcome.compliant is True
    assert outcome.audit_ref is not None
    payload = _audit_payload(root, outcome.audit_ref)
    assert isinstance(payload, dict)
    assert payload["compliant"] is True
    assert payload["changes"] == [
        {
            "after_sha256": hashlib.sha256(b"synthetic result\n").hexdigest(),
            "before_sha256": None,
            "disposition": "created",
            "inside_designated_roots": True,
            "path": "outputs/result.txt",
        }
    ]


def test_write_outside_designated_root_is_audit_failure(tmp_path: Path) -> None:
    """A mirror write is observed but classified outside the allowed write roots."""
    root = tmp_path / "run"
    designated = root / "outputs"
    plan = _plan(root, designated)
    auditor = ObservedWriteAuditor(root)
    handle = auditor.start(plan, "outside-write")
    escaped = root / "mirror" / "escaped.txt"
    escaped.write_text("outside", encoding="utf-8")
    outcome = auditor.finish(handle)
    assert outcome.compliant is False
    assert outcome.audit_ref is not None
    payload = _audit_payload(root, outcome.audit_ref)
    assert isinstance(payload, dict)
    assert payload["outside_designated_roots"] == ["mirror/escaped.txt"]
    changes = payload["changes"]
    assert isinstance(changes, list) and len(changes) == 1
    change = changes[0]
    assert isinstance(change, dict)
    assert change["inside_designated_roots"] is False
    assert change["after_sha256"] == hashlib.sha256(b"outside").hexdigest()


def test_runner_uses_production_auditor_without_counting_assessor_artifacts(
    tmp_path: Path,
) -> None:
    """Raw output and proof files are excluded only at their exact lease-owned paths."""
    root = tmp_path / "run"
    designated = root / "outputs"
    marker = designated / "result.txt"
    script = f"from pathlib import Path; Path({str(marker)!r}).write_text('safe')"
    plan = _plan(
        root,
        designated,
        (sys.executable, "-c", script),
        NetworkMode.LOOPBACK_ONLY,
    )
    auditor = ObservedWriteAuditor(root)
    context = RunnerContext(
        temporary_root=root,
        mirror_root=root / "mirror",
        safe_parent_environment={
            name: os.environ.get(name, "")
            for name in ("PATH", "PATHEXT", "SYSTEMROOT", "WINDIR")
        },
        write_admission=WriteAdmissionDecision(True, None),
        write_auditor=auditor,
        network_containment=LoopbackOnlyNetworkContainment(root),
    )
    result = ContainedProcessRunner(poll_interval_seconds=0.005).run(plan, context)
    assert result.termination.kind is TerminationKind.EXITED
    assert result.termination.exit_code == 0
    assert result.write_audit_ref is not None
    payload = _audit_payload(root, result.write_audit_ref)
    assert isinstance(payload, dict)
    changes = payload["changes"]
    assert isinstance(changes, list)
    paths = [item["path"] for item in changes if isinstance(item, dict)]
    assert paths == ["outputs/result.txt"]
    assert payload["outside_designated_roots"] == []


def test_unavailable_auditing_blocks_before_network_or_process_launch(
    tmp_path: Path,
) -> None:
    """An unusable observation root makes auditing unavailable and blocks pre-launch."""
    root = tmp_path / "run"
    designated = root / "outputs"
    plan = _plan(root, designated)
    (root / "write-audit").write_text("collision", encoding="utf-8")
    auditor = ObservedWriteAuditor(root)
    network = _NetworkContainment()
    marker = designated / "must-not-run"
    script = f"from pathlib import Path; Path({str(marker)!r}).write_text('bad')"
    plan = _plan(root, designated, (sys.executable, "-c", script))
    context = RunnerContext(
        temporary_root=root,
        mirror_root=root / "mirror",
        safe_parent_environment={
            name: os.environ.get(name, "")
            for name in ("PATH", "PATHEXT", "SYSTEMROOT", "WINDIR")
        },
        write_admission=WriteAdmissionDecision(True, None),
        write_auditor=auditor,
        network_containment=network,
    )
    assert auditor.available is False
    with pytest.raises(ProcessRunBlocked, match="write auditing is unavailable"):
        ContainedProcessRunner().run(plan, context)
    assert network.establish_calls == 0
    assert not marker.exists()
