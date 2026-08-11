"""Validate and release empirical Python network-containment proofs."""

from __future__ import annotations

import hmac
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from .contained_process_protocols import NetworkContainmentLease

_PYTHON_EXECUTABLE = re.compile(
    r"python(?:w)?(?:\d+(?:\.\d+)*)?(?:\.exe)?", re.IGNORECASE
)


class ProofStatus(StrEnum):
    """Current classification of one lease's quarantined proof marker."""

    MISSING = "missing"
    VALID = "valid"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class ContainmentProof:
    """Identity reported by the interpreter whose startup guard loaded."""

    pid: int
    interpreter: str


@dataclass(frozen=True, slots=True)
class ProofInspection:
    """Fail-closed marker classification with identity only when valid."""

    status: ProofStatus
    proof: ContainmentProof | None = None


@dataclass(frozen=True, slots=True)
class ProofDecision:
    """One polling decision for whether guarded user code may be released."""

    granted: bool
    blocked_reason: str | None = None


def inspect_containment_proof(
    temporary_root: Path,
    lease: NetworkContainmentLease,
    owned_processes: Mapping[int, str],
) -> ProofInspection:
    """Accept one exact current-lease marker from an observed owned interpreter."""
    if not lease.proof_required:  # Control: external adapters attest independently.
        return ProofInspection(ProofStatus.VALID)
    if not lease.observation_ref or not lease.proof_token:  # Control: complete lease.
        return ProofInspection(ProofStatus.INVALID)
    try:
        root = temporary_root.resolve(strict=True)  # Control: assessor-owned root.
        marker = root / lease.observation_ref  # Control: lease-bound marker only.
        if marker.is_symlink():  # Control: reject marker redirection.
            return ProofInspection(ProofStatus.INVALID)
        resolved = marker.resolve(strict=True)  # Control: existing proof object.
        observation_root = root / "network-containment" / "observations"
        if not resolved.is_relative_to(observation_root):  # Control: quarantine boundary.
            return ProofInspection(ProofStatus.INVALID)
        text = resolved.read_text(encoding="utf-8")  # Control: bounded lease evidence.
    except (OSError, UnicodeError, ValueError):
        return ProofInspection(ProofStatus.INVALID)
    if not text:
        return ProofInspection(ProofStatus.MISSING)
    records: list[dict[object, object]] = []
    try:
        for line in text.splitlines():
            payload = json.loads(line)
            if not isinstance(payload, dict):  # Control: structured evidence only.
                return ProofInspection(ProofStatus.INVALID)
            records.append(payload)
    except (json.JSONDecodeError, UnicodeError):
        return ProofInspection(ProofStatus.INVALID)
    proofs = [item for item in records if item.get("kind") == "containment_proof"]
    if len(proofs) != 1:  # Control: stale or ambiguous markers fail closed.
        return ProofInspection(ProofStatus.INVALID)
    marker_payload = proofs[0]
    token = marker_payload.get("token")
    pid = marker_payload.get("pid")
    interpreter = marker_payload.get("interpreter")
    if not isinstance(token, str) or not hmac.compare_digest(  # Control: lease identity.
        token, lease.proof_token
    ):
        return ProofInspection(ProofStatus.INVALID)
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:  # Control: real PID.
        return ProofInspection(ProofStatus.INVALID)
    observed_executable = owned_processes.get(pid)
    if observed_executable is None:  # Control: proof must come from this owned process tree.
        return ProofInspection(ProofStatus.MISSING)
    if not isinstance(interpreter, str) or not interpreter:  # Control: interpreter identity.
        return ProofInspection(ProofStatus.INVALID)
    try:
        executable = Path(interpreter)
        if not executable.is_absolute():  # Control: unambiguous interpreter path.
            return ProofInspection(ProofStatus.INVALID)
        reported = executable.resolve(strict=True)  # Control: reported interpreter exists.
        observed = Path(observed_executable).resolve(strict=True)  # Control: captured process.
        same_python_runtime = (
            _PYTHON_EXECUTABLE.fullmatch(reported.name) is not None
            and _PYTHON_EXECUTABLE.fullmatch(observed.name) is not None
        )
        if reported != observed and not same_python_runtime:
            return ProofInspection(ProofStatus.INVALID)  # Control: reject non-Python attester.
    except (OSError, ValueError):
        return ProofInspection(ProofStatus.INVALID)
    return ProofInspection(ProofStatus.VALID, ContainmentProof(pid, interpreter))


def decide_containment_proof(
    temporary_root: Path,
    lease: NetworkContainmentLease,
    owned_processes: Mapping[int, str],
    elapsed_ms: int,
    process_exited: bool,
    deadline_ms: int,
) -> ProofDecision:
    """Poll proof and release only a uniquely identified owned interpreter."""
    inspection = inspect_containment_proof(temporary_root, lease, owned_processes)
    if inspection.status is ProofStatus.VALID:
        try:
            release_proven_interpreter(temporary_root, lease)
            return ProofDecision(True)  # Control: valid marker gates checked user code.
        except OSError:
            return ProofDecision(False, "containment proof release failed")
    if inspection.status is ProofStatus.INVALID:
        return ProofDecision(False, "containment proof marker is invalid or ambiguous")
    if process_exited or elapsed_ms >= deadline_ms:
        return ProofDecision(False, "containment proof marker was not observed")
    return ProofDecision(False)


def release_proven_interpreter(
    temporary_root: Path, lease: NetworkContainmentLease
) -> None:
    """Release guarded Python user code only after its marker was validated."""
    if not lease.release_ref or not lease.proof_token:  # Control: complete handshake.
        raise OSError("containment proof release metadata is incomplete")
    root = temporary_root.resolve(strict=True)  # Control: assessor-owned root.
    release = root / lease.release_ref  # Control: lease-specific release only.
    release_root = root / "network-containment" / "releases"
    parent = release.parent.resolve(strict=True)  # Control: pre-created release root.
    if parent != release_root.resolve(strict=True):  # Control: no release-path escape.
        raise OSError("containment proof release path escaped quarantine")
    with release.open("x", encoding="utf-8", newline="\n") as stream:  # Control: one release.
        stream.write(lease.proof_token + "\n")  # Control: bind release to current lease.
