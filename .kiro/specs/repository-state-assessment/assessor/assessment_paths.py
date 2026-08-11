"""Allocate and guard assessment-owned temporary and permanent filesystem roots.

All writes are relative to newly created run roots. Cross-platform traversal,
pre-existing targets, symlink escapes, and unsanitized permanent writes fail closed.
"""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PureWindowsPath


_TEMPORARY_NAMESPACE = "omni-repository-assessment"
_PERMANENT_DIRECTORY = "assessment-output"
_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class ArtifactDestination(StrEnum):
    """The only two roots to which assessment artifacts may be written."""

    TEMPORARY = "temporary"
    PERMANENT = "permanent"


class ArtifactPathError(ValueError):
    """Raised when allocation or a requested artifact path is unsafe."""


class ArtifactPersistenceError(PermissionError):
    """Raised when artifact sensitivity forbids the requested persistence."""


@dataclass(frozen=True, slots=True)
class AssessmentRunPaths:
    """New deterministic roots owned exclusively by one assessment run."""

    run_id: str
    temporary_root: Path
    permanent_root: Path

    @classmethod
    def allocate(
        cls,
        run_id: str,
        spec_root: Path,
        temporary_base: Path | None = None,
    ) -> "AssessmentRunPaths":
        """Create both run roots exclusively, rolling back a partial allocation.

        ``run_id`` maps deterministically to both roots. Existing run roots are
        rejected rather than reused because prior content is never assessment-owned
        by the current run.
        """
        cls._validate_run_id(run_id)
        resolved_spec_root = cls._existing_directory(spec_root, "spec root")
        resolved_temp_base = cls._existing_directory(
            temporary_base or Path(tempfile.gettempdir()), "temporary base"
        )
        temporary_parent = cls._prepare_parent(
            resolved_temp_base / _TEMPORARY_NAMESPACE
        )
        permanent_parent = cls._prepare_parent(
            resolved_spec_root / _PERMANENT_DIRECTORY
        )
        temporary_root = temporary_parent / run_id
        permanent_root = permanent_parent / run_id

        for candidate in (temporary_root, permanent_root):
            if os.path.lexists(candidate):
                raise ArtifactPathError(f"assessment run path already exists: {candidate}")

        try:
            temporary_root.mkdir()
            try:
                permanent_root.mkdir()
            except OSError:
                temporary_root.rmdir()
                raise
        except FileExistsError as error:
            raise ArtifactPathError("assessment run path already exists") from error
        except OSError as error:
            raise ArtifactPathError(f"could not allocate assessment run paths: {error}") from error

        return cls(run_id, temporary_root.resolve(), permanent_root.resolve())

    def resolve_for_write(
        self, destination: ArtifactDestination, relative_path: str
    ) -> Path:
        """Resolve a new relative target and prove it remains in its selected root."""
        if not isinstance(destination, ArtifactDestination):
            raise ArtifactPathError("artifact destination must be explicit")
        segments = self._validated_relative_segments(relative_path)
        root = self._root(destination)
        target = root.joinpath(*segments).resolve(strict=False)
        if not target.is_relative_to(root):
            raise ArtifactPathError("artifact path escapes its designated root")
        if os.path.lexists(target):
            raise ArtifactPathError(f"artifact path already exists: {target}")
        return target

    def _root(self, destination: ArtifactDestination) -> Path:
        return (
            self.temporary_root
            if destination is ArtifactDestination.TEMPORARY
            else self.permanent_root
        )

    @staticmethod
    def _validate_run_id(run_id: str) -> None:
        if not isinstance(run_id, str) or not _RUN_ID_PATTERN.fullmatch(run_id):
            raise ArtifactPathError("run_id must contain only safe ASCII path characters")
        if run_id in {".", ".."} or run_id.endswith("."):
            raise ArtifactPathError("run_id cannot be a traversal or aliased path")

    @staticmethod
    def _existing_directory(path: Path, label: str) -> Path:
        candidate = Path(path)
        if candidate.is_symlink():
            raise ArtifactPathError(f"{label} cannot be a symbolic link")
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as error:
            raise ArtifactPathError(f"{label} must already exist") from error
        if not resolved.is_dir():
            raise ArtifactPathError(f"{label} must be a directory")
        return resolved

    @staticmethod
    def _prepare_parent(path: Path) -> Path:
        if path.is_symlink():
            raise ArtifactPathError(f"assessment parent cannot be a symbolic link: {path}")
        try:
            path.mkdir(parents=False, exist_ok=True)
        except OSError as error:
            raise ArtifactPathError(f"could not create assessment parent: {path}") from error
        if path.is_symlink() or not path.is_dir():
            raise ArtifactPathError(f"assessment parent must be a real directory: {path}")
        return path.resolve(strict=True)

    @staticmethod
    def _validated_relative_segments(relative_path: str) -> tuple[str, ...]:
        if not isinstance(relative_path, str) or not relative_path or "\x00" in relative_path:
            raise ArtifactPathError("artifact path must be non-empty text")
        normalized = relative_path.replace("\\", "/")
        windows_path = PureWindowsPath(relative_path)
        if normalized.startswith("/") or windows_path.is_absolute() or windows_path.drive:
            raise ArtifactPathError("artifact path must be relative")
        segments = tuple(normalized.split("/"))
        if any(segment in {"", ".", ".."} for segment in segments):
            raise ArtifactPathError("artifact path contains traversal or ambiguous segments")
        if any(":" in segment for segment in segments):
            raise ArtifactPathError("artifact path cannot contain a drive or alternate stream")
        return segments
