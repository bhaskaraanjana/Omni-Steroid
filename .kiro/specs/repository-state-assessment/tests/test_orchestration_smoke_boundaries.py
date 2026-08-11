"""Task 11.2 termination, preservation, cleanup, and report smoke tests.

Validates Requirements 1.5–1.9, 3.1, 3.13, 4.10, 7.2, and 9.14.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import IO, Any

import pytest

from assessor.assessment_cli import main
from assessor.assessment_phase_gates import (
    AssessmentPhase,
    GateStatus,
    PhaseExecutionResult,
)
from assessor.assessment_pipeline import PhaseAction
from assessor.model_types import OwnedProcess, ProcessOwnership, ZonedTimestamp
from assessor.preservation import AssessmentTermination
from assessor.process_cleanup import CleanupMode
from assessor.report_admission import admit_assessment_report
from assessor.run_manifest_append_store import AppendOnlyRunManifest
from test_orchestration_smoke import (
    _argv,
    _builder,
    _comparison,
    _green_actions,
    _install_forbidden_spies,
)
from test_report_synthesis import _report

_NOW = ZonedTimestamp(datetime(2026, 7, 31, tzinfo=timezone.utc))


def _roots(tmp_path: Path, name: str) -> tuple[Path, Path, Path, Path]:
    root = tmp_path / name
    source = root / "source repository 雪"
    temporary = root / "temporary artifacts 雪"
    output = root / "permanent artifacts 雪"
    for directory in (source, temporary, output):
        directory.mkdir(parents=True)
    return root, source, temporary, output


def test_source_manifest_mismatch_stops_without_repair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale source baseline blocks phase one and never restores fixture bytes."""
    root, source, _temporary, output = _roots(tmp_path, "source mismatch Ω")
    target = source / "tracked Ω.bin"
    baseline = b"baseline\x00payload"
    externally_changed = b"outside actor changed this\xff"
    target.write_bytes(baseline)
    baseline_hash = sha256(baseline).hexdigest()
    target.write_bytes(externally_changed)
    changed_hash = sha256(externally_changed).hexdigest()
    calls: list[AssessmentPhase] = []
    actions = list(_green_actions(calls, output))
    spies = _install_forbidden_spies(monkeypatch)

    def baseline_gate(_context):
        calls.append(AssessmentPhase.BASELINE)
        observed_hash = sha256(target.read_bytes()).hexdigest()
        if observed_hash != baseline_hash:
            return PhaseExecutionResult(
                GateStatus.FAILED, (),
                f"source manifest mismatch: {observed_hash} != {baseline_hash}",
            )
        raise AssertionError("stale source was incorrectly admitted")

    actions[0] = PhaseAction(AssessmentPhase.BASELINE, (), baseline_gate)
    manifest = output / "manifest.jsonl"
    code = main(_argv(root, manifest), _builder(actions, lambda: _comparison(False, "mismatch")))

    assert code == 2
    assert calls == [AssessmentPhase.BASELINE]
    state = AppendOnlyRunManifest.open(manifest, clock=lambda: _NOW).state()
    assert state.gate_for(AssessmentPhase.BASELINE) is GateStatus.FAILED
    assert all(state.gate_for(phase) is None for phase in tuple(AssessmentPhase)[1:])
    assert state.final_comparison_records[0].comparison_preserved is False
    assert "source manifest mismatch" in (state.gate_record(AssessmentPhase.BASELINE).reason or "")
    assert target.read_bytes() == externally_changed
    assert sha256(target.read_bytes()).hexdigest() == changed_hash
    assert spies.production_repairs == spies.forbidden_commands == spies.provider_connections == []


def test_cleanup_exception_is_visible_and_foreign_process_is_not_selected(tmp_path: Path) -> None:
    """Mid-cleanup failure stays partial while a pre-existing foreign identity survives."""
    root, _source, _temporary, output = _roots(tmp_path, "cleanup failure Ω")
    owned = OwnedProcess(4101, _NOW, "owned-fixture.exe", None)
    foreign = {"pid": 4099, "alive": True, "bytes": b"foreign-process-state"}
    cleanup_inputs: list[tuple[str, tuple[OwnedProcess, ...], CleanupMode]] = []
    actions = list(_green_actions([], output))

    def crash(context):
        context.record_owned_process(owned)
        raise RuntimeError("phase crashed Ω")

    def cleanup(token: str, processes: tuple[OwnedProcess, ...], mode: CleanupMode):
        cleanup_inputs.append((token, processes, mode))
        assert tuple(process.pid for process in processes) == (owned.pid,)
        raise RuntimeError("synthetic teardown failed Ω")

    actions[0] = PhaseAction(AssessmentPhase.BASELINE, ("crashing-check",), crash)
    manifest = output / "manifest.jsonl"
    code = main(_argv(root, manifest, "cleanup-run"), _builder(actions, cleanup=cleanup))

    assert code == 2
    assert cleanup_inputs == [("owned-cleanup-run", (owned,), CleanupMode.FAILURE)]
    assert foreign == {"pid": 4099, "alive": True, "bytes": b"foreign-process-state"}
    state = AppendOnlyRunManifest.open(manifest, clock=lambda: _NOW).state()
    report_record = next(record for record in state.records if record.event.value == "partial_report")
    assert "owned-process cleanup failed: RuntimeError: synthetic teardown failed Ω" in (
        report_record.reason or ""
    )
    assert len(state.final_comparison_records) == 1


