"""Declarative hardware/native procedures that cannot perform scoped behavior.

Plans keep every check independent, bounded, local-only, and assessment-owned.
Audio fixtures must remain in memory and are never admitted as artifacts.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .execution_models import Applicability, CheckPlan, Prerequisite
from .hardware_status import HardwareScope
from .model_types import NetworkMode, NetworkPolicy, VerificationPlane, WritePolicy


class NativeInputKind(StrEnum):
    """Synthetic input category permitted by a native procedure."""

    NONE = "none"
    AUDIO = "audio"
    TEXT = "text"


@dataclass(frozen=True, slots=True)
class NativeSafetyPolicy:
    """Safety constraints applied before a native procedure can be admitted."""

    input_kind: NativeInputKind
    synthetic_non_private_only: bool = True
    persist_audio: bool = False
    disposable_target_required: bool = False

    def __post_init__(self) -> None:
        if not self.synthetic_non_private_only:
            raise ValueError("native inputs must be synthetic and non-private")
        if self.persist_audio:
            raise ValueError("native procedures must never persist audio")


@dataclass(frozen=True, slots=True)
class BoundedObservable:
    """One required observable and its maximum elapsed time."""

    name: str
    deadline_ms: int

    def __post_init__(self) -> None:
        if not self.name or self.deadline_ms <= 0:
            raise ValueError("bounded observables require a name and positive deadline")


@dataclass(frozen=True, slots=True)
class NativeCheckPlan:
    """A generic check plan plus native safety and outcome contracts."""

    scope: HardwareScope
    check_plan: CheckPlan
    observables: tuple[BoundedObservable, ...]
    safety: NativeSafetyPolicy
    exactly_once_operations: tuple[str, ...] = ()


def _observable(name: str, seconds: int) -> BoundedObservable:
    return BoundedObservable(name, seconds * 1_000)


def _native_plan(
    *,
    scope: HardwareScope,
    cwd: str,
    run_root: str,
    prerequisites: tuple[str, ...],
    procedure: tuple[str, ...],
    observables: tuple[BoundedObservable, ...],
    safety: NativeSafetyPolicy = NativeSafetyPolicy(NativeInputKind.NONE),
    exactly_once: tuple[str, ...] = (),
    dependencies: tuple[str, ...] = (),
) -> NativeCheckPlan:
    conflict = "absence of conflicting pre-existing applications or processes"
    named_prerequisites = prerequisites if conflict in prerequisites else (*prerequisites, conflict)
    check = CheckPlan(
        check_id=f"hardware-{scope.value}",
        plane=VerificationPlane.HARDWARE_INTEGRATION,
        scope=scope.value,
        command_source=None,
        exact_argv=None,
        numbered_procedure=procedure,
        cwd=cwd,
        prerequisites=tuple(
            Prerequisite(
                name=name,
                detection_procedure=(
                    f"Confirm {name} without opening a device or executing scoped behavior",
                    "Record non-sensitive detection evidence",
                ),
            )
            for name in named_prerequisites
        ),
        applicability=Applicability.APPLICABLE,
        applicability_basis="configured hardware/native assessment scope",
        timeout_ms=sum(item.deadline_ms for item in observables),
        write_policy=WritePolicy((run_root,)),
        network_policy=NetworkPolicy(NetworkMode.NONE),
        external_dependency=False,
        dependent_check_ids=dependencies,
        cleanup_procedure=(
            "Stop and release only assessment-owned resources",
            "Confirm no assessment-created process or open device remains",
        ),
    )
    return NativeCheckPlan(scope, check, observables, safety, exactly_once)


def build_native_check_plans(
    *, cwd: str, run_root: str, tray_actions: tuple[str, ...]
) -> tuple[NativeCheckPlan, ...]:
    """Build independent, non-executing plans for every hardware/native scope."""
    audio_safety = NativeSafetyPolicy(NativeInputKind.AUDIO)
    text_safety = NativeSafetyPolicy(
        NativeInputKind.TEXT, disposable_target_required=True
    )
    plans = [
        _native_plan(
            scope=HardwareScope.MICROPHONE_CAPTURE,
            cwd=cwd,
            run_root=run_root,
            prerequisites=(
                "selected microphone device",
                "microphone permission",
                "microphone driver",
                "synthetic non-private microphone test audio",
            ),
            procedure=(
                "Start selected microphone capture; require start within 10 seconds",
                "Play only synthetic non-private test audio and require an in-memory frame with a non-zero sample within 10 seconds",
                "Stop capture within 5 seconds and discard every in-memory audio frame",
                "Reopen and stop the same microphone within 5 seconds to prove release",
            ),
            observables=(
                _observable("capture started", 10),
                _observable("non-zero in-memory frame received", 10),
                _observable("capture stopped", 5),
                _observable("same device reopened and stopped", 5),
            ),
            safety=audio_safety,
        ),
        _native_plan(
            scope=HardwareScope.SYSTEM_AUDIO_LOOPBACK_CAPTURE,
            cwd=cwd,
            run_root=run_root,
            prerequisites=(
                "selected system-audio loopback device",
                "system-audio loopback permission",
                "system-audio loopback driver",
                "local synthetic tone generator",
            ),
            procedure=(
                "Start selected loopback capture within 10 seconds",
                "Generate a local synthetic tone; require a non-zero in-memory frame during generation within 10 seconds and identify it as loopback",
                "Stop capture within 5 seconds and discard every in-memory audio frame",
                "Reopen and stop the same loopback device within 5 seconds to prove release",
            ),
            observables=(
                _observable("loopback capture started", 10),
                _observable("identified non-zero loopback frame received", 10),
                _observable("loopback capture stopped", 5),
                _observable("same loopback device reopened and stopped", 5),
            ),
            safety=audio_safety,
        ),
        _native_plan(
            scope=HardwareScope.GRAPHICS_PROCESSOR_SELECTION,
            cwd=cwd,
            run_root=run_root,
            prerequisites=("graphics processor", "graphics processor driver"),
            procedure=(
                "Resolve the configured local compute path and record the selected graphics processor without inference",
            ),
            observables=(_observable("graphics processor selected and identified", 300),),
        ),
        _native_plan(
            scope=HardwareScope.LOCAL_MODEL_INFERENCE,
            cwd=cwd,
            run_root=run_root,
            prerequisites=("graphics processor", "Local_Model weights", "local model runtime"),
            procedure=(
                "Load the confirmed Local_Model within 300 seconds",
                "Run exactly one local inference within 300 seconds and record a non-empty result, compute device, and duration in milliseconds",
            ),
            observables=(
                _observable("Local_Model loaded", 300),
                _observable("one non-empty local inference completed", 300),
            ),
            exactly_once=("local model inference",),
            dependencies=("hardware-graphics_processor_selection",),
        ),
        _native_plan(
            scope=HardwareScope.DENSE_RETRIEVAL,
            cwd=cwd,
            run_root=run_root,
            prerequisites=(
                "Dense_Retrieval_Weights",
                "local dense retrieval runtime",
                "disposable synthetic text corpus",
            ),
            procedure=(
                "Generate exactly one non-empty dense embedding within 120 seconds",
                "Complete exactly one retrieval within 120 seconds and record dense-tier participation",
            ),
            observables=(
                _observable("one non-empty dense embedding generated", 120),
                _observable("one dense-participating retrieval completed", 120),
            ),
            exactly_once=("dense embedding generation", "dense retrieval"),
        ),
        _native_plan(
            scope=HardwareScope.FALLBACK_RETRIEVAL,
            cwd=cwd,
            run_root=run_root,
            prerequisites=("documented fallback retrieval tier", "disposable synthetic text corpus"),
            procedure=(
                "Using only synthetic text, complete exactly one fallback-tier retrieval within 120 seconds and identify the fallback tier",
            ),
            observables=(_observable("one fallback retrieval completed", 120),),
            safety=NativeSafetyPolicy(NativeInputKind.TEXT),
            exactly_once=("fallback retrieval",),
        ),
        _native_plan(
            scope=HardwareScope.STT_ACCURACY,
            cwd=cwd,
            run_root=run_root,
            prerequisites=(
                "labelled local synthetic speech corpus",
                "speech Local_Model",
                "local speech model runtime",
            ),
            procedure=(
                "Transcribe the labelled synthetic local corpus without persisting audio",
                "Calculate uncapped word error rate and retain corpus count, duration, language, model, hardware, and valid numeric zero",
            ),
            # Requirement 5.6 has no per-item deadline; the assessment procedure is
            # still fail-closed and bounded to the model-operation ceiling.
            observables=(_observable("corpus WER and complete context produced", 300),),
            safety=audio_safety,
        ),
    ]

    from .native_desktop_check_plans import build_desktop_native_check_plans

    return tuple(
        (*plans, *build_desktop_native_check_plans(
            cwd=cwd,
            run_root=run_root,
            tray_actions=tray_actions,
        ))
    )
