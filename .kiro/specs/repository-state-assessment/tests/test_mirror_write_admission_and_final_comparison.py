"""Filesystem examples for mirror fidelity, fail-closed writes, and final comparison.

**Validates: Requirements 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 3.17, 9.14**
"""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

import pytest

from assessor.baseline_models import FileManifest, ManifestEntry
from assessor.mirror_workspace import create_verified_mirror
from assessor.model_types import WritePolicy, ZonedTimestamp
from assessor.preservation import (
    AssessmentTermination,
    PlannedOperation,
    PlannedWrite,
)
from assessor.source_comparison import (
    FinalComparisonGuard,
    compare_workspace_manifests,
)
from assessor.write_admission import (
    WriteAdmissionRequest,
    audit_observed_writes,
    evaluate_write_admission,
)

_NOW = ZonedTimestamp(datetime(2026, 7, 8, tzinfo=timezone.utc))


def _entry(path: str, content: bytes, *, tracked: bool) -> ManifestEntry:
    return ManifestEntry(path, len(content), sha256(content).hexdigest(), tracked)


def _manifest(*entries: ManifestEntry, kind: str = "source") -> FileManifest:
    return FileManifest("fixture-manifest", kind, _NOW, entries)


def test_mirror_copies_current_bytes_and_excludes_git_and_prior_outputs(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    files = {
        "tracked.txt": b"staged bytes on disk",
        "src/unstaged.py": b"unstaged bytes on disk\n",
        "notes/untracked.txt": b"untracked bytes",
        ".git/index": b"must not copy",
        ".kiro/specs/repository-state-assessment/assessment-output/old/report.json": b"old",
    }
    for relative_path, content in files.items():
        target = source / Path(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    source_manifest = _manifest(
        *(
            _entry(path, content, tracked=not path.startswith("notes/"))
            for path, content in files.items()
        )
    )

    result = create_verified_mirror(source, tmp_path / "run" / "mirror", source_manifest)

    assert result.verified
    assert set(result.copied_paths) == {
        "tracked.txt",
        "src/unstaged.py",
        "notes/untracked.txt",
    }
    assert set(result.excluded_paths) == {
        ".git/index",
        ".kiro/specs/repository-state-assessment/assessment-output/old/report.json",
    }
    assert (result.mirror_root / "tracked.txt").read_bytes() == files["tracked.txt"]
    assert (result.mirror_root / "src" / "unstaged.py").read_bytes() == files[
        "src/unstaged.py"
    ]
    assert not (result.mirror_root / ".git").exists()
    assert result.mirror_manifest.entries == tuple(
        entry
        for entry in source_manifest.entries
        if entry.path in result.copied_paths
    )


def test_mirror_hash_mismatch_blocks_verification(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "changed.txt").write_bytes(b"current")
    stale_entry = _entry("changed.txt", b"baseline", tracked=True)

    result = create_verified_mirror(
        source, tmp_path / "run" / "mirror", _manifest(stale_entry)
    )

    assert not result.verified
    assert result.copied_paths == ()
    assert result.mismatches[0].path == "changed.txt"
    assert result.mismatches[0].expected_sha256 == stale_entry.sha256


def _operation(target: str) -> PlannedOperation:
    return PlannedOperation(
        operation_id="python-tests",
        command_or_procedure=("python", "-m", "pytest"),
        requested_admission=True,
        writes=(PlannedWrite(target, b"planned output"),),
        dependent_check_ids=("python-tests", "python-coverage"),
    )


@pytest.mark.parametrize(
    ("redirected", "audit_available", "reason_fragment"),
    [
        (False, True, "redirection"),
        (True, False, "audit"),
    ],
)
def test_write_admission_fails_closed_with_complete_omission(
    tmp_path: Path,
    redirected: bool,
    audit_available: bool,
    reason_fragment: str,
) -> None:
    output_root = tmp_path / "run" / "artifacts"
    output_root.mkdir(parents=True)
    operation = _operation(str(output_root / "pytest.json"))

    decision = evaluate_write_admission(
        WriteAdmissionRequest(
            operation=operation,
            write_policy=WritePolicy((str(output_root),)),
            redirects_established=redirected,
            audit_available=audit_available,
            preexisting_paths=(),
        )
    )

    assert not decision.admitted
    assert decision.omission is not None
    assert reason_fragment in decision.omission.reason
    assert decision.omission.command_or_procedure == operation.command_or_procedure
    assert tuple(item.path for item in decision.omission.affected_content) == (
        str(output_root / "pytest.json"),
    )
    assert tuple(item.check_id for item in decision.omission.dependent_checks) == (
        "python-tests",
        "python-coverage",
    )


def test_write_admission_and_audit_reject_preexisting_or_escaped_writes(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "run" / "artifacts"
    output_root.mkdir(parents=True)
    planned_target = output_root / "new.json"
    decision = evaluate_write_admission(
        WriteAdmissionRequest(
            operation=_operation(str(planned_target)),
            write_policy=WritePolicy((str(output_root),)),
            redirects_established=True,
            audit_available=True,
            preexisting_paths=(),
        )
    )
    assert decision.admitted

    source_path = tmp_path / "source" / "app.py"
    audit = audit_observed_writes(
        (str(planned_target), str(source_path)),
        WritePolicy((str(output_root),)),
        preexisting_paths=(str(source_path),),
        audit_complete=True,
    )

    assert not audit.compliant
    assert audit.writes_outside_designated_roots == (str(source_path),)
    assert audit.preexisting_content_writes == (str(source_path),)


def test_final_comparison_reports_path_bytes_and_outside_writes() -> None:
    baseline = _manifest(
        _entry("src/app.py", b"before", tracked=True),
        _entry("notes/local.txt", b"note", tracked=False),
    )
    final = _manifest(
        _entry("src/app.py", b"after", tracked=True),
        _entry("new.py", b"new", tracked=True),
        kind="final",
    )

    comparison = compare_workspace_manifests(
        baseline,
        final,
        baseline_manifest_ref="baseline/source-manifest.json",
        final_manifest_ref="final/failure-source-manifest.json",
        designated_roots=("run/artifacts",),
        observed_writes=("run/artifacts/log.txt", "src/app.py"),
        compared_at=_NOW,
    )

    assert not comparison.tracked_paths_identical
    assert not comparison.untracked_paths_identical
    assert not comparison.production_bytes_identical
    assert comparison.writes_outside_designated_roots == ("src/app.py",)
    assert {item.difference_kind for item in comparison.differences} == {
        "added",
        "deleted",
        "content_changed",
    }


@pytest.mark.parametrize(
    "termination",
    list(AssessmentTermination),
)
def test_guard_compares_on_every_termination_and_never_restores_source(
    tmp_path: Path, termination: AssessmentTermination
) -> None:
    source = tmp_path / "source.txt"
    source.write_bytes(b"baseline")
    baseline = _manifest(_entry("source.txt", b"baseline", tracked=True))
    records = []

    def compare() -> object:
        final_content = source.read_bytes()
        final = _manifest(_entry("source.txt", final_content, tracked=True), kind="final")
        return compare_workspace_manifests(
            baseline,
            final,
            baseline_manifest_ref="baseline.json",
            final_manifest_ref=f"final/{termination.value}.json",
            designated_roots=(str(tmp_path / "run"),),
            observed_writes=(str(source),),
            compared_at=_NOW,
        )

    guard = FinalComparisonGuard(compare, records.append)
    with pytest.raises((RuntimeError, TimeoutError, KeyboardInterrupt)) if termination is not AssessmentTermination.SUCCESS else _does_not_raise():
        with guard:
            source.write_bytes(b"unexpected mutation")
            if termination is AssessmentTermination.FAILURE:
                raise RuntimeError("fixture failure")
            if termination is AssessmentTermination.TIMEOUT:
                raise TimeoutError("fixture timeout")
            if termination is AssessmentTermination.ABORT:
                raise KeyboardInterrupt()

    assert guard.record is not None
    assert guard.record.termination is termination
    assert records == [guard.record]
    assert not guard.record.comparison.preservation_confirmed
    assert source.read_bytes() == b"unexpected mutation"


class _does_not_raise:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *_args: object) -> bool:
        return False
