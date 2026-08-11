"""Observe capture, model, and retrieval prerequisites without opening a device.

Availability is judged against the environment the check would actually execute in
— the verified mirror plus the contained child environment — not against the
developer's live desktop. A prerequisite that cannot be confirmed by a
non-behavioral observation is recorded unavailable, never assumed present.
Desktop and OS-integration scopes live in `native_desktop_host_observations`.
"""

from __future__ import annotations

from .hardware_status import HardwareScope
from .native_desktop_host_observations import (
    global_hotkey_observations,
    sidecar_observations,
    tauri_observations,
    text_injection_observations,
    tray_observations,
)
from .native_host_observation_records import NativeHostFacts as NativeHostFacts
from .native_host_observation_records import (
    audio_device_observations,
    conflict_observation,
    observation,
)
from .native_preflight import NativePreflightObservation


def observations_for_scope(
    scope: HardwareScope, facts: NativeHostFacts
) -> tuple[NativePreflightObservation, ...]:
    """Return one non-behavioral observation per prerequisite of one scope."""
    builder = _BUILDERS[scope]
    return (*builder(facts), conflict_observation(facts))


def _microphone(facts: NativeHostFacts) -> list[NativePreflightObservation]:
    return [
        *audio_device_observations("microphone"),
        observation(
            "synthetic non-private microphone test audio",
            False,
            "mirror fixture search for a labelled synthetic microphone corpus",
            "no repository fixture supplies synthetic audio to a physical microphone, and "
            "configuring a virtual input device would change machine audio configuration",
        ),
    ]


def _loopback(facts: NativeHostFacts) -> list[NativePreflightObservation]:
    return [
        *audio_device_observations("system-audio loopback"),
        observation(
            "local synthetic tone generator",
            False,
            "mirror fixture search for an assessment-owned tone generator",
            "no repository-owned generator exists, and system-audio loopback on a live "
            "desktop would capture whatever other applications are playing, which is not "
            "guaranteed synthetic non-private input",
        ),
    ]


def _graphics_processor(facts: NativeHostFacts) -> list[NativePreflightObservation]:
    tool = facts.graphics_processor_tool
    return [
        observation(
            "graphics processor",
            tool is not None,
            f"vendor management tool resolution: {tool or 'unresolved'}",
            "a resolvable vendor management tool evidences a present graphics processor",
        ),
        observation(
            "graphics processor driver",
            tool is not None,
            f"vendor management tool resolution: {tool or 'unresolved'}",
            "the vendor management tool ships with, and is only resolvable alongside, its driver",
        ),
    ]


def _local_model_inference(facts: NativeHostFacts) -> list[NativePreflightObservation]:
    weights = facts.contained_models_dir
    return [
        *_graphics_processor(facts)[:1],
        observation(
            "Local_Model weights",
            False,
            f"contained model root probe: {weights}",
            "the contained environment redirects the model root to an empty assessment-owned "
            "directory; host weights outside the containment boundary are not admissible and "
            "downloading weights is prohibited",
        ),
        observation(
            "local model runtime",
            True,
            "mirror dependency manifest declares the local inference runtime",
            "the runtime is declared and installed, but has no admissible weights to load",
        ),
    ]


def _dense_retrieval(facts: NativeHostFacts) -> list[NativePreflightObservation]:
    return [
        observation(
            "Dense_Retrieval_Weights",
            False,
            f"contained model root probe: {facts.contained_models_dir}",
            "no dense embedding export exists in the contained model root or on the host; "
            "downloading weights is prohibited",
        ),
        observation(
            "local dense retrieval runtime",
            True,
            "mirror dependency manifest declares the ONNX and vector-store runtime",
            "the runtime is present; only its weights are absent",
        ),
        observation(
            "disposable synthetic text corpus",
            True,
            "assessment-owned corpus created under the temporary run root",
            "synthetic non-private text authored by the assessment for this run only",
        ),
    ]


def _fallback_retrieval(facts: NativeHostFacts) -> list[NativePreflightObservation]:
    schema = facts.mirror_root / "migrations/0004_index_layer.sql"
    return [
        observation(
            "documented fallback retrieval tier",
            schema.is_file(),
            f"mirror schema probe: {schema}",
            "the repository documents an explicit keyword-only tier over the full-text index "
            "used when the dense side is configured absent",
        ),
        observation(
            "disposable synthetic text corpus",
            True,
            "assessment-owned corpus created under the temporary run root",
            "synthetic non-private text authored by the assessment for this run only",
        ),
    ]


def _stt_accuracy(facts: NativeHostFacts) -> list[NativePreflightObservation]:
    return [
        observation(
            "labelled local synthetic speech corpus",
            False,
            "mirror fixture search for labelled speech audio",
            "no labelled synthetic speech corpus exists in the repository, so no word error "
            "rate can be measured and none may be invented",
        ),
        observation(
            "speech Local_Model",
            False,
            f"contained model root probe: {facts.contained_models_dir}",
            "the contained model root is empty and downloading weights is prohibited",
        ),
        observation(
            "local speech model runtime",
            True,
            "mirror dependency manifest declares the speech runtime extra",
            "the runtime is declared; corpus and weights are the missing inputs",
        ),
    ]


_BUILDERS = {
    HardwareScope.MICROPHONE_CAPTURE: _microphone,
    HardwareScope.SYSTEM_AUDIO_LOOPBACK_CAPTURE: _loopback,
    HardwareScope.GRAPHICS_PROCESSOR_SELECTION: _graphics_processor,
    HardwareScope.LOCAL_MODEL_INFERENCE: _local_model_inference,
    HardwareScope.DENSE_RETRIEVAL: _dense_retrieval,
    HardwareScope.FALLBACK_RETRIEVAL: _fallback_retrieval,
    HardwareScope.STT_ACCURACY: _stt_accuracy,
    HardwareScope.TAURI_LAUNCH: tauri_observations,
    HardwareScope.PYTHON_ENGINE_SIDECAR_LIFECYCLE: sidecar_observations,
    HardwareScope.TRAY_BEHAVIOR: tray_observations,
    HardwareScope.GLOBAL_HOTKEY_HANDLING: global_hotkey_observations,
    HardwareScope.SUPPORTED_TEXT_INJECTION: text_injection_observations,
}
