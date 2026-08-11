"""Verify the assessor's domain contracts and safety-critical model invariants."""

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from assessor import (
    AssessmentBaseline,
    AssessmentStatus,
    BenchmarkSet,
    ExactArgumentVector,
    Measurement,
    MeasurementUnit,
    NetworkMode,
    NetworkPolicy,
    OperatingSystemInventory,
    ParityRow,
    RepositoryHead,
    RepositoryHeadKind,
    RerunInstruction,
    WorkspaceComparison,
    WritePolicy,
    ZonedTimestamp,
)


def test_safety_critical_value_objects_are_lossless_and_fail_closed() -> None:
    timestamp = ZonedTimestamp(datetime(2026, 7, 8, 9, 10, tzinfo=timezone(timedelta(hours=5))))
    argv = ExactArgumentVector(("cmd.exe", "/c", "C:\\DEV\\Omni Steroid\\check.cmd", ""))
    measurement = Measurement("wer", Decimal("0.0"), MeasurementUnit.PERCENT, "local corpus")

    assert timestamp.value.utcoffset() == timedelta(hours=5)
    assert argv.values[-2:] == ("C:\\DEV\\Omni Steroid\\check.cmd", "")
    assert measurement.value == Decimal("0.0")
    assert NetworkPolicy(NetworkMode.LOOPBACK_ONLY).permits_non_loopback is False
    assert WritePolicy(("run-root",)).permits_preexisting_mutation is False


def test_classified_models_have_one_immutable_primary_status() -> None:
    row = ParityRow(
        row_id="granola-meeting-search",
        benchmark_set=BenchmarkSet.GRANOLA,
        benchmark_capability="meeting search",
        benchmark_source=None,
        benchmark_source_date=None,
        benchmark_basis_status=AssessmentStatus.UNVERIFIED,
        omni_documentary_claim_refs=(),
        implementation_locations=(),
        fresh_evidence_refs=(),
        primary_status=AssessmentStatus.UNVERIFIED,
        limitation="No current benchmark source",
        parity_conclusion="Unverified",
        measurements=(),
    )
    assert row.primary_status is AssessmentStatus.UNVERIFIED
    with pytest.raises(FrozenInstanceError):
        row.primary_status = AssessmentStatus.VERIFIED_WORKING  # type: ignore[misc]


def test_head_and_workspace_comparison_are_explicit() -> None:
    head = RepositoryHead("a" * 40, RepositoryHeadKind.DETACHED)
    comparison = WorkspaceComparison(
        baseline_manifest_ref="baseline",
        final_manifest_ref="final",
        tracked_paths_identical=True,
        untracked_paths_identical=True,
        production_bytes_identical=True,
        differences=(),
        writes_outside_designated_roots=(),
    )
    assert head.branch_name is None
    assert comparison.preservation_confirmed is True


def test_naive_timestamp_and_inconsistent_branch_are_rejected() -> None:
    with pytest.raises(ValueError, match="time-zone offset"):
        ZonedTimestamp(datetime(2026, 7, 8, 9, 10))
    with pytest.raises(ValueError, match="branch_name"):
        RepositoryHead("a" * 40, RepositoryHeadKind.BRANCH)


def test_branch_and_detached_head_rendering_are_unambiguous() -> None:
    commit = "a" * 40

    assert RepositoryHead(commit, RepositoryHeadKind.BRANCH, "feature/reporting").render() == (
        f"branch feature/reporting ({commit})"
    )
    assert RepositoryHead(commit, RepositoryHeadKind.DETACHED).render() == (
        f"detached HEAD ({commit})"
    )


def test_baseline_preserves_explicitly_empty_collections() -> None:
    baseline = AssessmentBaseline(
        run_id="boundary-run",
        repository_root=r"C:\DEV\Omni Steroid",
        head=RepositoryHead("b" * 40, RepositoryHeadKind.BRANCH, "main"),
        started_at=ZonedTimestamp(datetime(2026, 7, 8, 9, 10, tzinfo=timezone.utc)),
        staged_changes=(),
        unstaged_changes=(),
        untracked_paths=(),
        operating_system=OperatingSystemInventory("Windows", "11", "26100"),
        hardware=(),
        tools=(),
        source_manifest_ref="manifests/source.json",
        designated_roots=(),
    )

    assert baseline.staged_changes == ()
    assert baseline.unstaged_changes == ()
    assert baseline.untracked_paths == ()
    assert baseline.hardware == ()
    assert baseline.tools == ()
    assert baseline.designated_roots == ()


def test_windows_paths_with_spaces_render_as_replayable_arguments() -> None:
    argv = ExactArgumentVector(
        (
            r"C:\Program Files\Omni Tools\checker.exe",
            r"C:\DEV\Omni Steroid\assessment input.json",
        )
    )

    assert argv.render_windows() == (
        '"C:\\Program Files\\Omni Tools\\checker.exe" '
        '"C:\\DEV\\Omni Steroid\\assessment input.json"'
    )


def test_cmd_rerun_quotes_the_complete_command_payload() -> None:
    setup = r"C:\Program Files\Microsoft Visual Studio\setup_x64.bat"
    argv = ExactArgumentVector(
        ("cmd.exe", "/d", "/s", "/c", f'call "{setup}" && cargo test --locked')
    )
    rerun = RerunInstruction(
        prerequisites=("Visual Studio build tools", "cargo"),
        exact_argv=argv,
        numbered_procedure=None,
        expected_observable="exit code 0",
    )

    assert rerun.render_windows() == (
        'cmd.exe /d /s /c "call \\"C:\\Program Files\\Microsoft Visual Studio\\'
        'setup_x64.bat\\" && cargo test --locked"'
    )


def test_typed_zero_measurement_is_retained() -> None:
    measurement = Measurement(
        "stt_word_error_rate",
        Decimal("0.0"),
        MeasurementUnit.PERCENT,
        "labelled local speech corpus",
    )

    assert measurement.value == Decimal("0.0")
    assert measurement.value is not None
