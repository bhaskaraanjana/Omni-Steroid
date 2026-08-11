"""Pure STT accuracy projection for measured and preflight-blocked reports."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .model_types import AssessmentStatus, require_primary_status


@dataclass(frozen=True, slots=True)
class STTAccuracyContext:
    """Complete corpus, model, and hardware context for a measured WER."""

    corpus_item_count: int
    total_audio_duration_seconds: Decimal
    language: str
    local_model: str
    hardware: str

    def __post_init__(self) -> None:
        if self.corpus_item_count <= 0:
            raise ValueError("corpus_item_count must be positive")
        if not isinstance(self.total_audio_duration_seconds, Decimal):
            raise TypeError("total_audio_duration_seconds must be Decimal")
        if (
            not self.total_audio_duration_seconds.is_finite()
            or self.total_audio_duration_seconds < 0
        ):
            raise ValueError("total_audio_duration_seconds must be finite and non-negative")
        if not all((self.language, self.local_model, self.hardware)):
            raise ValueError("language, local_model, and hardware must not be empty")


@dataclass(frozen=True, slots=True)
class STTAccuracyReportEntry:
    """Report-ready STT result with explicit measured or blocked state."""

    word_error_rate_percent: Decimal | None
    corpus_item_count: int | None
    total_audio_duration_seconds: Decimal | None
    language: str | None
    local_model: str | None
    hardware: str | None
    blockers: tuple[str, ...]
    primary_status: AssessmentStatus
    evidence_reference: str

    def __post_init__(self) -> None:
        require_primary_status(self.primary_status)
        if not self.evidence_reference:
            raise ValueError("evidence_reference must not be empty")


def synthesize_stt_accuracy(
    *,
    word_error_rate_percent: Decimal | None,
    context: STTAccuracyContext | None,
    blockers: tuple[str, ...],
    primary_status: AssessmentStatus,
    evidence_reference: str,
) -> STTAccuracyReportEntry:
    """Project STT evidence without capping WER or treating zero as absent.

    A measurement requires the full corpus/model/hardware context. A blocked,
    unmeasured result carries every named blocker and deliberately has no numeric
    measurement or inferred context.
    """
    require_primary_status(primary_status)
    if not evidence_reference:
        raise ValueError("evidence_reference must not be empty")
    if any(not blocker for blocker in blockers):
        raise ValueError("blockers must not contain empty names")

    if word_error_rate_percent is None:
        if context is not None:
            raise ValueError("unmeasured STT accuracy must omit measurement context")
        if not blockers:
            raise ValueError("unmeasured STT accuracy requires at least one blocker")
        if primary_status is not AssessmentStatus.ENVIRONMENT_BLOCKED:
            raise ValueError("blocked STT accuracy must be Environment_Blocked")
        return STTAccuracyReportEntry(
            word_error_rate_percent=None,
            corpus_item_count=None,
            total_audio_duration_seconds=None,
            language=None,
            local_model=None,
            hardware=None,
            blockers=blockers,
            primary_status=primary_status,
            evidence_reference=evidence_reference,
        )

    if not isinstance(word_error_rate_percent, Decimal):
        raise TypeError("word_error_rate_percent must be Decimal when measured")
    if not word_error_rate_percent.is_finite() or word_error_rate_percent < 0:
        raise ValueError("word_error_rate_percent must be finite and non-negative")
    if context is None:
        raise ValueError("measured STT accuracy requires complete context")
    if blockers:
        raise ValueError("measured STT accuracy cannot retain blockers")
    if primary_status is AssessmentStatus.ENVIRONMENT_BLOCKED:
        raise ValueError("measured STT accuracy cannot be Environment_Blocked")

    return STTAccuracyReportEntry(
        word_error_rate_percent=word_error_rate_percent,
        corpus_item_count=context.corpus_item_count,
        total_audio_duration_seconds=context.total_audio_duration_seconds,
        language=context.language,
        local_model=context.local_model,
        hardware=context.hardware,
        blockers=(),
        primary_status=primary_status,
        evidence_reference=evidence_reference,
    )
