"""Task 11.2 orchestration smoke tests for Requirements 1.5–1.9, 3.1,
3.13, 4.10, 7.2, and 9.14.
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

import pytest

from assessor.assessment_cli import main
from assessor.assessment_phase_gates import (
    AssessmentPhase,
    ExecutionAdmission,
    GateStatus,
    PhaseExecutionResult,
)
from assessor.assessment_pipeline import AssessmentPipeline, PhaseAction
from assessor.contained_process_runner import ContainedProcessRunner, ProcessRunBlocked
from assessor.execution_models import Applicability, Prerequisite, TerminationKind
from assessor.model_types import NetworkMode, WritePolicy, ZonedTimestamp
from assessor.preservation import PlannedOperation, PlannedWrite
from assessor.run_manifest_append_store import AppendOnlyRunManifest
from assessor.run_models import WorkspaceComparison
from assessor.status_decision import StatusDecisionFacts, decide_status
from assessor.write_admission import WriteAdmissionRequest, evaluate_write_admission
from test_contained_runner_containment import (
    _SocketGuardContainment,
    _artifact,
    _context,
    _plan,
)

_NOW = ZonedTimestamp(datetime(2026, 7, 31, tzinfo=timezone.utc))
_ADMISSION = ExecutionAdmission(True, True, True, True, True)


@dataclass
class _ForbiddenSpies:
    forbidden_commands: list[tuple[str, ...]] = field(default_factory=list)
    provider_connections: list[object] = field(default_factory=list)
    production_repairs: list[tuple[object, ...]] = field(default_factory=list)
    all_commands: list[tuple[str, ...]] = field(default_factory=list)


def _comparison(preserved: bool = True, suffix: str = "final") -> WorkspaceComparison:
    return WorkspaceComparison(
        "baseline/source.json", f"final/{suffix}.json", preserved, preserved,
        preserved, (), (), _NOW,
    )


def _argv(root: Path, manifest: Path, run_id: str = "run-雪") -> list[str]:
    return [
        "run", "--manifest", str(manifest), "--run-id", run_id,
        "--source-root", str(root / "source repository 雪"),
        "--temporary-root", str(root / "temporary artifacts 雪"),
        "--output-root", str(root / "permanent artifacts 雪"),
        "--ownership-token", f"owned-{run_id}",
    ]


def _green_actions(
    calls: list[AssessmentPhase], output: Path,
) -> tuple[PhaseAction, ...]:
    actions = []
    for phase in AssessmentPhase:
        def execute(_context, selected=phase):
            calls.append(selected)
            artifact = output / f"{selected.name.lower()}.json"
            artifact.write_bytes((selected.value + "\n").encode("utf-8"))
            return PhaseExecutionResult(
                GateStatus.GREEN, (str(artifact),), None,
                execution_admission=(
                    _ADMISSION if selected is AssessmentPhase.DISCOVERY_ADMISSION else None
                ),
            )
        actions.append(PhaseAction(phase, (), execute))
    return tuple(actions)


def _builder(actions, compare=lambda: _comparison(), cleanup=None):
    def build(_request, store):
        kwargs = {} if cleanup is None else {"cleanup": cleanup}
        return AssessmentPipeline(store, tuple(actions), compare, **kwargs)
    return build


def _install_forbidden_spies(monkeypatch: pytest.MonkeyPatch) -> _ForbiddenSpies:
    spies = _ForbiddenSpies()
    original_popen = subprocess.Popen

    def popen(argv, *args, **kwargs):
        command = tuple(str(item) for item in argv)
        spies.all_commands.append(command)
        lowered = tuple(item.casefold() for item in command)
        dependency = any(item in {"install", "sync"} for item in lowered)
        dangerous_git = bool(lowered and Path(lowered[0]).name == "git" and any(
            item in {"commit", "push", "reset", "restore", "checkout"}
            for item in lowered[1:]
        ))
        if dependency or dangerous_git:
            spies.forbidden_commands.append(command)
            raise AssertionError(f"forbidden command invoked: {command}")
        return original_popen(argv, *args, **kwargs)

    def forbidden_run(*args, **_kwargs):
        command = tuple(str(item) for item in (args[0] if args else ()))
        spies.forbidden_commands.append(command)
        raise AssertionError(f"forbidden command seam invoked: {command}")

    def provider_connect(*args, **_kwargs):
        spies.provider_connections.append(args)
        raise AssertionError("real provider/network seam invoked")

    def repair(*args, **_kwargs):
        spies.production_repairs.append(args)
        raise AssertionError("production repair seam invoked")

    monkeypatch.setattr(subprocess, "Popen", popen)
    monkeypatch.setattr(subprocess, "run", forbidden_run)
    monkeypatch.setattr(socket, "create_connection", provider_connect)
    monkeypatch.setattr(socket.socket, "connect", provider_connect)
    monkeypatch.setattr(shutil, "copy2", repair)
    monkeypatch.setattr(shutil, "copyfile", repair)
    monkeypatch.setattr(shutil, "copytree", repair)
    return spies


def test_cli_stops_at_flipped_gate_with_complete_safety_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A late red gate stops the CLI after omission, egress, and blocker evidence."""
    root = tmp_path / "orchestration fixture with spaces Ω"
    source = root / "source repository 雪"
    temporary = root / "temporary artifacts 雪"
    output = root / "permanent artifacts 雪"
    for directory in (source, temporary, output):
        directory.mkdir(parents=True)
    tracked = source / "tracked payload.bin"
    untracked = source / "untracked nested 雪" / "note Ω.txt"
    untracked.parent.mkdir()
    tracked.write_bytes(b"tracked\x00bytes\xff")
    untracked.write_bytes("untracked—雪\n".encode())
    before = {tracked: tracked.read_bytes(), untracked: untracked.read_bytes()}
    before_hashes = {path: sha256(data).hexdigest() for path, data in before.items()}
    calls: list[AssessmentPhase] = []
    observations: dict[str, object] = {}
    spies = _install_forbidden_spies(monkeypatch)
    actions = list(_green_actions(calls, output))

    def mirror(_phase_context):
        calls.append(AssessmentPhase.MIRROR_EXECUTION)
        operation = PlannedOperation(
            "unsafe-write", ("synthetic-check",), True,
            (PlannedWrite(str(tracked), b"must-not-land"),),
            ("dependent-a", "dependent-b"),
        )
        decision = evaluate_write_admission(WriteAdmissionRequest(
            operation, WritePolicy((str(output),)), True, True, (str(tracked),)
        ))
        assert not decision.admitted and decision.omission is not None
        omission = decision.omission
        observations["omission"] = omission

        missing = "definitely-missing-assessor-tool.exe"
        blocked_plan = _plan(
            temporary, (missing, "--version"),
            prerequisites=(Prerequisite(missing, ("where", missing), False, "preflight.json"),),
        )
        commands_before = len(spies.all_commands)
        with pytest.raises(ProcessRunBlocked, match="named prerequisites unavailable"):
            ContainedProcessRunner().run(blocked_plan, _context(temporary))
        assert len(spies.all_commands) == commands_before
        status = decide_status(StatusDecisionFacts(
            Applicability.APPLICABLE, False, None, (missing,), False, False,
            False, (), False, False, False, True,
        ))
        observations["blocked"] = status

        script = """exec(open('sitecustomize.py', encoding='utf-8').read(), {})
import socket
try: socket.socket().connect(('203.0.113.9', 443))
except PermissionError: print('denied-before-connect')
else: raise SystemExit(91)
"""
        plan = _plan(
            temporary, (sys.executable, "-c", script),
            network_mode=NetworkMode.LOOPBACK_ONLY,
        )
        network = _SocketGuardContainment(temporary / "integration space 雪" / "run")
        result = ContainedProcessRunner().run(plan, _context(temporary, network))
        observations["egress"] = json.loads(
            _artifact(temporary, result.network_observation_ref).read_text(encoding="utf-8")
        )
        assert result.termination.kind is TerminationKind.EXITED
        evidence = output / "mirror-safety.json"
        evidence.write_text("omitted, blocked, denied\n", encoding="utf-8")
        return PhaseExecutionResult(GateStatus.GREEN, (str(evidence),), None)

    def flip_red(_context):
        calls.append(AssessmentPhase.PARITY)
        return PhaseExecutionResult(GateStatus.FAILED, (), "parity gate flipped red Ω")

    phases = tuple(AssessmentPhase)
    actions[phases.index(AssessmentPhase.MIRROR_EXECUTION)] = PhaseAction(
        AssessmentPhase.MIRROR_EXECUTION, (), mirror
    )
    actions[phases.index(AssessmentPhase.PARITY)] = PhaseAction(
        AssessmentPhase.PARITY, (), flip_red
    )
    manifest = output / "run-manifest.jsonl"
    code = main(_argv(root, manifest), _builder(actions))

    assert code == 2
    state = AppendOnlyRunManifest.open(manifest, clock=lambda: _NOW).state()
    assert calls == list(phases[: phases.index(AssessmentPhase.PARITY) + 1]), tuple(
        (record.event.value, record.reason) for record in state.records if record.reason
    )
    assert state.gate_for(AssessmentPhase.PARITY) is GateStatus.FAILED
    assert state.gate_for(AssessmentPhase.REPORT) is None
    partial = Path(next(r.artifact_refs[0] for r in state.records if r.event.value == "partial_report"))
    text = partial.read_text(encoding="utf-8")
    assert "Status: PARTIAL" in text and "| report | not reached |" in text
    omission = observations["omission"]
    assert tuple(item.path for item in omission.affected_content) == (str(tracked),)
    assert tuple(item.check_id for item in omission.dependent_checks) == (
        "dependent-a", "dependent-b",
    )
    blocked = observations["blocked"]
    assert blocked.primary_status.value == "Environment_Blocked"
    assert blocked.counts_as_product_failure is False
    assert observations["egress"] == {
        "host": "203.0.113.9", "loopback": False, "disposition": "denied",
    }
    assert spies.forbidden_commands == spies.provider_connections == spies.production_repairs == []
    assert {path: path.read_bytes() for path in before} == before
    assert {path: sha256(path.read_bytes()).hexdigest() for path in before} == before_hashes
