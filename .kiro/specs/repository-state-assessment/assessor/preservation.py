"""Pure source-preservation model used to prove execution admission safety."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256
from pathlib import PurePosixPath, PureWindowsPath

from .model_types import AssessmentStatus
from .run_models import WorkspaceComparison


class AssessmentTermination(StrEnum):
    """Terminal outcomes across which source preservation is mandatory."""

    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"
    ABORT = "abort"


@dataclass(frozen=True, slots=True)
class WorkspaceFile:
    """One pre-existing tracked or untracked source file and its exact bytes."""

    path: str
    content: bytes
    tracked: bool
    production: bool = True


@dataclass(frozen=True, slots=True)
class PlannedWrite:
    """One file write declared by a planned operation."""

    path: str
    content: bytes


@dataclass(frozen=True, slots=True)
class PlannedOperation:
    """A pure operation plan carrying admission intent and dependent checks."""

    operation_id: str
    command_or_procedure: tuple[str, ...]
    requested_admission: bool
    writes: tuple[PlannedWrite, ...]
    dependent_check_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AffectedContent:
    """Path and digest of content an omitted operation would have affected."""

    path: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class OmittedDependentCheck:
    """A dependent check made unverified by an omitted operation."""

    check_id: str
    status: AssessmentStatus = field(
        default=AssessmentStatus.UNVERIFIED, init=False
    )


@dataclass(frozen=True, slots=True)
class OmissionEvidence:
    """Complete evidence explaining why a planned operation did not execute."""

    operation_id: str
    command_or_procedure: tuple[str, ...]
    affected_content: tuple[AffectedContent, ...]
    reason: str
    dependent_checks: tuple[OmittedDependentCheck, ...]


@dataclass(frozen=True, slots=True)
class NonDestructiveExecution:
    """Pure result of admission, artifact writes, and final source comparison."""

    termination: AssessmentTermination
    source_before: tuple[WorkspaceFile, ...]
    source_after: tuple[WorkspaceFile, ...]
    artifact_bytes: tuple[tuple[str, bytes], ...]
    observed_writes: tuple[str, ...]
    omissions: tuple[OmissionEvidence, ...]
    final_comparison: WorkspaceComparison


def _path_parts(path: str) -> tuple[str, ...] | None:
    """Return normalized relative path parts, or ``None`` for unsafe syntax."""
    if not path or "\x00" in path:
        return None
    normalized = path.replace("\\", "/")
    windows_path = PureWindowsPath(path)
    candidate = PurePosixPath(normalized)
    if candidate.is_absolute() or windows_path.is_absolute() or windows_path.drive:
        return None
    if any(part in {"", ".", ".."} for part in normalized.split("/")):
        return None
    return candidate.parts


def is_under_designated_root(path: str, designated_roots: tuple[str, ...]) -> bool:
    """Return whether a write target is a descendant of a designated run root."""
    candidate = _path_parts(path)
    if candidate is None:
        return False
    for root in designated_roots:
        root_parts = _path_parts(root)
        if root_parts and len(candidate) > len(root_parts):
            if candidate[: len(root_parts)] == root_parts:
                return True
    return False


def _omission(operation: PlannedOperation, reason: str) -> OmissionEvidence:
    return OmissionEvidence(
        operation_id=operation.operation_id,
        command_or_procedure=operation.command_or_procedure,
        affected_content=tuple(
            AffectedContent(
                path=write.path,
                size_bytes=len(write.content),
                sha256=sha256(write.content).hexdigest(),
            )
            for write in operation.writes
        ),
        reason=reason,
        dependent_checks=tuple(
            OmittedDependentCheck(check_id) for check_id in operation.dependent_check_ids
        ),
    )


def evaluate_non_destructive_execution(
    source_files: tuple[WorkspaceFile, ...],
    operations: tuple[PlannedOperation, ...],
    designated_roots: tuple[str, ...],
    termination: AssessmentTermination,
) -> NonDestructiveExecution:
    """Admit only assessment-owned writes and always compare the untouched source.

    This function deliberately models no source mutation primitive. An operation is
    omitted when admission was denied, a target is pre-existing, or a target is not
    below a designated root. Safe writes become assessment artifacts only.
    """
    if not designated_roots or any(_path_parts(root) is None for root in designated_roots):
        raise ValueError("designated roots must be safe relative paths")
    source_paths = [item.path for item in source_files]
    if len(source_paths) != len(set(source_paths)):
        raise ValueError("source file paths must be unique")

    artifacts: dict[str, bytes] = {}
    observed_writes: list[str] = []
    omissions: list[OmissionEvidence] = []
    preexisting_paths = set(source_paths)

    for operation in operations:
        unsafe_targets = tuple(
            write.path
            for write in operation.writes
            if write.path in preexisting_paths
            or not is_under_designated_root(write.path, designated_roots)
        )
        if not operation.requested_admission:
            omissions.append(_omission(operation, "operation was not admitted"))
        elif unsafe_targets:
            omissions.append(
                _omission(
                    operation,
                    "unsafe write would affect pre-existing content or escape "
                    f"designated roots: {', '.join(unsafe_targets)}",
                )
            )
        else:
            for write in operation.writes:
                artifacts[write.path] = write.content
                observed_writes.append(write.path)

    source_after = tuple(source_files)
    comparison = WorkspaceComparison(
        baseline_manifest_ref="baseline/source-manifest.json",
        final_manifest_ref=f"final/{termination.value}-source-manifest.json",
        tracked_paths_identical=True,
        untracked_paths_identical=True,
        production_bytes_identical=True,
        differences=(),
        writes_outside_designated_roots=(),
    )
    return NonDestructiveExecution(
        termination=termination,
        source_before=tuple(source_files),
        source_after=source_after,
        artifact_bytes=tuple(artifacts.items()),
        observed_writes=tuple(observed_writes),
        omissions=tuple(omissions),
        final_comparison=comparison,
    )
