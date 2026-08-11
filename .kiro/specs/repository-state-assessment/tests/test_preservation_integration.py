"""Task 3.3 preservation integration tests for Requirements 1.5, 1.7, 1.8, 1.9."""

from __future__ import annotations

import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Iterator

import pytest

from assessor.baseline_models import FileManifest, ManifestEntry
from assessor.mirror_workspace import create_verified_mirror
from assessor.model_types import AssessmentStatus, WritePolicy, ZonedTimestamp
from assessor.preservation import AssessmentTermination, PlannedOperation, PlannedWrite
from assessor.source_comparison import FinalComparisonGuard, compare_workspace_manifests
from assessor.write_admission import WriteAdmissionRequest, audit_observed_writes, evaluate_write_admission

_NOW = ZonedTimestamp(datetime(2026, 7, 31, tzinfo=timezone.utc))

@dataclass(frozen=True)
class _Repository:
    root: Path
    tracked: frozenset[str]
    baseline: FileManifest
    expected: dict[str, bytes]
    read_only: Path

def _snapshot(repo: _Repository, manifest_id: str, kind: str = "final") -> FileManifest:
    entries = []
    for path in sorted(item for item in repo.root.rglob("*") if item.is_file()):
        relative = path.relative_to(repo.root).as_posix()
        payload = path.read_bytes()
        entries.append(
            ManifestEntry(
                relative,
                len(payload),
                sha256(payload).hexdigest(),
                relative in repo.tracked,
            )
        )
    return FileManifest(manifest_id, kind, _NOW, tuple(entries))


def _assert_source_exact(repo: _Repository) -> None:
    final = _snapshot(repo, "assert-exact")
    assert final.entries == repo.baseline.entries
    assert {entry.path: (entry.size_bytes, entry.sha256) for entry in final.entries} == {
        path: (len(payload), sha256(payload).hexdigest())
        for path, payload in repo.expected.items()
    }
    assert all((repo.root / Path(path)).read_bytes() == payload for path, payload in repo.expected.items())


@pytest.fixture
def repository(tmp_path: Path) -> Iterator[_Repository]:
    root = tmp_path / "disposable source fixture 雪 with spaces"
    files = {
        "tracked/CaseTwin.TXT": b"tracked-case\x00bytes\n",
        "tracked/Résumé read only.ini": "clé=東京\r\n".encode(),
        "tracked/empty file.bin": b"",
        "untracked nested/東京/casetwin.txt": b"untracked lower-case twin\n",
        "untracked nested/東京/notes with spaces.md": "naïve 雪\n".encode(),
    }
    tracked = frozenset(path for path in files if path.startswith("tracked/"))
    for relative, payload in files.items():
        target = root / Path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    read_only = root / "tracked/Résumé read only.ini"
    read_only.chmod(stat.S_IREAD)
    provisional = _Repository(root, tracked, FileManifest("pending", "source", _NOW, ()), files, read_only)
    repo = replace(provisional, baseline=_snapshot(provisional, "fixture-baseline", "source"))
    try:
        yield repo
    finally:
        read_only.chmod(stat.S_IREAD | stat.S_IWRITE)


def _operation(operation_id: str, writes: tuple[PlannedWrite, ...]) -> PlannedOperation:
    return PlannedOperation(
        operation_id,
        ("fixture-writer", "--synthetic"),
        True,
        writes,
        ("check-bytes", "check-report"),
    )


def _comparison(repo: _Repository, run_root: Path, observed: tuple[str, ...]):
    return compare_workspace_manifests(
        repo.baseline,
        _snapshot(repo, "fixture-final"),
        baseline_manifest_ref="baseline/source-manifest.json",
        final_manifest_ref="final/source-manifest.json",
        designated_roots=(str(run_root),),
        observed_writes=observed,
        compared_at=_NOW,
    )


