"""Machine-readable schemas for normalized JSON and JSONL evidence artifacts.

The schemas are intentionally strict: missing and unknown fields fail admission so
incomplete evidence cannot silently enter the permanent assessment report.
"""

from __future__ import annotations

from typing import Any

from .execution_models import TerminationKind
from .model_types import AssessmentStatus, MeasurementUnit, VerificationPlane

JsonSchema = dict[str, Any]


def _array(items: JsonSchema) -> JsonSchema:
    return {"type": "array", "items": items}


def _non_empty_array(items: JsonSchema) -> JsonSchema:
    return {"type": "array", "items": items, "minItems": 1}


def _nullable(schema: JsonSchema) -> JsonSchema:
    return {"oneOf": [schema, {"type": "null"}]}


def _object(properties: dict[str, JsonSchema], *, required: tuple[str, ...] | None = None) -> JsonSchema:
    return {
        "type": "object",
        "properties": properties,
        "required": list(required or properties),
        "additionalProperties": False,
    }


STRING: JsonSchema = {"type": "string"}
NON_EMPTY_STRING: JsonSchema = {"type": "string", "minLength": 1}
NON_NEGATIVE_INTEGER: JsonSchema = {"type": "integer", "minimum": 0}
NULLABLE_STRING = _nullable(STRING)
STRING_ARRAY = _array(STRING)

SOURCE_LOCATION_SCHEMA = _object(
    {
        "path": NON_EMPTY_STRING,
        "start_line": {"type": "integer", "minimum": 1},
        "end_line": {"type": "integer", "minimum": 1},
    }
)

TERMINATION_SCHEMA = _object(
    {
        "kind": {"type": "string", "enum": [item.value for item in TerminationKind]},
        "exit_code": _nullable({"type": "integer"}),
        "signal": _nullable({"type": "integer"}),
        "timeout_ms": _nullable(NON_NEGATIVE_INTEGER),
    }
)

PREREQUISITE_SCHEMA = _object(
    {
        "name": NON_EMPTY_STRING,
        "detection_procedure": STRING_ARRAY,
        "available": _nullable({"type": "boolean"}),
        "evidence_ref": NULLABLE_STRING,
    }
)

OS_SCHEMA = _object(
    {"name": NON_EMPTY_STRING, "version": NON_EMPTY_STRING, "build": NULLABLE_STRING}
)

HARDWARE_SCHEMA = _object(
    {
        "category": NON_EMPTY_STRING,
        "name": NON_EMPTY_STRING,
        "attributes": _array(
            {"type": "array", "items": STRING, "minItems": 2, "maxItems": 2}
        ),
    }
)

TOOL_VERSION_SCHEMA = _object(
    {
        "name": NON_EMPTY_STRING,
        "version": NON_EMPTY_STRING,
        "executable": NON_EMPTY_STRING,
    }
)

ENVIRONMENT_SCHEMA = _object(
    {
        "os": OS_SCHEMA,
        "hardware": _array(HARDWARE_SCHEMA),
        "tool_versions": _array(TOOL_VERSION_SCHEMA),
        "safe_variable_names": STRING_ARRAY,
    }
)

PROCESS_SCHEMA = _object(
    {
        "pid": {"type": "integer", "minimum": 1},
        "created_at": {"type": "string", "format": "date-time"},
        "executable": NON_EMPTY_STRING,
        "parent_pid": _nullable({"type": "integer", "minimum": 1}),
    }
)

PROCESS_OWNERSHIP_SCHEMA = _object(
    {
        "ownership_token": NON_EMPTY_STRING,
        "mechanism": NON_EMPTY_STRING,
        "processes": _array(PROCESS_SCHEMA),
        "cleanup_completed": {"type": "boolean"},
    }
)

