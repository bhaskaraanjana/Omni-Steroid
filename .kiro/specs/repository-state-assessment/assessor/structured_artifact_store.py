"""Persist validated evidence only within assessment-owned run roots.

Raw records may exist only in the temporary root. Permanent output requires an
explicit sanitized provenance flag and is created exclusively without overwrites.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from contextlib import suppress
from pathlib import Path

from .assessment_paths import (
    ArtifactDestination,
    ArtifactPathError,
    ArtifactPersistenceError,
    AssessmentRunPaths,
)
from .structured_artifact_validation import StructuredArtifactValidator


class StructuredArtifactStore:
    """Validate then exclusively persist normalized JSON or JSONL evidence."""

    def __init__(
        self,
        paths: AssessmentRunPaths,
        validator: StructuredArtifactValidator | None = None,
    ) -> None:
        """Bind writes to one allocated run's designated roots."""
        self._paths = paths
        self._validator = validator or StructuredArtifactValidator()

    def write_json(
        self,
        relative_path: str,
        record: Mapping[str, object],
        *,
        destination: ArtifactDestination,
        sanitized: bool,
    ) -> Path:
        """Validate and write one evidence record as canonical JSON."""
        self._require_persistence_allowed(destination, sanitized)
        self._require_suffix(relative_path, ".json")
        validated = self._validator.validate_evidence_record(dict(record))
        serialized = self._validator.canonical_json(validated)
        return self._write_exclusive(destination, relative_path, serialized)

    def write_jsonl(
        self,
        relative_path: str,
        records: Iterable[Mapping[str, object]],
        *,
        destination: ArtifactDestination,
        sanitized: bool,
    ) -> Path:
        """Validate and write a non-empty evidence sequence as canonical JSONL."""
        self._require_persistence_allowed(destination, sanitized)
        self._require_suffix(relative_path, ".jsonl")
        validated = self._validator.validate_evidence_collection(tuple(records))
        serialized = self._validator.canonical_jsonl(validated)
        return self._write_exclusive(destination, relative_path, serialized)

    @staticmethod
    def _require_persistence_allowed(
        destination: ArtifactDestination, sanitized: bool
    ) -> None:
        if not isinstance(destination, ArtifactDestination):
            raise ArtifactPathError("artifact destination must be explicit")
        if not isinstance(sanitized, bool):
            raise ArtifactPersistenceError("sanitized provenance must be boolean")
        if destination is ArtifactDestination.PERMANENT and not sanitized:
            # Requirement 7.11: raw or uncertain records never enter report output.
            raise ArtifactPersistenceError(
                "permanent persistence of an unsanitized artifact is forbidden"
            )

    @staticmethod
    def _require_suffix(relative_path: str, expected_suffix: str) -> None:
        if not isinstance(relative_path, str) or not relative_path.lower().endswith(
            expected_suffix
        ):
            raise ArtifactPathError(
                f"structured artifact path must end with {expected_suffix}"
            )

    def _write_exclusive(
        self,
        destination: ArtifactDestination,
        relative_path: str,
        serialized: str,
    ) -> Path:
        target = self._paths.resolve_for_write(destination, relative_path)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise ArtifactPathError(f"could not create artifact directory: {error}") from error

        # Resolve again after parent creation to detect a raced symlink escape.
        target = self._paths.resolve_for_write(destination, relative_path)
        created = False
        try:
            with target.open("x", encoding="utf-8", newline="\n") as artifact_file:
                created = True
                artifact_file.write(serialized)
                artifact_file.flush()
                os.fsync(artifact_file.fileno())
        except FileExistsError as error:
            raise ArtifactPathError(f"artifact path already exists: {target}") from error
        except OSError as error:
            if created:
                with suppress(OSError):
                    target.unlink()
            raise ArtifactPersistenceError(f"artifact write failed: {error}") from error
        return target