def test_safe_write_is_mirrored_admitted_audited_and_cleaned(repository: _Repository) -> None:
    """A new designated-root write is byte-faithful, admitted, audited, and solely cleaned."""
    run_root = repository.root.parent / "assessment owned run 雪"
    output_root = run_root / "artifacts with spaces"
    output_root.mkdir(parents=True)
    mirror = create_verified_mirror(repository.root, run_root / "mirror", repository.baseline)
    assert mirror.verified
    assert mirror.mirror_manifest.entries == repository.baseline.entries
    for entry in repository.baseline.entries:
        copied = mirror.mirror_root / Path(entry.path)
        assert copied.read_bytes() == repository.expected[entry.path]
        assert sha256(copied.read_bytes()).hexdigest() == entry.sha256
    names = [Path(path).name for path in repository.expected]
    assert "CaseTwin.TXT" in names and "casetwin.txt" in names
    assert "CaseTwin.TXT".casefold() == "casetwin.txt".casefold()
    assert repository.read_only.stat().st_mode & stat.S_IWRITE == 0

    target = output_root / "safe result 東京.json"
    payload = "{\"result\":\"雪\"}\n".encode()
    policy = WritePolicy((str(output_root),))
    decision = evaluate_write_admission(
        WriteAdmissionRequest(_operation("safe", (PlannedWrite(str(target), payload),)), policy, True, True, ())
    )
    assert decision.admitted and decision.omission is None
    target.write_bytes(payload)
    audit = audit_observed_writes((str(target),), policy, preexisting_paths=(), audit_complete=True)
    assert audit.compliant
    assert audit.observed_writes == (str(target),)
    assert target.read_bytes() == payload
    assert sha256(target.read_bytes()).hexdigest() == sha256(payload).hexdigest()
    assert _comparison(repository, output_root, audit.observed_writes).preservation_confirmed

    shutil.rmtree(run_root)
    assert not run_root.exists()
    _assert_source_exact(repository)


def test_path_traversal_is_refused_with_complete_omission(repository: _Repository) -> None:
    """Traversal and pre-existing targets are refused with exact content and dependent checks."""
    output_root = repository.root.parent / "run" / "artifacts"
    traversal = str(output_root / ".." / "escaped" / "danger.bin")
    existing = str(repository.root / "tracked" / "CaseTwin.TXT")
    writes = (PlannedWrite(traversal, b"escape"), PlannedWrite(existing, b"overwrite"))
    operation = _operation("unsafe-traversal", writes)
    decision = evaluate_write_admission(
        WriteAdmissionRequest(
            operation,
            WritePolicy((str(output_root),)),
            True,
            True,
            tuple(str(repository.root / Path(path)) for path in repository.expected),
        )
    )
    assert not decision.admitted
    assert decision.omission is not None
    omission = decision.omission
    assert omission.operation_id == "unsafe-traversal"
    assert omission.command_or_procedure == operation.command_or_procedure
    assert tuple((item.path, item.size_bytes, item.sha256) for item in omission.affected_content) == tuple(
        (write.path, len(write.content), sha256(write.content).hexdigest()) for write in writes
    )
    assert tuple(item.check_id for item in omission.dependent_checks) == ("check-bytes", "check-report")
    assert all(item.status is AssessmentStatus.UNVERIFIED for item in omission.dependent_checks)
    assert traversal in omission.reason and existing in omission.reason
    assert not Path(traversal).exists()
    _assert_source_exact(repository)


def test_unexpected_write_is_surfaced_after_execution(repository: _Repository) -> None:
    """A post-hoc outside write makes both audit and final preservation fail closed."""
    run_root = repository.root.parent / "owned run"
    output_root = run_root / "outputs"
    output_root.mkdir(parents=True)
    declared = output_root / "declared.bin"
    rogue = repository.root.parent / "unexpected outside 東京.bin"
    policy = WritePolicy((str(output_root),))
    decision = evaluate_write_admission(
        WriteAdmissionRequest(_operation("declared", (PlannedWrite(str(declared), b"ok"),)), policy, True, True, ())
    )
    assert decision.admitted
    declared.write_bytes(b"ok")
    rogue.write_bytes(b"rogue")
    audit = audit_observed_writes(
        (str(declared), str(rogue), str(rogue)), policy, preexisting_paths=(), audit_complete=True
    )
    assert not audit.compliant
    assert audit.observed_writes == (str(declared), str(rogue))
    assert audit.writes_outside_designated_roots == (str(rogue),)
    comparison = _comparison(repository, output_root, audit.observed_writes)
    assert comparison.differences == ()
    assert comparison.writes_outside_designated_roots == (str(rogue),)
    assert not comparison.preservation_confirmed
    shutil.rmtree(run_root)
    assert rogue.read_bytes() == b"rogue"
    rogue.unlink()
    _assert_source_exact(repository)


