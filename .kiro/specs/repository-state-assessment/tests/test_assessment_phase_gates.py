"""Boundary tests for hard phase gates, resume, cancellation, and partial reports."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from assessor.assessment_phase_gates import (
    AssessmentPhase,
    ExecutionAdmission,
    GateStatus,
    PhaseExecutionResult,
)
from assessor.assessment_pipeline import (
    AssessmentPipeline,
    PhaseAction,
    PipelineOptions,
)
from assessor.model_types import OwnedProcess, ProcessOwnership, ZonedTimestamp
from assessor.process_cleanup import CleanupMode
from assessor.run_manifest_append_store import AppendOnlyRunManifest, CheckState, RunIdentity
from assessor.run_models import WorkspaceComparison

_NOW = ZonedTimestamp(datetime(2026, 7, 31, tzinfo=timezone.utc))

_ADMISSION = ExecutionAdmission(True, True, True, True, True)


def _comparison() -> WorkspaceComparison:
    return WorkspaceComparison("baseline.json", "final.json", True, True, True, (), (), _NOW)


def _store(tmp_path: Path) -> AppendOnlyRunManifest:
    return AppendOnlyRunManifest.create(
        tmp_path / "manifest.jsonl",
        RunIdentity(
            "run-1",
            str(tmp_path / "source"),
            str(tmp_path / "temp"),
            str(tmp_path / "out"),
            "owned-token",
        ),
        clock=lambda: _NOW,
    )


def _actions(
    call_log: list[AssessmentPhase], failure: AssessmentPhase | None = None
) -> tuple[PhaseAction, ...]:
    actions: list[PhaseAction] = []
    for phase in AssessmentPhase:

        def execute(_context, selected=phase):
            call_log.append(selected)
            if selected is failure:
                return PhaseExecutionResult(GateStatus.FAILED, (), "synthetic gate failure")
            return PhaseExecutionResult(
                GateStatus.GREEN,
                (f"{selected.value}.json",),
                None,
                execution_admission=(
                    _ADMISSION if selected is AssessmentPhase.DISCOVERY_ADMISSION else None
                ),
            )

        actions.append(PhaseAction(phase, (), execute))
    return tuple(actions)


def test_failed_gate_blocks_every_later_phase_and_emits_visibly_partial_report(
    tmp_path: Path,
) -> None:
    calls: list[AssessmentPhase] = []
    store = _store(tmp_path)
    result = AssessmentPipeline(store, _actions(calls, AssessmentPhase.CLAIMS), _comparison).run()

    assert calls == [AssessmentPhase.BASELINE, AssessmentPhase.CLAIMS]
    assert result.partial is True
    assert result.termination_reason == "synthetic gate failure"
    assert result.reached_phases == (AssessmentPhase.BASELINE,)
    text = Path(result.partial_report_ref).read_text(encoding="utf-8")
    assert text.startswith("# PARTIAL Repository State Assessment\n\nStatus: PARTIAL\n")
    assert "| claims | failed |" in text
    assert "| discovery/admission | not reached |" in text
    assert store.state().gate_for(AssessmentPhase.DISCOVERY_ADMISSION) is None


def test_resume_skips_green_phases_reconstructed_only_from_manifest(tmp_path: Path) -> None:
    calls: list[AssessmentPhase] = []
    store = _store(tmp_path)
    first = AssessmentPipeline(store, _actions(calls), _comparison).run(
        PipelineOptions(phase_limit=AssessmentPhase.CLAIMS)
    )
    assert first.partial is True
    assert calls == [AssessmentPhase.BASELINE, AssessmentPhase.CLAIMS]

    calls.clear()
    reopened = AppendOnlyRunManifest.open(store.path, clock=lambda: _NOW)
    second = AssessmentPipeline(reopened, _actions(calls), _comparison).run()

    assert calls == list(AssessmentPhase)[2:]
    assert second.partial is False
    assert second.reached_phases == tuple(AssessmentPhase)
    assert len(reopened.state().final_comparison_records) == 2


def test_keyboard_interrupt_marks_running_check_unverified_and_cleans_only_owned_identity(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    owned = OwnedProcess(321, _NOW, "fixture-worker.exe", None)
    cleanup_calls: list[tuple[str, tuple[OwnedProcess, ...], CleanupMode]] = []

    def interrupt(context):
        context.record_owned_process(owned)
        raise KeyboardInterrupt

    actions = list(_actions([]))
    actions[0] = PhaseAction(AssessmentPhase.BASELINE, ("baseline-check",), interrupt)

    def cleanup(
        token: str, processes: tuple[OwnedProcess, ...], mode: CleanupMode
    ) -> ProcessOwnership:
        cleanup_calls.append((token, processes, mode))
        return ProcessOwnership(token, "fixture", processes, True)

    result = AssessmentPipeline(store, tuple(actions), _comparison, cleanup=cleanup).run()
    state = store.state()

    assert result.partial is True
    assert state.check_state("baseline-check") is CheckState.UNVERIFIED
    assert cleanup_calls == [("owned-token", (owned,), CleanupMode.ABORT)]
    assert state.gate_for(AssessmentPhase.BASELINE) is GateStatus.INCONCLUSIVE


@pytest.mark.parametrize(
    ("raised", "mode"),
    [(TimeoutError(), CleanupMode.TIMEOUT), (RuntimeError("crash"), CleanupMode.FAILURE)],
)
def test_final_comparison_runs_on_timeout_and_crash(
    tmp_path: Path, raised: BaseException, mode: CleanupMode
) -> None:
    store = _store(tmp_path)
    comparisons: list[str] = []
    cleanup_modes: list[CleanupMode] = []

    def fail(_context):
        raise raised

    actions = list(_actions([]))
    actions[0] = PhaseAction(AssessmentPhase.BASELINE, ("check-1",), fail)

    def compare() -> WorkspaceComparison:
        comparisons.append("compared")
        return _comparison()

    def cleanup(
        token: str, processes: tuple[OwnedProcess, ...], selected: CleanupMode
    ) -> ProcessOwnership:
        cleanup_modes.append(selected)
        return ProcessOwnership(token, "fixture", processes, True)

    result = AssessmentPipeline(store, tuple(actions), compare, cleanup=cleanup).run()

    assert result.partial is True
    assert comparisons == ["compared"]
    assert cleanup_modes == [mode]
    assert store.state().check_state("check-1") is CheckState.UNVERIFIED
    assert len(store.state().final_comparison_records) == 1


def test_observation_only_stops_before_process_execution_without_passing_skipped_phases(
    tmp_path: Path,
) -> None:
    calls: list[AssessmentPhase] = []
    store = _store(tmp_path)
    result = AssessmentPipeline(store, _actions(calls), _comparison).run(
        PipelineOptions(observation_only=True)
    )

    assert calls == list(AssessmentPhase)[:3]
    assert result.partial is True
    assert store.state().gate_for(AssessmentPhase.MIRROR_EXECUTION) is None
    assert "| mirror execution | not reached |" in Path(result.partial_report_ref).read_text(
        encoding="utf-8"
    )


def test_cli_exposes_run_resume_phase_limit_and_observation_only(tmp_path: Path) -> None:
    from assessor.assessment_cli import build_argument_parser

    parser = build_argument_parser()
    run = parser.parse_args(
        [
            "run",
            "--manifest",
            str(tmp_path / "manifest.jsonl"),
            "--run-id",
            "run-cli",
            "--source-root",
            "source",
            "--temporary-root",
            "temporary",
            "--output-root",
            "output",
            "--phase-limit",
            "mirror-execution",
            "--observation-only",
        ]
    )
    resume = parser.parse_args(
        ["resume", "--manifest", str(tmp_path / "manifest.jsonl"), "--phase-limit", "parity"]
    )

    assert run.command == "run"
    assert run.phase_limit is AssessmentPhase.MIRROR_EXECUTION
    assert run.observation_only is True
    assert resume.command == "resume"
    assert resume.phase_limit is AssessmentPhase.PARITY
    assert resume.observation_only is False


def test_missing_execution_safety_proof_stops_before_mirror_process_phase(
    tmp_path: Path,
) -> None:
    calls: list[AssessmentPhase] = []
    actions = list(_actions(calls))

    def unsafe_discovery(_context):
        calls.append(AssessmentPhase.DISCOVERY_ADMISSION)
        return PhaseExecutionResult(GateStatus.GREEN, ("discovery.json",), None)

    actions[2] = PhaseAction(AssessmentPhase.DISCOVERY_ADMISSION, (), unsafe_discovery)
    result = AssessmentPipeline(_store(tmp_path), tuple(actions), _comparison).run()

    assert calls == [
        AssessmentPhase.BASELINE,
        AssessmentPhase.CLAIMS,
        AssessmentPhase.DISCOVERY_ADMISSION,
    ]
    assert result.partial is True
    assert "did not establish every execution safety control" in result.termination_reason
