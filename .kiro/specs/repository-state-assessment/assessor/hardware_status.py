"""Pure status decisions for independently preflighted hardware/native checks."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .execution_models import Applicability
from .model_types import AssessmentStatus, require_primary_status


class HardwareScope(StrEnum):
    """The required independently reported hardware/native scopes."""

    MICROPHONE_CAPTURE = "microphone_capture"
    SYSTEM_AUDIO_LOOPBACK_CAPTURE = "system_audio_loopback_capture"
    GRAPHICS_PROCESSOR_SELECTION = "graphics_processor_selection"
    LOCAL_MODEL_INFERENCE = "local_model_inference"
    DENSE_RETRIEVAL = "dense_retrieval"
    FALLBACK_RETRIEVAL = "fallback_retrieval"
    STT_ACCURACY = "stt_accuracy"
    TAURI_LAUNCH = "tauri_launch"
    PYTHON_ENGINE_SIDECAR_LIFECYCLE = "python_engine_sidecar_lifecycle"
    TRAY_BEHAVIOR = "tray_behavior"
    GLOBAL_HOTKEY_HANDLING = "global_hotkey_handling"
    SUPPORTED_TEXT_INJECTION = "supported_text_injection"


@dataclass(frozen=True, slots=True)
class HardwareCheckOutcome:
    """Preflight and execution facts for one hardware/native scope."""

    scope: HardwareScope
    applicability: Applicability
    prerequisites_available: bool
    execution_attempted: bool
    required_outcomes_complete: bool
    subset_verified: bool
    malfunction_observed: bool
    evidence_ref: str

    def __post_init__(self) -> None:
        if not self.evidence_ref:
            raise ValueError("hardware outcome requires one evidence reference")


@dataclass(frozen=True, slots=True)
class HardwareStatusDecision:
    """One primary status and one evidence reference for a native scope."""

    scope: HardwareScope
    primary_status: AssessmentStatus
    evidence_ref: str

    def __post_init__(self) -> None:
        require_primary_status(self.primary_status)
        if not self.evidence_ref:
            raise ValueError("hardware decision requires one evidence reference")


@dataclass(frozen=True, slots=True)
class HardwareStatusInventory:
    """A complete set of unique native-scope status decisions."""

    decisions: tuple[HardwareStatusDecision, ...]

    @property
    def product_failure_scopes(self) -> tuple[HardwareScope, ...]:
        """Return only confirmed post-preflight integration failures."""
        return tuple(
            decision.scope
            for decision in self.decisions
            if decision.primary_status is AssessmentStatus.INTEGRATION_FAILED
        )


def decide_hardware_status(outcome: HardwareCheckOutcome) -> HardwareStatusDecision:
    """Classify absence before execution separately from an observed malfunction."""
    if outcome.applicability is Applicability.NOT_APPLICABLE:
        status = AssessmentStatus.NOT_APPLICABLE
    elif not outcome.prerequisites_available:
        status = AssessmentStatus.ENVIRONMENT_BLOCKED
    elif not outcome.execution_attempted:
        status = AssessmentStatus.UNVERIFIED
    elif outcome.malfunction_observed:
        status = AssessmentStatus.INTEGRATION_FAILED
    elif outcome.required_outcomes_complete:
        status = AssessmentStatus.VERIFIED_WORKING
    elif outcome.subset_verified:
        status = AssessmentStatus.VERIFIED_PARTIAL
    else:
        status = AssessmentStatus.INTEGRATION_FAILED

    return HardwareStatusDecision(outcome.scope, status, outcome.evidence_ref)


def classify_hardware_inventory(
    outcomes: tuple[HardwareCheckOutcome, ...],
) -> HardwareStatusInventory:
    """Require and classify exactly one outcome for every required native scope."""
    scopes = tuple(outcome.scope for outcome in outcomes)
    if len(set(scopes)) != len(scopes):
        raise ValueError("hardware outcomes must have unique scopes")
    if set(scopes) != set(HardwareScope):
        raise ValueError("hardware outcomes must cover every required scope exactly once")
    return HardwareStatusInventory(tuple(decide_hardware_status(item) for item in outcomes))
