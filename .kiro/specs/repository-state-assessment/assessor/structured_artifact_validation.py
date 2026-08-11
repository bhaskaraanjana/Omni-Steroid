"""Strict, dependency-free validation for assessment JSON and JSONL evidence.

External structured data is untrusted. Validation rejects duplicate keys, unknown
fields, malformed zoned timestamps, and incomplete records before any file write.
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from decimal import Decimal
from typing import Any, Mapping, Sequence

from .artifact_schemas import EVIDENCE_COLLECTION_SCHEMA, EVIDENCE_RECORD_SCHEMA, JsonSchema


class ArtifactSchemaError(ValueError):
    """Raised when structured evidence is invalid or ambiguous."""


class StructuredArtifactValidator:
    """Validate normalized evidence against the assessor's strict schemas."""

    def validate_evidence_record(self, record: object) -> dict[str, object]:
        """Return a validated evidence record or raise ``ArtifactSchemaError``."""
        self._validate(record, EVIDENCE_RECORD_SCHEMA, "$")
        assert isinstance(record, dict)
        for index, location in enumerate(record["source_command_locations"]):
            assert isinstance(location, dict)
            if location["end_line"] < location["start_line"]:
                raise ArtifactSchemaError(
                    f"$.source_command_locations[{index}].end_line must not precede start_line"
                )
        return record

    def validate_evidence_collection(
        self, records: Sequence[Mapping[str, object]]
    ) -> tuple[dict[str, object], ...]:
        """Validate a non-empty sequence of evidence records."""
        materialized = [dict(record) for record in records]
        self._validate(materialized, EVIDENCE_COLLECTION_SCHEMA, "$")
        return tuple(self.validate_evidence_record(record) for record in materialized)

    def validate_json(self, document: str) -> dict[str, object]:
        """Parse and validate one EvidenceRecord JSON document."""
        value = self._parse_json(document, line_number=None)
        return self.validate_evidence_record(value)

    def validate_jsonl(self, document: str) -> tuple[dict[str, object], ...]:
        """Parse and validate one EvidenceRecord per non-blank JSONL line."""
        if not document:
            raise ArtifactSchemaError("JSONL must contain at least one evidence record")
        records: list[dict[str, object]] = []
        for line_number, line in enumerate(document.splitlines(), start=1):
            if not line.strip():
                raise ArtifactSchemaError(f"JSONL line {line_number} is a blank line")
            value = self._parse_json(line, line_number=line_number)
            if not isinstance(value, dict):
                raise ArtifactSchemaError(f"JSONL line {line_number} must be an object")
            records.append(value)
        if not records:
            raise ArtifactSchemaError("JSONL must contain at least one evidence record")
        return self.validate_evidence_collection(records)

    @staticmethod
    def canonical_json(record: Mapping[str, object]) -> str:
        """Serialize a record deterministically after validation by the caller."""
        return json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"

    @staticmethod
    def canonical_jsonl(records: Sequence[Mapping[str, object]]) -> str:
        """Serialize validated records deterministically as JSON Lines."""
        return "".join(
            json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            for record in records
        )

    def _parse_json(self, document: str, *, line_number: int | None) -> object:
        if not isinstance(document, str):
            raise ArtifactSchemaError("JSON input must be text")

        def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, value in pairs:
                if key in result:
                    raise ArtifactSchemaError(f"duplicate JSON property: {key}")
                result[key] = value
            return result

        try:
            return json.loads(document, object_pairs_hook=reject_duplicates)
        except ArtifactSchemaError:
            raise
        except (json.JSONDecodeError, RecursionError) as error:
            prefix = f"JSONL line {line_number}" if line_number is not None else "JSON"
            raise ArtifactSchemaError(f"{prefix} is malformed: {error}") from error

    def _validate(self, value: object, schema: JsonSchema, path: str) -> None:
        expected_type = schema.get("type")
        if expected_type is not None and not self._matches_type(value, expected_type):
            raise ArtifactSchemaError(f"{path} must be {expected_type}")

        if "const" in schema and value != schema["const"]:
            raise ArtifactSchemaError(f"{path} must equal {schema['const']!r}")
        if "enum" in schema and value not in schema["enum"]:
            raise ArtifactSchemaError(f"{path} has an unsupported value")

        if isinstance(value, str):
            if len(value) < schema.get("minLength", 0):
                raise ArtifactSchemaError(f"{path} must not be empty")
            if schema.get("format") == "date-time":
                self._validate_zoned_datetime(value, path)

        if self._is_number(value):
            if not math.isfinite(float(value)):
                raise ArtifactSchemaError(f"{path} must be finite")
            if "minimum" in schema and value < schema["minimum"]:
                raise ArtifactSchemaError(f"{path} must be at least {schema['minimum']}")

        if isinstance(value, list):
            if len(value) < schema.get("minItems", 0):
                raise ArtifactSchemaError(f"{path} has too few items")
            if "maxItems" in schema and len(value) > schema["maxItems"]:
                raise ArtifactSchemaError(f"{path} has too many items")
            item_schema = schema.get("items")
            if item_schema is not None:
                for index, item in enumerate(value):
                    self._validate(item, item_schema, f"{path}[{index}]")

        if isinstance(value, dict):
            properties = schema.get("properties", {})
            for required_name in schema.get("required", []):
                if required_name not in value:
                    raise ArtifactSchemaError(f"{path}.{required_name} is required")
            if schema.get("additionalProperties") is False:
                unexpected = sorted(set(value) - set(properties))
                if unexpected:
                    raise ArtifactSchemaError(
                        f"{path} has unexpected property {unexpected[0]!r}"
                    )
            for name, property_schema in properties.items():
                if name in value:
                    self._validate(value[name], property_schema, f"{path}.{name}")

        if "oneOf" in schema:
            successful_options = 0
            for option in schema["oneOf"]:
                try:
                    self._validate(value, option, path)
                except ArtifactSchemaError:
                    continue
                successful_options += 1
            if successful_options != 1:
                raise ArtifactSchemaError(f"{path} must match exactly one allowed shape")

    @staticmethod
    def _matches_type(value: object, expected_type: str) -> bool:
        type_checks = {
            "object": lambda candidate: isinstance(candidate, dict),
            "array": lambda candidate: isinstance(candidate, list),
            "string": lambda candidate: isinstance(candidate, str),
            "integer": lambda candidate: isinstance(candidate, int)
            and not isinstance(candidate, bool),
            "number": StructuredArtifactValidator._is_number,
            "boolean": lambda candidate: isinstance(candidate, bool),
            "null": lambda candidate: candidate is None,
        }
        try:
            return type_checks[expected_type](value)
        except KeyError as error:
            raise ArtifactSchemaError(f"unsupported schema type {expected_type!r}") from error

    @staticmethod
    def _is_number(value: object) -> bool:
        return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)

    @staticmethod
    def _validate_zoned_datetime(value: str, path: str) -> None:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise ArtifactSchemaError(f"{path} must be an ISO-8601 date-time") from error
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ArtifactSchemaError(f"{path} must include a time-zone offset")
