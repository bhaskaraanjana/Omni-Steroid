"""Hash the on-disk source tree into a manifest without carrying file contents.

This is the manifest stage of baseline collection: file bytes are streamed only into
SHA-256, so downstream reports receive hashes, sizes, and path-derived sensitivity
labels while the bytes themselves never leave this module.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable, Sequence
from pathlib import Path, PurePosixPath

from .baseline_collection_errors import BaselineCollectionError
from .baseline_models import FileManifest, ManifestEntry
from .model_types import ZonedTimestamp


def collect_source_manifest(
    root: Path,
    *,
    tracked_paths: Sequence[str],
    untracked_paths: Sequence[str],
    manifest_id: str,
    created_at: ZonedTimestamp,
    classify_sensitive_path: Callable[[str], str | None],
) -> FileManifest:
    """Build one source manifest over the tracked and untracked paths under ``root``.

    Paths that no longer resolve to a file or symlink are skipped. Sensitivity labelling
    is injected so the vocabulary stays with the collector that owns it, and so this
    module never inspects content to classify an entry.
    """
    tracked = set(tracked_paths)
    all_paths = sorted(tracked | set(untracked_paths))
    entries: list[ManifestEntry] = []
    for relative_path in all_paths:
        candidate = root.joinpath(*PurePosixPath(relative_path).parts)
        if not candidate.is_file() and not candidate.is_symlink():
            continue
        size, digest = hash_path(candidate)
        entries.append(
            ManifestEntry(
                path=relative_path,
                size_bytes=size,
                sha256=digest,
                tracked=relative_path in tracked,
                sensitive_category=classify_sensitive_path(relative_path),
            )
        )
    return FileManifest(manifest_id, "source", created_at, tuple(entries))


def hash_path(path: Path) -> tuple[int, str]:
    """Return the byte size and SHA-256 of one file, or of a symlink's target text.

    A symlink is hashed by its target bytes rather than followed, so the manifest never
    reads through a link out of the observed tree. Raises ``BaselineCollectionError``
    when a pre-existing path cannot be read.
    """
    digest = hashlib.sha256()
    size = 0
    try:
        if path.is_symlink():
            payload = os.fsencode(os.readlink(path))
            digest.update(payload)
            return len(payload), digest.hexdigest()
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                size += len(chunk)
                digest.update(chunk)
    except OSError as error:
        raise BaselineCollectionError(
            f"could not hash pre-existing path {path}: {error}"
        ) from error
    return size, digest.hexdigest()
