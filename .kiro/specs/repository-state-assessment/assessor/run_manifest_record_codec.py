"""Encode and strictly decode append-only run-manifest records.

This codec sits below the manifest store and rejects missing or unrecognised values,
preventing malformed recovery input from being interpreted as a successful gate.
"""

from __future__ import annotations

import json
from datetime import datetime

from .assessment_phase_gates import AssessmentPhase, GateStatus
from .model_types import OwnedProcess, ZonedTimestamp
from .run_manifest_records import (
    CheckState,
    ManifestCorruption,
    ManifestEvent,
    ManifestRecord,
    RunIdentity,
)
from .run_models import PhaseState


def encode_manifest_record(record: ManifestRecord) -> bytes:
    """Return one deterministic UTF-8 JSONL record."""
    process = record.process
    identity = record.identity
    value: dict[str, object] = {
        "sequence": record.sequence,
        "record_id": record.record_id,
        "run_id": record.run_id,
        "event": record.event.value,
        "recorded_at": record.recorded_at.value.isoformat(),
        "phase": record.phase.value if record.phase else None,
        "phase_state": record.phase_state.value if record.phase_state else None,
        "gate": record.gate.value if record.gate else None,
        "check_id": record.check_id,
        "check_state": record.check_state.value if record.check_state else None,
        "artifact_refs": list(record.artifact_refs),
        "reason": record.reason,
        "supersedes": record.supersedes,
        "comparison_preserved": record.comparison_preserved,
        "execution_admitted": record.execution_admitted,
        "process": (
            {
                "pid": process.pid,
                "created_at": process.created_at.value.isoformat(),
                "executable": process.executable,
                "parent_pid": process.parent_pid,
            }
            if process
            else None
        ),
        "identity": (
            {
                "run_id": identity.run_id,
                "source_repository_root": identity.source_repository_root,
                "temporary_run_root": identity.temporary_run_root,
                "permanent_output_root": identity.permanent_output_root,
                "ownership_token": identity.ownership_token,
            }
            if identity
            else None
        ),
    }
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode("utf-8")


def decode_manifest_record(line: bytes, index: int) -> ManifestRecord:
    """Decode one record with strict types and fail-closed enum recognition."""
    try:
        decoded: object = json.loads(line)
        if not isinstance(decoded, dict):
            raise ValueError("record is not an object")
        phase = _optional_text(decoded, "phase")
        phase_state = _optional_text(decoded, "phase_state")
        gate = _optional_text(decoded, "gate")
        check_state = _optional_text(decoded, "check_state")
        refs = decoded.get("artifact_refs")
        if not isinstance(refs, list) or not all(isinstance(item, str) for item in refs):
            raise ValueError("artifact_refs must be a text array")
        comparison = decoded.get("comparison_preserved")
        if comparison is not None and not isinstance(comparison, bool):
            raise ValueError("comparison_preserved must be boolean or null")
        admission = decoded.get("execution_admitted")
        if admission is not None and not isinstance(admission, bool):
            raise ValueError("execution_admitted must be boolean or null")
        return ManifestRecord(
            sequence=_integer(decoded, "sequence"),
            record_id=_text(decoded, "record_id"),
            run_id=_text(decoded, "run_id"),
            event=ManifestEvent(_text(decoded, "event")),
            recorded_at=ZonedTimestamp(datetime.fromisoformat(_text(decoded, "recorded_at"))),
            phase=AssessmentPhase(phase) if phase else None,
            phase_state=PhaseState(phase_state) if phase_state else None,
            gate=GateStatus(gate) if gate else None,
            check_id=_optional_text(decoded, "check_id"),
            check_state=CheckState(check_state) if check_state else None,
            artifact_refs=tuple(refs),
            reason=_optional_text(decoded, "reason"),
            supersedes=_optional_text(decoded, "supersedes"),
            process=_process(decoded.get("process")),
            identity=_identity(decoded.get("identity")),
            comparison_preserved=comparison,
            execution_admitted=admission,
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ManifestCorruption(f"invalid manifest record at line {index + 1}: {error}") from error


def _text(value: dict[object, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"{key} must be non-empty text")
    return item


def _optional_text(value: dict[object, object], key: str) -> str | None:
    item = value.get(key)
    if item is not None and not isinstance(item, str):
        raise ValueError(f"{key} must be text or null")
    return item


def _integer(value: dict[object, object], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool):
        raise ValueError(f"{key} must be an integer")
    return item


def _identity(value: object) -> RunIdentity | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("identity must be an object or null")
    return RunIdentity(
        _text(value, "run_id"),
        _text(value, "source_repository_root"),
        _text(value, "temporary_run_root"),
        _text(value, "permanent_output_root"),
        _text(value, "ownership_token"),
    )


def _process(value: object) -> OwnedProcess | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("process must be an object or null")
    parent = value.get("parent_pid")
    if parent is not None and (not isinstance(parent, int) or isinstance(parent, bool)):
        raise ValueError("parent_pid must be an integer or null")
    return OwnedProcess(
        _integer(value, "pid"),
        ZonedTimestamp(datetime.fromisoformat(_text(value, "created_at"))),
        _text(value, "executable"),
        parent,
    )
