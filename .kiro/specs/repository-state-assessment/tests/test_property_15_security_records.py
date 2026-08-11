"""Feature: repository-state-assessment, Property 15: Security records are complete and sanitized.

**Validates: Requirements 7.3, 7.4, 7.5, 7.11**
"""

from __future__ import annotations

import random

from assessor import (
    RawSecurityArtifact,
    SecurityControl,
    SecurityControlResult,
    SensitiveCategory,
    SensitiveMarker,
    VerificationMethods,
    normalize_security_records,
)

_SEED = 20260708
_CASES = 256


def _markers(case: int, control: SecurityControl) -> tuple[SensitiveMarker, ...]:
    prefix = f"case-{case}-{control.value}"
    values = {
        SensitiveCategory.SECRET: f"sk-{prefix}-9f82",
        SensitiveCategory.CREDENTIAL: f"Bearer.{prefix}.credential",
        SensitiveCategory.PRIVATE_AUDIO: f"RIFF-private-audio-{prefix}",
        SensitiveCategory.PRIVATE_TRANSCRIPT: f"private transcript Łódź {prefix}",
        SensitiveCategory.PRIVATE_PATH: f"C:\\Users\\Person {case}\\Private\\{control.value}.txt",
        SensitiveCategory.PRIVATE_CONTENT: f"personal note 東京 {prefix}",
    }
    return tuple(SensitiveMarker(category, value) for category, value in values.items())


def _result(rng: random.Random, case: int, control: SecurityControl) -> SecurityControlResult:
    markers = _markers(case, control)
    methods = VerificationMethods(*(bool(rng.getrandbits(1)) for _ in range(5)))
    joined = " | ".join(marker.value for marker in markers)
    redactable = " | ".join(
        marker.value
        for marker in markers
        if marker.category is not SensitiveCategory.PRIVATE_AUDIO
    )
    return SecurityControlResult(
        control=control,
        methods=methods,
        relevant_output=(f"observed {joined}",),
        artifacts=(
            RawSecurityArtifact(f"redactable-{case}-{control.value}", redactable, True),
            RawSecurityArtifact(f"unsafe-{case}-{control.value}", joined, False),
            RawSecurityArtifact(f"safe-{case}-{control.value}", "synthetic safe evidence", False),
        ),
        sensitive_markers=markers,
    )


def test_private_audio_and_non_redactable_sensitive_artifacts_are_withheld() -> None:
    """A concrete record demonstrates redaction labels and fail-closed withholding."""
    rng = random.Random(_SEED)
    results = tuple(_result(rng, 0, control) for control in SecurityControl)

    collection = normalize_security_records(results)

    first = collection.records[0]
    assert first.methods == results[0].methods
    assert SensitiveCategory.SECRET.label in first.relevant_output[0]
    assert {artifact.artifact_id for artifact in first.artifacts} == {
        "redactable-0-local_only_storage",
        "safe-0-local_only_storage",
    }
    assert "unsafe-0-local_only_storage" in collection.withheld_artifact_ids


def test_property_15_security_records_are_complete_and_sanitized() -> None:
    """Generate 256 complete control inventories with all sensitive categories.

    **Validates: Requirements 7.3, 7.4, 7.5, 7.11**
    """
    rng = random.Random(_SEED)
    categories = set(SensitiveCategory)

    for case in range(_CASES):
        generated = [_result(rng, case, control) for control in SecurityControl]
        rng.shuffle(generated)
        collection = normalize_security_records(tuple(generated))
        records_by_control = {record.control: record for record in collection.records}

        assert len(collection.records) == len(SecurityControl)
        assert tuple(record.control for record in collection.records) == tuple(SecurityControl)
        assert set(records_by_control) == set(SecurityControl)
        assert len(records_by_control) == len(collection.records)

        expected_withheld: set[str] = set()
        for raw in generated:
            record = records_by_control[raw.control]
            assert record.methods == raw.methods
            assert len(record.methods.values()) == 5
            assert all(type(value) is bool for value in record.methods.values())

            labels = {marker.category.label for marker in raw.sensitive_markers}
            values = {marker.value for marker in raw.sensitive_markers}
            permanent_text = "\n".join(
                (*record.relevant_output, *(artifact.content for artifact in record.artifacts))
            )
            assert all(label in permanent_text for label in labels)
            assert values.isdisjoint(permanent_text)
            assert {marker.category for marker in raw.sensitive_markers} == categories

            expected_withheld.add(f"unsafe-{case}-{raw.control.value}")
            admitted_ids = {artifact.artifact_id for artifact in record.artifacts}
            assert f"redactable-{case}-{raw.control.value}" in admitted_ids
            assert f"safe-{case}-{raw.control.value}" in admitted_ids
            assert expected_withheld.isdisjoint(admitted_ids)

        assert set(collection.withheld_artifact_ids) == expected_withheld

    assert _CASES >= 100