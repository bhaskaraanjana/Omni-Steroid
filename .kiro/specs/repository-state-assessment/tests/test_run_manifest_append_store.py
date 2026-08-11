"""Boundary tests for the append-only resumable run manifest."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from assessor.assessment_phase_gates import AssessmentPhase, GateStatus
from assessor.model_types import ZonedTimestamp
from assessor.run_manifest_append_store import AppendOnlyRunManifest, RunIdentity
from assessor.run_models import PhaseState

_NOW = ZonedTimestamp(datetime(2026, 7, 31, tzinfo=timezone.utc))


def test_superseding_gate_record_appends_without_changing_original_bytes(tmp_path: Path) -> None:
    path = tmp_path / "manifest.jsonl"
    store = AppendOnlyRunManifest.create(
        path,
        RunIdentity("run-1", "source", "temporary", "output", "token-1"),
        clock=lambda: _NOW,
    )
    original = store.append_phase_finished(
        AssessmentPhase.BASELINE,
        PhaseState.FAILED,
        GateStatus.FAILED,
        (),
        "baseline observation failed",
    )
    bytes_before = path.read_bytes()

    replacement = store.append_phase_finished(
        AssessmentPhase.BASELINE,
        PhaseState.COMPLETED,
        GateStatus.GREEN,
        ("baseline-2.json",),
        None,
        supersedes=original.record_id,
    )
    bytes_after = path.read_bytes()

    assert bytes_after[: len(bytes_before)] == bytes_before
    assert bytes_after.count(b"\n") == bytes_before.count(b"\n") + 1
    state = AppendOnlyRunManifest.open(path, clock=lambda: _NOW).state()
    assert state.gate_for(AssessmentPhase.BASELINE) is GateStatus.GREEN
    assert tuple(record.record_id for record in state.records) == (
        "run-1:000000",
        original.record_id,
        replacement.record_id,
    )
    assert state.record(original.record_id).reason == "baseline observation failed"
    assert state.record(replacement.record_id).supersedes == original.record_id


def test_evidence_correction_retains_both_references_and_effective_supersession(
    tmp_path: Path,
) -> None:
    store = AppendOnlyRunManifest.create(
        tmp_path / "manifest.jsonl",
        RunIdentity("run-2", "source", "temporary", "output", "token-2"),
        clock=lambda: _NOW,
    )
    raw = store.append_evidence("raw/check.stdout", None)
    corrected = store.append_evidence("normalized/check-v2.json", raw.record_id)

    state = store.state()
    assert tuple(
        record.artifact_refs for record in state.records if record.event.value == "evidence"
    ) == (
        ("raw/check.stdout",),
        ("normalized/check-v2.json",),
    )
    assert tuple(
        record.record_id for record in state.effective_records if record.event.value == "evidence"
    ) == (corrected.record_id,)
