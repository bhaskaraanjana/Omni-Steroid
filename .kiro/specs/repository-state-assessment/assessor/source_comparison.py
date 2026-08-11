"""Capture and compare source manifests on every assessment termination path.

The comparison is observation-only: it reports additions, removals, byte changes,
and writes outside designated roots. It intentionally contains no restoration API.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from .baseline_collector import BaselineCollector
from .baseline_models import FileManifest, ManifestEntry
from .model_types import ZonedTimestamp
from .preservation import AssessmentTermination
from .run_models import FileDifference, WorkspaceComparison
from .write_admission import path_is_within_designated_roots


_UNOBSERVABLE_MANIFEST_REF = "final-comparison-unobservable"


@dataclass(frozen=True, slots=True)
class FinalComparisonRecord:
    """Termination classification paired with its mandatory source comparison."""

    termination: AssessmentTermination
    comparison: WorkspaceComparison


class GitManifestCollectionError(RuntimeError):
    """Raised when final read-only Git/path observation cannot be completed."""


def _entry_map(manifest: FileManifest) -> dict[str, ManifestEntry]:
    entries = {entry.path: entry for entry in manifest.entries}
    if len(entries) != len(manifest.entries):
        raise ValueError("manifest paths must be unique")
    return entries


def _difference(
    path: str, kind: str, baseline: str | None, final: str | None
) -> FileDifference:
    return FileDifference(path, kind, baseline, final)


def compare_workspace_manifests(
    baseline_manifest: FileManifest,
    final_manifest: FileManifest,
    *,
    baseline_manifest_ref: str,
    final_manifest_ref: str,
    designated_roots: tuple[str, ...],
    observed_writes: tuple[str, ...],
    compared_at: ZonedTimestamp,
) -> WorkspaceComparison:
    """Compare tracked/untracked path sets and every baseline file byte hash."""
    baseline = _entry_map(baseline_manifest)
    final = _entry_map(final_manifest)
    baseline_tracked = {path for path, entry in baseline.items() if entry.tracked}
    final_tracked = {path for path, entry in final.items() if entry.tracked}
    baseline_untracked = set(baseline) - baseline_tracked
    final_untracked = set(final) - final_tracked

    differences: list[FileDifference] = []
    for path in sorted(set(baseline) | set(final)):
        before = baseline.get(path)
        after = final.get(path)
        if before is None:
            differences.append(_difference(path, "added", None, after.sha256 if after else None))
            continue
        if after is None:
            differences.append(_difference(path, "deleted", before.sha256, None))
            continue
        if before.tracked != after.tracked:
            differences.append(
                _difference(path, "tracking_changed", str(before.tracked), str(after.tracked))
            )
        if before.sha256 != after.sha256 or before.size_bytes != after.size_bytes:
            differences.append(
                _difference(path, "content_changed", before.sha256, after.sha256)
            )

    production_bytes_identical = all(
        path in final
        and final[path].sha256 == entry.sha256
        and final[path].size_bytes == entry.size_bytes
        for path, entry in baseline.items()
    )
    outside_writes = tuple(
        dict.fromkeys(
            path
            for path in observed_writes
            if not path_is_within_designated_roots(path, designated_roots)
        )
    )
    return WorkspaceComparison(
        baseline_manifest_ref=baseline_manifest_ref,
        final_manifest_ref=final_manifest_ref,
        tracked_paths_identical=baseline_tracked == final_tracked,
        untracked_paths_identical=baseline_untracked == final_untracked,
        production_bytes_identical=production_bytes_identical,
        differences=tuple(differences),
        writes_outside_designated_roots=outside_writes,
        compared_at=compared_at,
    )


def _unobservable_comparison() -> WorkspaceComparison:
    """Return the only safe comparison when the final observation itself failed.

    Every preservation dimension is reported unconfirmed. An unobserved workspace is
    never "identical" -- claiming otherwise would turn a failed check into reassurance.
    """
    return WorkspaceComparison(
        baseline_manifest_ref=_UNOBSERVABLE_MANIFEST_REF,
        final_manifest_ref=_UNOBSERVABLE_MANIFEST_REF,
        tracked_paths_identical=False,  # fail-closed: unobserved is never confirmed identical
        untracked_paths_identical=False,  # fail-closed: unobserved is never confirmed identical
        production_bytes_identical=False,  # fail-closed: unobserved is never confirmed identical
        differences=(),  # no differences were observed because observation itself failed
        writes_outside_designated_roots=(),
        compared_at=ZonedTimestamp(datetime.now(UTC)),
    )


def _termination_for_exception(
    exception_type: type[BaseException] | None,
) -> AssessmentTermination:
    if exception_type is None:
        return AssessmentTermination.SUCCESS
    if issubclass(exception_type, (TimeoutError, asyncio.TimeoutError)):
        return AssessmentTermination.TIMEOUT
    if issubclass(exception_type, (KeyboardInterrupt, asyncio.CancelledError)):
        return AssessmentTermination.ABORT
    return AssessmentTermination.FAILURE


class FinalComparisonGuard:
    """Context guard that emits one final comparison and never restores source."""

    def __init__(
        self,
        compare: Callable[[], WorkspaceComparison],
        record_writer: Callable[[FinalComparisonRecord], object],
    ) -> None:
        self._compare = compare
        self._record_writer = record_writer
        self.record: FinalComparisonRecord | None = None

    def __enter__(self) -> "FinalComparisonGuard":
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        _exception: BaseException | None,
        _traceback: object,
    ) -> bool:
        self.finalize(_termination_for_exception(exception_type))
        return False

    def finalize(self, termination: AssessmentTermination) -> FinalComparisonRecord:
        """Create the comparison exactly once for explicit or context termination.

        A failure inside the comparison itself still emits the mandatory record before
        the exception propagates, so a termination path can never end with no artifact.
        """
        if self.record is not None:
            return self.record
        try:
            comparison = self._compare()
        except BaseException:
            # fail-closed: an unobservable comparison must still emit its mandatory record
            # rather than leave the caller with silence that reads as "nothing changed".
            self._emit(FinalComparisonRecord(termination, _unobservable_comparison()))
            raise
        return self._emit(FinalComparisonRecord(termination, comparison))

    def _emit(self, record: FinalComparisonRecord) -> FinalComparisonRecord:
        """Store and write the single final comparison record for this run."""
        self.record = record
        self._record_writer(record)
        return record


def _git_paths(root: Path, *arguments: str) -> tuple[str, ...]:
    environment = os.environ.copy()
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    environment["LC_ALL"] = "C"
    try:
        result = subprocess.run(
            ("git", "--no-optional-locks", *arguments),
            cwd=root,
            env=environment,
            check=True,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise GitManifestCollectionError(
            f"final Git observation failed for {arguments[0]}: {error}"
        ) from error
    return tuple(
        sorted(
            item.decode("utf-8", errors="surrogateescape").replace("\\", "/")
            for item in result.stdout.split(b"\0")
            if item
        )
    )


def _hash_path(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    if path.is_symlink():
        payload = os.fsencode(os.readlink(path))
        return len(payload), hashlib.sha256(payload).hexdigest()
    size = 0
    try:
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                size += len(chunk)
                digest.update(chunk)
    except OSError as error:
        raise GitManifestCollectionError(f"could not hash final path {path}: {error}") from error
    return size, digest.hexdigest()


def collect_git_workspace_manifest(
    repository_root: str | Path,
    *,
    manifest_id: str,
    created_at: ZonedTimestamp,
    excluded_prefixes: tuple[str, ...] = (
        ".git",
        ".kiro/specs/repository-state-assessment/assessment-output",
    ),
) -> FileManifest:
    """Capture current tracked/untracked disk bytes using read-only Git queries."""
    try:
        root = Path(repository_root).resolve(strict=True)
    except OSError as error:
        raise GitManifestCollectionError("repository root is unavailable") from error
    tracked = set(_git_paths(root, "ls-files", "-z", "--cached"))
    untracked = set(
        _git_paths(root, "ls-files", "-z", "--others", "--exclude-standard")
    )

    def excluded(path: str) -> bool:
        parts = PurePosixPath(path).parts
        return any(
            parts[: len(PurePosixPath(prefix).parts)] == PurePosixPath(prefix).parts
            for prefix in excluded_prefixes
        )

    entries: list[ManifestEntry] = []
    for relative_path in sorted(tracked | untracked):
        if excluded(relative_path):
            continue
        candidate = root.joinpath(*PurePosixPath(relative_path).parts)
        if not candidate.is_file() and not candidate.is_symlink():
            continue
        size, digest = _hash_path(candidate)
        entries.append(
            ManifestEntry(
                path=relative_path,
                size_bytes=size,
                sha256=digest,
                tracked=relative_path in tracked,
                sensitive_category=BaselineCollector.classify_sensitive_path(relative_path),
            )
        )
    return FileManifest(manifest_id, "final", created_at, tuple(entries))
