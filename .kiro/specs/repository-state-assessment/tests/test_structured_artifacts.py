"""Exercise strict structured-evidence validation and assessment-owned writes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from assessor import (
    ArtifactDestination,
    ArtifactPathError,
    ArtifactPersistenceError,
    ArtifactSchemaError,
    AssessmentRunPaths,
    StructuredArtifactStore,
    StructuredArtifactValidator,
)


def valid_evidence_record() -> dict[str, object]:
    """Return a complete synthetic EvidenceRecord JSON value."""
    return {
        "evidence_id": "evidence-python-lint",
        "check_id": "python-lint",
        "plane": "Python_Engine",
        "scope": "repository-defined lint",
        "exact_argv": ["uv", "run", "ruff", "check", "."],
        "numbered_procedure": None,
        "source_command_locations": [
            {"path": "Makefile", "start_line": 10, "end_line": 10}
        ],
        "cwd": "mirror",
        "started_at": "2026-07-08T09:10:11+00:00",
        "duration_ms": 12,
        "termination": {
            "kind": "exited",
            "exit_code": 0,
            "signal": None,
            "timeout_ms": 30000,
        },
        "prerequisites": [],
        "environment": {
            "os": {"name": "Windows", "version": "11", "build": "26100"},
            "hardware": [],
            "tool_versions": [],
            "safe_variable_names": ["PYTHONUTF8"],
        },
        "source_revision": "a" * 40,
        "stdout_ref": "raw/python-lint.stdout",
        "stderr_ref": "raw/python-lint.stderr",
        "relevant_output": ["All checks passed"],
        "warnings": [],
        "test_counts": {
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "deselected": 0,
            "ignored": 0,
        },
        "measurements": [],
        "artifacts": [{"kind": "log", "path": "logs/lint.txt", "absent": False}],
        "network_observation_ref": None,
        "process_ownership": {
            "ownership_token": "run-token",
            "mechanism": "job-object",
            "processes": [],
            "cleanup_completed": True,
        },
        "write_audit_ref": "audit/python-lint.json",
        "primary_status": "Verified_Working",
        "status_basis": "fresh command exited successfully",
        "rerun": {
            "prerequisites": ["uv"],
            "exact_argv": ["uv", "run", "ruff", "check", "."],
            "numbered_procedure": None,
            "expected_observable": "exit code 0",
        },
    }


def test_json_and_jsonl_evidence_are_strictly_validated() -> None:
    validator = StructuredArtifactValidator()
    record = valid_evidence_record()

    assert validator.validate_json(json.dumps(record)) == record
    assert validator.validate_jsonl(json.dumps(record) + "\n" + json.dumps(record)) == (
        record,
        record,
    )

    unexpected_field = record.copy()
    unexpected_field["secret"] = "must not be accepted"
    with pytest.raises(ArtifactSchemaError, match="unexpected property"):
        validator.validate_evidence_record(unexpected_field)


def test_every_missing_evidence_field_is_rejected() -> None:
    validator = StructuredArtifactValidator()
    record = valid_evidence_record()

    for field_name in record:
        incomplete = record.copy()
        del incomplete[field_name]
        with pytest.raises(ArtifactSchemaError, match=field_name):
            validator.validate_evidence_record(incomplete)


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("evidence_id", ""),
        ("duration_ms", -1),
        ("started_at", "2026-07-08T09:10:11"),
        ("primary_status", "passed"),
    ],
)
def test_invalid_evidence_field_values_are_rejected(
    field_name: str, invalid_value: object
) -> None:
    validator = StructuredArtifactValidator()
    invalid = valid_evidence_record()
    invalid[field_name] = invalid_value

    with pytest.raises(ArtifactSchemaError, match=field_name):
        validator.validate_evidence_record(invalid)


def test_typed_zero_measurement_is_valid_evidence_not_missing() -> None:
    validator = StructuredArtifactValidator()
    record = valid_evidence_record()
    record["measurements"] = [
        {
            "name": "stt_word_error_rate",
            "value": 0.0,
            "unit": "percent",
            "assessed_scope": "labelled local speech corpus",
        }
    ]

    validated = validator.validate_evidence_record(record)

    assert validated["measurements"] == record["measurements"]
    assert validated["measurements"][0]["value"] == 0.0  # type: ignore[index]


@pytest.mark.parametrize(
    "document, expected_message",
    [
        ('{"evidence_id":"first","evidence_id":"second"}', "duplicate JSON property"),
        ("{}\n\n{}", "blank line"),
        ("", "at least one evidence record"),
    ],
)
def test_json_boundaries_reject_ambiguous_or_empty_input(
    document: str, expected_message: str
) -> None:
    validator = StructuredArtifactValidator()

    with pytest.raises(ArtifactSchemaError, match=expected_message):
        if "\n" in document or not document:
            validator.validate_jsonl(document)
        else:
            validator.validate_json(document)


def test_run_paths_are_deterministic_new_and_collision_safe(tmp_path: Path) -> None:
    spec_root = tmp_path / "spec"
    temp_base = tmp_path / "temp"
    spec_root.mkdir()
    temp_base.mkdir()

    paths = AssessmentRunPaths.allocate(
        run_id="20260708T091011Z-a1b2c3d4",
        spec_root=spec_root,
        temporary_base=temp_base,
    )

    assert paths.temporary_root == (
        temp_base.resolve()
        / "omni-repository-assessment"
        / "20260708T091011Z-a1b2c3d4"
    )
    assert paths.permanent_root == (
        spec_root.resolve()
        / "assessment-output"
        / "20260708T091011Z-a1b2c3d4"
    )
    assert paths.temporary_root.is_dir()
    assert paths.permanent_root.is_dir()

    with pytest.raises(ArtifactPathError, match="already exists"):
        AssessmentRunPaths.allocate(
            run_id=paths.run_id,
            spec_root=spec_root,
            temporary_base=temp_base,
        )


@pytest.mark.parametrize(
    "unsafe_path",
    [
        "../outside.json",
        "nested/../../outside.json",
        "/absolute/outside.json",
        "C:\\outside\\record.json",
        "\\\\server\\share\\record.json",
        ".",
        "",
    ],
)
def test_relative_artifact_paths_cannot_escape_designated_roots(
    tmp_path: Path, unsafe_path: str
) -> None:
    spec_root = tmp_path / "spec"
    temp_base = tmp_path / "temp"
    spec_root.mkdir()
    temp_base.mkdir()
    paths = AssessmentRunPaths.allocate("safe-run", spec_root, temp_base)

    with pytest.raises(ArtifactPathError):
        paths.resolve_for_write(ArtifactDestination.TEMPORARY, unsafe_path)


def test_store_validates_before_exclusive_sanitized_persistence(tmp_path: Path) -> None:
    spec_root = tmp_path / "spec"
    temp_base = tmp_path / "temp"
    spec_root.mkdir()
    temp_base.mkdir()
    paths = AssessmentRunPaths.allocate("artifact-run", spec_root, temp_base)
    store = StructuredArtifactStore(paths)
    record = valid_evidence_record()

    raw_path = store.write_json(
        "raw/evidence.json",
        record,
        destination=ArtifactDestination.TEMPORARY,
        sanitized=False,
    )
    assert raw_path.is_relative_to(paths.temporary_root)

    with pytest.raises(ArtifactPersistenceError, match="unsanitized"):
        store.write_json(
            "evidence/unsafe.json",
            record,
            destination=ArtifactDestination.PERMANENT,
            sanitized=False,
        )
    assert not (paths.permanent_root / "evidence" / "unsafe.json").exists()

    permanent_path = store.write_json(
        "evidence/python-lint.json",
        record,
        destination=ArtifactDestination.PERMANENT,
        sanitized=True,
    )
    assert permanent_path.is_relative_to(paths.permanent_root)
    assert json.loads(permanent_path.read_text(encoding="utf-8")) == record

    with pytest.raises(ArtifactPathError, match="already exists"):
        store.write_json(
            "evidence/python-lint.json",
            record,
            destination=ArtifactDestination.PERMANENT,
            sanitized=True,
        )


def test_invalid_records_are_never_persisted(tmp_path: Path) -> None:
    spec_root = tmp_path / "spec"
    temp_base = tmp_path / "temp"
    spec_root.mkdir()
    temp_base.mkdir()
    paths = AssessmentRunPaths.allocate("invalid-record-run", spec_root, temp_base)
    store = StructuredArtifactStore(paths)
    invalid_record = valid_evidence_record()
    invalid_record["duration_ms"] = -1

    with pytest.raises(ArtifactSchemaError, match="duration_ms"):
        store.write_jsonl(
            "evidence/records.jsonl",
            [valid_evidence_record(), invalid_record],
            destination=ArtifactDestination.PERMANENT,
            sanitized=True,
        )

    assert not (paths.permanent_root / "evidence" / "records.jsonl").exists()