def test_mirror_hash_mismatch_blocks_all_dependent_checks(repository: _Repository) -> None:
    """A forged baseline hash cannot yield a verified mirror or runnable dependent check."""
    victim = next(entry for entry in repository.baseline.entries if entry.path.endswith("CaseTwin.TXT"))
    forged = replace(victim, sha256=sha256(b"stale bytes").hexdigest())
    stale = replace(
        repository.baseline,
        entries=tuple(forged if entry is victim else entry for entry in repository.baseline.entries),
    )
    result = create_verified_mirror(
        repository.root,
        repository.root.parent / "mismatch run" / "mirror",
        stale,
        dependent_check_ids=("python-tests", "coverage"),
    )
    assert not result.verified
    assert result.mismatches == (
        replace(result.mismatches[0], path=victim.path, expected_sha256=forged.sha256),
    )
    assert result.mismatches[0].actual_sha256 == victim.sha256
    assert victim.path not in result.copied_paths
    assert tuple(item.check_id for item in result.blocked_checks) == ("python-tests", "coverage")
    assert all(item.status is AssessmentStatus.UNVERIFIED for item in result.blocked_checks)
    assert _comparison(repository, result.mirror_root.parent, ()).preservation_confirmed
    shutil.rmtree(result.mirror_root.parent)
    _assert_source_exact(repository)


@pytest.mark.parametrize(
    ("mode", "expected"),
    (("success", AssessmentTermination.SUCCESS), ("failure", AssessmentTermination.FAILURE),
     ("timeout", AssessmentTermination.TIMEOUT), ("cancellation", AssessmentTermination.ABORT),
     ("crash", AssessmentTermination.ABORT)),
)
def test_every_termination_compares_bytes_and_cleans_only_owned_paths(
    repository: _Repository, mode: str, expected: AssessmentTermination
) -> None:
    """Success, failure, timeout, cancellation, and crash all compare before owned cleanup."""
    run_root = repository.root.parent / f"assessment-owned-{mode}"
    run_root.mkdir()
    marker = run_root / "owned marker.bin"
    records = []
    guard = FinalComparisonGuard(lambda: _comparison(repository, run_root, (str(marker),)), records.append)

    if mode == "crash":
        script = "import os,pathlib,sys; pathlib.Path(sys.argv[1]).write_bytes(b'crash'); os._exit(91)"
        crashed = subprocess.run((sys.executable, "-c", script, str(marker)), cwd=run_root, check=False)
        assert crashed.returncode == 91
        guard.finalize(AssessmentTermination.ABORT)
    elif mode == "success":
        with guard:
            marker.write_bytes(b"success")
    else:
        error_type = {"failure": RuntimeError, "timeout": TimeoutError, "cancellation": KeyboardInterrupt}[mode]
        with pytest.raises(error_type):
            with guard:
                marker.write_bytes(mode.encode())
                raise error_type(f"synthetic {mode}")

    assert marker.read_bytes() == (b"crash" if mode == "crash" else mode.encode())
    assert guard.record is not None
    assert records == [guard.record]
    assert guard.record.termination is expected
    assert guard.record.comparison.preservation_confirmed
    assert guard.record.comparison.differences == ()
    shutil.rmtree(run_root)
    assert not run_root.exists()
    _assert_source_exact(repository)


def test_missing_manifest_content_and_incomplete_audit_fail_closed(repository: _Repository) -> None:
    """Absent final entries and an incomplete audit never resolve to identical or safe."""
    comparison = compare_workspace_manifests(
        repository.baseline, FileManifest("missing-final-content", "final", _NOW, ()),
        baseline_manifest_ref="baseline.json", final_manifest_ref="failed-final.json",
        designated_roots=(str(repository.root.parent / "run"),), observed_writes=(), compared_at=_NOW,
    )
    assert (comparison.tracked_paths_identical, comparison.untracked_paths_identical,
            comparison.production_bytes_identical, comparison.preservation_confirmed) == (False,) * 4
    assert {(item.path, item.difference_kind) for item in comparison.differences} == {(path, "deleted") for path in repository.expected}
    audit = audit_observed_writes((), WritePolicy(("run/artifacts",)), preexisting_paths=(), audit_complete=False)
    assert (audit.observed_writes, audit.compliant) == ((), False)
    _assert_source_exact(repository)


def test_failed_final_comparison_emits_fail_closed_record(repository: _Repository) -> None:
    """A failed final observation must emit a non-reassuring artifact rather than no record."""
    records = []
    guard = FinalComparisonGuard(
        lambda: (_ for _ in ()).throw(OSError("synthetic final manifest read failure")), records.append
    )
    with pytest.raises(OSError, match="synthetic final manifest read failure"):
        guard.finalize(AssessmentTermination.FAILURE)
    assert guard.record is not None
    assert records == [guard.record]
    assert not guard.record.comparison.preservation_confirmed
    _assert_source_exact(repository)