TEST_COUNTS_SCHEMA = _object(
    {
        "passed": NON_NEGATIVE_INTEGER,
        "failed": NON_NEGATIVE_INTEGER,
        "skipped": NON_NEGATIVE_INTEGER,
        "deselected": NON_NEGATIVE_INTEGER,
        "ignored": NON_NEGATIVE_INTEGER,
    }
)

MEASUREMENT_SCHEMA = _object(
    {
        "name": NON_EMPTY_STRING,
        "value": {"type": "number"},
        "unit": {"type": "string", "enum": [item.value for item in MeasurementUnit]},
        "assessed_scope": NON_EMPTY_STRING,
    }
)

ARTIFACT_SCHEMA = {
    **_object(
        {"kind": NON_EMPTY_STRING, "path": NULLABLE_STRING, "absent": {"type": "boolean"}}
    ),
    "oneOf": [
        {"properties": {"path": NON_EMPTY_STRING, "absent": {"const": False}}},
        {"properties": {"path": {"type": "null"}, "absent": {"const": True}}},
    ],
}

RERUN_SCHEMA = {
    **_object(
        {
            "prerequisites": STRING_ARRAY,
            "exact_argv": _nullable(_non_empty_array(STRING)),
            "numbered_procedure": _nullable(_non_empty_array(NON_EMPTY_STRING)),
            "expected_observable": NON_EMPTY_STRING,
        }
    ),
    "oneOf": [
        {
            "properties": {
                "exact_argv": _array(STRING),
                "numbered_procedure": {"type": "null"},
            }
        },
        {
            "properties": {
                "exact_argv": {"type": "null"},
                "numbered_procedure": _array(NON_EMPTY_STRING),
            }
        },
    ],
}

EVIDENCE_RECORD_SCHEMA: JsonSchema = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Repository State Assessment Evidence Record",
    **_object(
        {
            "evidence_id": NON_EMPTY_STRING,
            "check_id": NON_EMPTY_STRING,
            "plane": {"type": "string", "enum": [item.value for item in VerificationPlane]},
            "scope": NON_EMPTY_STRING,
            "exact_argv": _nullable(_non_empty_array(STRING)),
            "numbered_procedure": _nullable(_non_empty_array(NON_EMPTY_STRING)),
            "source_command_locations": _array(SOURCE_LOCATION_SCHEMA),
            "cwd": NON_EMPTY_STRING,
            "started_at": {"type": "string", "format": "date-time"},
            "duration_ms": NON_NEGATIVE_INTEGER,
            "termination": TERMINATION_SCHEMA,
            "prerequisites": _array(PREREQUISITE_SCHEMA),
            "environment": ENVIRONMENT_SCHEMA,
            "source_revision": NON_EMPTY_STRING,
            "stdout_ref": NULLABLE_STRING,
            "stderr_ref": NULLABLE_STRING,
            "relevant_output": STRING_ARRAY,
            "warnings": STRING_ARRAY,
            "test_counts": TEST_COUNTS_SCHEMA,
            "measurements": _array(MEASUREMENT_SCHEMA),
            "artifacts": _array(ARTIFACT_SCHEMA),
            "network_observation_ref": NULLABLE_STRING,
            "process_ownership": PROCESS_OWNERSHIP_SCHEMA,
            "write_audit_ref": NULLABLE_STRING,
            "primary_status": {
                "type": "string",
                "enum": [item.value for item in AssessmentStatus],
            },
            "status_basis": NON_EMPTY_STRING,
            "rerun": RERUN_SCHEMA,
        }
    ),
    "oneOf": [
        {
            "properties": {
                "exact_argv": _array(STRING),
                "numbered_procedure": {"type": "null"},
            }
        },
        {
            "properties": {
                "exact_argv": {"type": "null"},
                "numbered_procedure": _array(NON_EMPTY_STRING),
            }
        },
    ],
}

EVIDENCE_COLLECTION_SCHEMA: JsonSchema = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Repository State Assessment Evidence Record Collection",
    "type": "array",
    "items": EVIDENCE_RECORD_SCHEMA,
    "minItems": 1,
}