@pytest.mark.parametrize(
    ("termination", "raised", "expected_mode", "expected_code"),
    (
        (AssessmentTermination.SUCCESS, None, None, 0),
        (AssessmentTermination.FAILURE, RuntimeError("failure Ω"), CleanupMode.FAILURE, 2),
        (AssessmentTermination.TIMEOUT, TimeoutError("timeout Ω"), CleanupMode.TIMEOUT, 2),
        (AssessmentTermination.ABORT, KeyboardInterrupt(), CleanupMode.ABORT, 2),
    ),
)
def test_cli_records_final_comparison_for_every_termination_in_empty_repository(
    tmp_path: Path,
    termination: AssessmentTermination,
    raised: BaseException | None,
    expected_mode: CleanupMode | None,
    expected_code: int,
) -> None:
    """Success, failure, timeout, and abort each append one exact comparison record."""
    root, source, _temporary, output = _roots(tmp_path, f"empty repo {termination.value} Ω")
    assert tuple(source.iterdir()) == ()
    actions = list(_green_actions([], output))
    cleanup_modes: list[CleanupMode] = []

    if raised is not None:
        def terminate(_context):
            raise raised
        actions[0] = PhaseAction(AssessmentPhase.BASELINE, ("terminal-check",), terminate)

    def cleanup(token: str, processes: tuple[OwnedProcess, ...], mode: CleanupMode):
        cleanup_modes.append(mode)
        return ProcessOwnership(token, "synthetic", processes, True)

    manifest = output / "manifest.jsonl"
    code = main(
        _argv(root, manifest, f"term-{termination.value}"),
        _builder(actions, lambda: _comparison(True, termination.value), cleanup),
    )

    assert code == expected_code
    state = AppendOnlyRunManifest.open(manifest, clock=lambda: _NOW).state()
    records = state.final_comparison_records
    assert len(records) == 1
    assert records[0].reason == f"{termination.value} termination source comparison"
    assert records[0].comparison_preserved is True
    assert cleanup_modes == ([] if expected_mode is None else [expected_mode])


def test_success_artifacts_are_exactly_contained_and_source_hashes_are_stable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The CLI writes only enumerated owned artifacts and preserves Unicode fixture bytes."""
    root, source, temporary, output = _roots(tmp_path, "artifact containment Ω")
    tracked = source / "tracked file.bin"
    nested = source / "untracked nested 雪" / "raw note.txt"
    nested.parent.mkdir()
    expected_source = {
        tracked: b"tracked\x00\xffbytes",
        nested: "untracked note—雪\n".encode("utf-8"),
    }
    for path, content in expected_source.items():
        path.write_bytes(content)
    source_hashes = {path: sha256(content).hexdigest() for path, content in expected_source.items()}
    actions = list(_green_actions([], output))
    original_baseline = actions[0].execute

    def baseline(context):
        (temporary / "bounded scratch Ω.tmp").write_bytes(b"temporary-only\x00")
        return original_baseline(context)

    actions[0] = PhaseAction(AssessmentPhase.BASELINE, (), baseline)
    manifest = output / "manifest.jsonl"
    write_paths: set[Path] = set()
    original_open = Path.open

    def observed_open(self: Path, mode: str = "r", *args: Any, **kwargs: Any) -> IO[Any]:
        if any(flag in mode for flag in "wax+"):
            write_paths.add(self.resolve())
        return original_open(self, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", observed_open)

    def compare():
        preserved = all(path.read_bytes() == content for path, content in expected_source.items())
        return _comparison(preserved, "contained")

    assert main(_argv(root, manifest, "contained-run"), _builder(actions, compare)) == 0
    expected_artifacts = {
        manifest.resolve(),
        (temporary / "bounded scratch Ω.tmp").resolve(),
        *((output / f"{phase.name.lower()}.json").resolve() for phase in AssessmentPhase),
    }
    assert write_paths == expected_artifacts
    assert all(
        path.is_relative_to(temporary.resolve()) or path.is_relative_to(output.resolve())
        for path in write_paths
    )
    assert {path: path.read_bytes() for path in expected_source} == expected_source
    assert {
        path: sha256(path.read_bytes()).hexdigest() for path in expected_source
    } == source_hashes
    for phase in AssessmentPhase:
        artifact = output / f"{phase.name.lower()}.json"
        expected = (phase.value + "\n").encode("utf-8")
        assert artifact.read_bytes() == expected
        assert sha256(artifact.read_bytes()).hexdigest() == sha256(expected).hexdigest()
    manifest_hash = sha256(manifest.read_bytes()).hexdigest()
    AppendOnlyRunManifest.open(manifest, clock=lambda: _NOW).state()
    assert sha256(manifest.read_bytes()).hexdigest() == manifest_hash


def test_report_admission_rejects_mismatch_and_admits_only_clean_report() -> None:
    """A defective final comparison cannot publish, while the clean report is admitted."""
    clean = _report()
    defective = replace(
        clean,
        final_comparison=replace(clean.final_comparison, production_bytes_identical=False),
    )
    rejected = admit_assessment_report(defective)
    admitted = admit_assessment_report(clean)

    assert rejected.admitted is False
    assert rejected.reasons == (
        "source workspace mismatch: final comparison did not preserve production",
    )
    assert admitted.admitted is True
    assert admitted.reasons == ()
