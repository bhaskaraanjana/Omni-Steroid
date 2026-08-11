"""Property 11 coverage for complete STT accuracy report context."""

from __future__ import annotations

from decimal import Decimal

import pytest

from assessor import (
    AssessmentStatus,
    STTAccuracyContext,
    synthesize_stt_accuracy,
)

_CASES = 192


def _context(case_index: int) -> STTAccuracyContext:
    return STTAccuracyContext(
        corpus_item_count=case_index + 1,
        total_audio_duration_seconds=Decimal(case_index + 1) / Decimal("8"),
        language=("en-US", "es-ES", "ja-JP")[case_index % 3],
        local_model=f"speech-model-{case_index % 7}",
        hardware=f"accelerator-{case_index % 5}",
    )


def _wer(case_index: int) -> Decimal:
    # Includes exact zero and values above 100%, proving WER is not capped.
    return Decimal(case_index * 137) / Decimal("10")


def _blockers(case_index: int) -> tuple[str, ...]:
    mask = case_index % 3
    if mask == 0:
        return ("labelled local speech corpus",)
    if mask == 1:
        return ("speech Local_Model",)
    return ("labelled local speech corpus", "speech Local_Model")


def test_property_11_stt_accuracy_preserves_valid_zero_and_complete_context() -> None:
    """Property 11: STT accuracy preserves valid zero and complete context.

    **Validates: Requirements 5.6, 5.7, 9.5, 9.6**
    """
    measured_values: list[Decimal] = []

    for case_index in range(_CASES):
        context = _context(case_index)
        wer = _wer(case_index)
        measured = synthesize_stt_accuracy(
            word_error_rate_percent=wer,
            context=context,
            blockers=(),
            primary_status=AssessmentStatus.VERIFIED_WORKING,
            evidence_reference=f"evidence/stt-{case_index}.json",
        )

        assert measured.word_error_rate_percent == wer
        assert measured.word_error_rate_percent is not None
        assert measured.corpus_item_count == context.corpus_item_count
        assert measured.total_audio_duration_seconds == context.total_audio_duration_seconds
        assert measured.language == context.language
        assert measured.local_model == context.local_model
        assert measured.hardware == context.hardware
        assert measured.evidence_reference == f"evidence/stt-{case_index}.json"
        assert measured.blockers == ()
        measured_values.append(measured.word_error_rate_percent)

        blockers = _blockers(case_index)
        blocked = synthesize_stt_accuracy(
            word_error_rate_percent=None,
            context=None,
            blockers=blockers,
            primary_status=AssessmentStatus.ENVIRONMENT_BLOCKED,
            evidence_reference=f"evidence/stt-blocked-{case_index}.json",
        )

        assert blocked.word_error_rate_percent is None
        assert blocked.corpus_item_count is None
        assert blocked.total_audio_duration_seconds is None
        assert blocked.language is None
        assert blocked.local_model is None
        assert blocked.hardware is None
        assert blocked.blockers == blockers
        assert blocked.primary_status is AssessmentStatus.ENVIRONMENT_BLOCKED
        assert blocked.evidence_reference == f"evidence/stt-blocked-{case_index}.json"

    assert len(measured_values) >= 100
    assert Decimal("0.0") in measured_values
    assert any(value > Decimal("100") for value in measured_values)


def test_measured_stt_accuracy_rejects_incomplete_or_blocked_context() -> None:
    with pytest.raises(ValueError, match="context"):
        synthesize_stt_accuracy(
            word_error_rate_percent=Decimal("0.0"),
            context=None,
            blockers=(),
            primary_status=AssessmentStatus.VERIFIED_WORKING,
            evidence_reference="evidence/stt.json",
        )

    with pytest.raises(ValueError, match="blockers"):
        synthesize_stt_accuracy(
            word_error_rate_percent=Decimal("12.5"),
            context=_context(0),
            blockers=("speech Local_Model",),
            primary_status=AssessmentStatus.VERIFIED_WORKING,
            evidence_reference="evidence/stt.json",
        )


def test_unmeasured_stt_accuracy_requires_every_blocking_field() -> None:
    with pytest.raises(ValueError, match="blocker"):
        synthesize_stt_accuracy(
            word_error_rate_percent=None,
            context=None,
            blockers=(),
            primary_status=AssessmentStatus.ENVIRONMENT_BLOCKED,
            evidence_reference="evidence/stt-blocked.json",
        )
