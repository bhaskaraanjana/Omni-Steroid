"""Observe desktop and OS-integration prerequisites without touching the desktop.

These scopes would launch the product shell, register a global hotkey, or take
foreground control of the live interactive session. Observation therefore confirms
availability only from configuration and paths; it never launches, registers, or
injects anything.
"""

from __future__ import annotations

import os

from .native_host_observation_records import (
    NativeHostFacts,
    absent_path,
    observation,
)
from .native_preflight import NativePreflightObservation


def tauri_observations(facts: NativeHostFacts) -> list[NativePreflightObservation]:
    return [
        observation(
            "Tauri host operating-system facilities",
            os.name == "nt",
            f"platform probe: {os.name}",
            "a desktop host provides the windowing facilities the shell requires",
        ),
        observation(
            "interactive desktop session",
            facts.interactive_desktop,
            "session probe of the current login session",
            "an interactive session is required before any window may be shown",
        ),
        absent_path(
            "configured Tauri application executable",
            facts.tauri_executable,
            "build outputs are excluded from the assessment mirror by recorded mirror policy, "
            "and the assessment neither builds nor launches the developer's installed application",
        ),
    ]


def sidecar_observations(facts: NativeHostFacts) -> list[NativePreflightObservation]:
    return [
        absent_path(
            "Python_Engine sidecar executable",
            facts.sidecar_executable,
            "packaging outputs are excluded from the assessment mirror by recorded mirror policy",
        ),
        observation(
            "host process ownership and cleanup facility",
            True,
            "owned-process inspection facility resolved",
            "the assessment can identify and clean only processes it created",
        ),
        observation(
            "assessment-owned Tauri instance",
            False,
            "dependent scope hardware-tauri_launch did not execute",
            "no assessment-owned desktop instance exists because its own preflight blocked",
        ),
    ]


def tray_observations(facts: NativeHostFacts) -> list[NativePreflightObservation]:
    return [
        observation(
            "configured tray host operating-system facilities",
            os.name == "nt",
            f"platform probe: {os.name}",
            "a desktop host provides the tray facilities the shell requires",
        ),
        observation(
            "discovered configured tray actions",
            bool(facts.tray_actions),
            f"mirror configuration probe: {len(facts.tray_actions)} action(s)",
            "tray actions are read from current repository configuration",
        ),
        observation(
            "assessment-owned Tauri instance",
            False,
            "dependent scope hardware-tauri_launch did not execute",
            "no assessment-owned desktop instance exists because its own preflight blocked",
        ),
    ]


def global_hotkey_observations(facts: NativeHostFacts) -> list[NativePreflightObservation]:
    return [
        observation(
            "global hotkey host operating-system facilities",
            os.name == "nt",
            f"platform probe: {os.name}",
            "a desktop host provides global hotkey registration",
        ),
        observation(
            "configured global hotkey without registration conflict",
            False,
            "no registration attempted",
            "registering a global hotkey would capture input from the live interactive session, "
            "so conflict-freedom cannot be confirmed without interfering with the user's desktop",
        ),
        absent_path(
            "disposable unfocused local target",
            facts.tauri_executable,
            "the only configured responder is the desktop application, which is excluded from "
            "the mirror; the assessment will not substitute the developer's installed instance",
        ),
    ]


def text_injection_observations(facts: NativeHostFacts) -> list[NativePreflightObservation]:
    return [
        observation(
            "supported text injection host operating-system facilities",
            os.name == "nt",
            f"platform probe: {os.name}",
            "a desktop host provides the synthetic input facilities",
        ),
        observation(
            "foreground-control permission",
            False,
            "no foreground control attempted",
            "taking foreground control would interfere with the live interactive session",
        ),
        observation(
            "disposable local target",
            False,
            "repository round-trip target inspection",
            "the repository's only injection target is an ignored native round trip whose "
            "cleanup terminates every editor process on the host, including pre-existing ones, "
            "and its toolchain is unavailable, so no disposable target can be created safely",
        ),
    ]
