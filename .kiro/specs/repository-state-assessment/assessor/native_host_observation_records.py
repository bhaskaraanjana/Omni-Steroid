"""Shared facts and record primitives for hardware/native preflight observation.

Both the capture/model/retrieval observers and the desktop observers build their
records here, so a prerequisite is described the same way wherever it is observed.
Nothing in this module opens a device, launches an application, or registers input.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .native_preflight import NativePreflightObservation

CONFLICT_PREREQUISITE = "absence of conflicting pre-existing applications or processes"
NO_DEVICE_PROBE = (
    "not confirmable without opening the audio subsystem; the assessment never "
    "opens a capture device, so this prerequisite stays unconfirmed and fails closed"
)


@dataclass(frozen=True, slots=True)
class NativeHostFacts:
    """Filesystem and process facts gathered once for every native scope."""

    mirror_root: Path
    contained_models_dir: Path
    interactive_desktop: bool
    conflicting_process_names: tuple[str, ...]
    graphics_processor_tool: str | None
    tray_actions: tuple[str, ...]

    @property
    def tauri_executable(self) -> Path:
        """Location the built desktop binary would occupy inside the mirror."""
        return self.mirror_root / "apps/ui/src-tauri/target/release/omni-ui.exe"

    @property
    def sidecar_executable(self) -> Path:
        """Location the frozen engine sidecar would occupy inside the mirror."""
        return self.mirror_root / "packaging/dist/omni-engine/omni-engine.exe"


def observation(
    name: str, available: bool, evidence: str, detail: str
) -> NativePreflightObservation:
    """Record one prerequisite observation with its detection evidence."""
    return NativePreflightObservation(name, available, evidence, detail)


def absent_path(name: str, path: Path, why: str) -> NativePreflightObservation:
    """Observe a prerequisite that is satisfied only by an existing path."""
    return observation(
        name,
        path.exists(),
        f"path probe: {path}",
        f"{'present' if path.exists() else 'absent'}; {why}",
    )


def audio_device_observations(prefix: str) -> list[NativePreflightObservation]:
    """Record the device, permission, and driver trio for one audio direction."""
    evidence = "no device enumeration performed"
    return [
        observation(f"selected {prefix} device", False, evidence, NO_DEVICE_PROBE),
        observation(f"{prefix} permission", False, evidence, NO_DEVICE_PROBE),
        observation(f"{prefix} driver", False, evidence, NO_DEVICE_PROBE),
    ]


def conflict_observation(facts: NativeHostFacts) -> NativePreflightObservation:
    """Observe whether any pre-existing application would make a scope unsafe."""
    conflicting = facts.conflicting_process_names
    return observation(
        CONFLICT_PREREQUISITE,
        not conflicting,
        "process-name inventory of the live desktop",
        (
            "no conflicting pre-existing application observed"
            if not conflicting
            else f"conflicting pre-existing processes observed: {', '.join(conflicting)}"
        ),
    )
