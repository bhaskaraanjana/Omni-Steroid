"""Create and hash-verify the assessment's byte-faithful execution mirror.

The copier reads only paths captured by the baseline manifest. It never uses Git to
materialize content, so staged, unstaged, and untracked files reflect current disk
bytes. Git metadata and prior assessment outputs are deliberately excluded.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path, PurePosixPath, PureWindowsPath

from .baseline_models import FileManifest, ManifestEntry
from .model_types import AssessmentStatus

_DEFAULT_EXCLUDED_PREFIXES = (
    ".git",
    ".kiro/specs/repository-state-assessment/assessment-output",
)


class MirrorCreationError(RuntimeError):
    """Raised when safe mirror allocation or path containment cannot be proved."""


@dataclass(frozen=True, slots=True)
class MirrorHashMismatch:
    """A baseline input that could not be reproduced with its expected hash."""

    path: str
    expected_sha256: str
    actual_sha256: str | None
    reason: str


@dataclass(frozen=True, slots=True)
class MirrorBlockedCheck:
    """A dependent check blocked because at least one mirror input mismatched."""

    check_id: str
    status: AssessmentStatus = field(default=AssessmentStatus.UNVERIFIED, init=False)


@dataclass(frozen=True, slots=True)
class MirrorCopyResult:
    """Mirror location, verified manifest, exclusions, and fail-closed blockers."""

    mirror_root: Path
    mirror_manifest: FileManifest
    copied_paths: tuple[str, ...]
    excluded_paths: tuple[str, ...]
    mismatches: tuple[MirrorHashMismatch, ...]
    blocked_checks: tuple[MirrorBlockedCheck, ...]

    @property
    def verified(self) -> bool:
        """Return true only when every non-excluded baseline input matched."""
        return not self.mismatches


def _safe_parts(relative_path: str) -> tuple[str, ...]:
    if not relative_path or "\x00" in relative_path:
        raise MirrorCreationError("manifest path must be non-empty text")
    normalized = relative_path.replace("\\", "/")
    windows_path = PureWindowsPath(relative_path)
    if normalized.startswith("/") or windows_path.is_absolute() or windows_path.drive:
        raise MirrorCreationError(f"manifest path must be relative: {relative_path}")
    parts = tuple(normalized.split("/"))
    if any(part in {"", ".", ".."} or ":" in part for part in parts):
        raise MirrorCreationError(f"manifest path is unsafe: {relative_path}")
    return PurePosixPath(normalized).parts


def _is_excluded(path: str, prefixes: tuple[str, ...]) -> bool:
    parts = _safe_parts(path)
    for prefix in prefixes:
        prefix_parts = _safe_parts(prefix)
        if parts[: len(prefix_parts)] == prefix_parts:
            return True
    return False


def _hash_link(path: Path) -> tuple[int, str]:
    payload = os.fsencode(os.readlink(path))
    return len(payload), sha256(payload).hexdigest()


def _copy_and_hash(source: Path, destination: Path) -> tuple[int, str]:
    digest = sha256()
    size = 0
    with source.open("rb") as input_file, destination.open("xb") as output_file:
        while chunk := input_file.read(1024 * 1024):
            output_file.write(chunk)
            digest.update(chunk)
            size += len(chunk)
    return size, digest.hexdigest()


def _copy_entry(
    source_root: Path, mirror_root: Path, entry: ManifestEntry
) -> tuple[int, str]:
    parts = _safe_parts(entry.path)
    source = source_root.joinpath(*parts)
    destination = mirror_root.joinpath(*parts)
    try:
        parent = source.parent.resolve(strict=True)
    except OSError as error:
        raise MirrorCreationError(f"source parent is unavailable: {entry.path}") from error
    if not parent.is_relative_to(source_root):
        raise MirrorCreationError(f"source path traverses a linked directory: {entry.path}")
    destination.parent.mkdir(parents=True, exist_ok=True)

    if source.is_symlink():
        size, digest = _hash_link(source)
        try:
            os.symlink(os.readlink(source), destination)
        except OSError as error:
            raise MirrorCreationError(f"could not reproduce symbolic link: {entry.path}") from error
        return size, digest
    try:
        resolved_source = source.resolve(strict=True)
    except OSError as error:
        raise MirrorCreationError(f"source input is unavailable: {entry.path}") from error
    if not resolved_source.is_relative_to(source_root) or not resolved_source.is_file():
        raise MirrorCreationError(f"source input is not a contained file: {entry.path}")
    return _copy_and_hash(resolved_source, destination)


def create_verified_mirror(
    source_root: str | Path,
    mirror_root: str | Path,
    source_manifest: FileManifest,
    *,
    excluded_prefixes: tuple[str, ...] = _DEFAULT_EXCLUDED_PREFIXES,
    dependent_check_ids: tuple[str, ...] = (),
) -> MirrorCopyResult:
    """Copy baseline on-disk inputs into a new mirror and verify every hash.

    The mirror must not already exist and must be outside the source workspace.
    Hash mismatches are returned as blockers rather than hidden or repaired.
    """
    source = Path(source_root).resolve(strict=True)
    if not source.is_dir():
        raise MirrorCreationError(f"source root is not a directory: {source}")
    requested_mirror = Path(mirror_root)
    if os.path.lexists(requested_mirror):
        raise MirrorCreationError(f"mirror root already exists: {requested_mirror}")
    resolved_mirror = requested_mirror.resolve(strict=False)
    if resolved_mirror.is_relative_to(source):
        raise MirrorCreationError("mirror root cannot be inside the source workspace")
    try:
        requested_mirror.mkdir(parents=True)
    except OSError as error:
        raise MirrorCreationError(f"could not allocate mirror root: {error}") from error
    mirror = requested_mirror.resolve(strict=True)

    copied_entries: list[ManifestEntry] = []
    excluded: list[str] = []
    mismatches: list[MirrorHashMismatch] = []
    seen_paths: set[str] = set()
    for entry in source_manifest.entries:
        if entry.path in seen_paths:
            raise MirrorCreationError(f"manifest path is duplicated: {entry.path}")
        seen_paths.add(entry.path)
        if _is_excluded(entry.path, excluded_prefixes):
            excluded.append(entry.path)
            continue
        try:
            actual_size, actual_hash = _copy_entry(source, mirror, entry)
        except (MirrorCreationError, OSError) as error:
            mismatches.append(
                MirrorHashMismatch(entry.path, entry.sha256, None, str(error))
            )
            continue
        if actual_size != entry.size_bytes or actual_hash != entry.sha256:
            target = mirror.joinpath(*_safe_parts(entry.path))
            try:
                target.unlink()
            except OSError:
                pass
            mismatches.append(
                MirrorHashMismatch(
                    entry.path,
                    entry.sha256,
                    actual_hash,
                    "copied size or SHA-256 differs from the source manifest",
                )
            )
            continue
        copied_entries.append(entry)

    mirror_manifest = FileManifest(
        manifest_id=f"{source_manifest.manifest_id}-mirror",
        kind="mirror",
        created_at=source_manifest.created_at,
        entries=tuple(copied_entries),
    )
    blocked = (
        tuple(MirrorBlockedCheck(check_id) for check_id in dependent_check_ids)
        if mismatches
        else ()
    )
    return MirrorCopyResult(
        mirror_root=mirror,
        mirror_manifest=mirror_manifest,
        copied_paths=tuple(entry.path for entry in copied_entries),
        excluded_paths=tuple(excluded),
        mismatches=tuple(mismatches),
        blocked_checks=blocked,
    )
