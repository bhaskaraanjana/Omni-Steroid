"""Fail-closed write admission and post-execution audit records.

A command is admitted only when all declared writes are redirected into new
assessment-owned roots and a complete audit facility is available. Ambiguity is an
omission, never implicit permission.
"""

from __future__ import annotations

import ntpath
import posixpath
from dataclasses import dataclass
from hashlib import sha256
from pathlib import PureWindowsPath

from .model_types import WritePolicy
from .preservation import (
    AffectedContent,
    OmissionEvidence,
    OmittedDependentCheck,
    PlannedOperation,
)


@dataclass(frozen=True, slots=True)
class WriteAdmissionRequest:
    """Facts required to decide whether a planned writing operation may run."""

    operation: PlannedOperation
    write_policy: WritePolicy
    redirects_established: bool
    audit_available: bool
    preexisting_paths: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class WriteAdmissionDecision:
    """Exactly one admitted result or a complete omission record."""

    admitted: bool
    omission: OmissionEvidence | None

    def __post_init__(self) -> None:
        if self.admitted == (self.omission is not None):
            raise ValueError("admission must have exactly one decision outcome")


@dataclass(frozen=True, slots=True)
class WriteAuditRecord:
    """Observed writes and every containment failure found after execution."""

    observed_writes: tuple[str, ...]
    writes_outside_designated_roots: tuple[str, ...]
    preexisting_content_writes: tuple[str, ...]
    audit_complete: bool

    @property
    def compliant(self) -> bool:
        """Return true only for a complete audit containing no unsafe write."""
        return (
            self.audit_complete
            and not self.writes_outside_designated_roots
            and not self.preexisting_content_writes
        )


def _canonical_parts(path: str) -> tuple[str, tuple[str, ...]] | None:
    if not path or "\x00" in path:
        return None
    windows = PureWindowsPath(path)
    if windows.drive or "\\" in path:
        normalized = ntpath.normpath(path)
        if normalized in {".", ".."}:
            return None
        return "windows", tuple(part.casefold() for part in PureWindowsPath(normalized).parts)
    normalized = posixpath.normpath(path)
    if normalized in {".", ".."} or normalized.startswith("../"):
        return None
    return "posix", tuple(normalized.split("/"))


def path_is_within_designated_roots(
    path: str, designated_roots: tuple[str, ...]
) -> bool:
    """Check lexical containment for absolute Windows/POSIX and relative paths."""
    candidate = _canonical_parts(path)
    if candidate is None:
        return False
    style, candidate_parts = candidate
    for root in designated_roots:
        root_value = _canonical_parts(root)
        if root_value is None or root_value[0] != style:
            continue
        root_parts = root_value[1]
        if len(candidate_parts) > len(root_parts) and candidate_parts[: len(root_parts)] == root_parts:
            return True
    return False


def _same_path(left: str, right: str) -> bool:
    return _canonical_parts(left) == _canonical_parts(right)


def _omission(request: WriteAdmissionRequest, reason: str) -> OmissionEvidence:
    operation = request.operation
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
            OmittedDependentCheck(check_id)
            for check_id in operation.dependent_check_ids
        ),
    )


def evaluate_write_admission(request: WriteAdmissionRequest) -> WriteAdmissionDecision:
    """Admit only redirected, auditable, new writes below designated roots."""
    operation = request.operation
    reason: str | None = None
    if not operation.requested_admission:
        reason = "operation was not requested for admission"
    elif not request.redirects_established:
        reason = "complete write redirection could not be established"
    elif request.write_policy.audit_required and not request.audit_available:
        reason = "a complete write audit is unavailable"
    else:
        unsafe_targets = tuple(
            write.path
            for write in operation.writes
            if not path_is_within_designated_roots(
                write.path, request.write_policy.designated_roots
            )
            or any(_same_path(write.path, item) for item in request.preexisting_paths)
        )
        if unsafe_targets:
            reason = (
                "planned writes would affect pre-existing content or escape "
                f"designated roots: {', '.join(unsafe_targets)}"
            )
    if reason is not None:
        return WriteAdmissionDecision(False, _omission(request, reason))
    return WriteAdmissionDecision(True, None)


def audit_observed_writes(
    observed_write_paths: tuple[str, ...],
    write_policy: WritePolicy,
    *,
    preexisting_paths: tuple[str, ...],
    audit_complete: bool,
) -> WriteAuditRecord:
    """Classify every observed write without treating an incomplete audit as safe."""
    observed = tuple(dict.fromkeys(observed_write_paths))
    outside = tuple(
        path
        for path in observed
        if not path_is_within_designated_roots(path, write_policy.designated_roots)
    )
    preexisting = tuple(
        path
        for path in observed
        if any(_same_path(path, item) for item in preexisting_paths)
    )
    return WriteAuditRecord(observed, outside, preexisting, audit_complete)
