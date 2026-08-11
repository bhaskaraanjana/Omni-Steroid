"""Desktop-host native procedure definitions for the hardware assessment.

The definitions are inert: they describe preflights and bounded observables but
never launch Tauri, register a hotkey, touch the clipboard, or inject text.
"""

from __future__ import annotations

from .hardware_status import HardwareScope
from .native_check_plans import (
    NativeCheckPlan,
    NativeInputKind,
    NativeSafetyPolicy,
    _native_plan,
    _observable,
)


def build_desktop_native_check_plans(
    *, cwd: str, run_root: str, tray_actions: tuple[str, ...]
) -> tuple[NativeCheckPlan, ...]:
    """Build Tauri/sidecar and OS-integration plans without executing them."""
    tray_observables = (
        _observable("tray presence observed", 30),
        *tuple(
            _observable(f"configured tray action {action!r} outcome observed", 10)
            for action in tray_actions
        ),
    )
    tray_steps = (
        "After Tauri launch, require configured tray presence within 30 seconds",
        *tuple(
            f"Invoke discovered tray action {action!r} once and require its configured outcome within 10 seconds"
            for action in tray_actions
        ),
    )
    return (
        _native_plan(
            scope=HardwareScope.TAURI_LAUNCH,
            cwd=cwd,
            run_root=run_root,
            prerequisites=(
                "Tauri host operating-system facilities",
                "interactive desktop session",
                "configured Tauri application executable",
            ),
            procedure=("Launch one assessment-owned Tauri instance within 60 seconds",),
            observables=(_observable("Tauri launched", 60),),
            exactly_once=("Tauri launch",),
        ),
        _native_plan(
            scope=HardwareScope.PYTHON_ENGINE_SIDECAR_LIFECYCLE,
            cwd=cwd,
            run_root=run_root,
            prerequisites=(
                "Python_Engine sidecar executable",
                "host process ownership and cleanup facility",
                "assessment-owned Tauri instance",
            ),
            procedure=(
                "Require the assessment-owned Python_Engine sidecar to start within 30 seconds of Tauri launch and remain available while Tauri runs",
                "Exit Tauri; require sidecar stop and absence of the assessment-created process within 10 seconds",
            ),
            observables=(
                _observable("sidecar started and available", 30),
                _observable("sidecar stopped and process absent", 10),
            ),
            dependencies=("hardware-tauri_launch",),
        ),
        _native_plan(
            scope=HardwareScope.TRAY_BEHAVIOR,
            cwd=cwd,
            run_root=run_root,
            prerequisites=(
                "configured tray host operating-system facilities",
                "discovered configured tray actions",
                "assessment-owned Tauri instance",
            ),
            procedure=tray_steps,
            observables=tray_observables,
            dependencies=("hardware-tauri_launch",),
        ),
        _native_plan(
            scope=HardwareScope.GLOBAL_HOTKEY_HANDLING,
            cwd=cwd,
            run_root=run_root,
            prerequisites=(
                "global hotkey host operating-system facilities",
                "configured global hotkey without registration conflict",
                "disposable unfocused local target",
            ),
            procedure=(
                "Register the configured hotkey, remove application input focus, activate it once, and require exactly one configured response within 5 seconds",
            ),
            observables=(_observable("exactly one unfocused hotkey response", 5),),
            exactly_once=("global hotkey activation", "configured application response"),
        ),
        _native_plan(
            scope=HardwareScope.SUPPORTED_TEXT_INJECTION,
            cwd=cwd,
            run_root=run_root,
            prerequisites=(
                "supported text injection host operating-system facilities",
                "foreground-control permission",
                "disposable local target",
            ),
            procedure=(
                "Inject one synthetic non-private test string once into the disposable local target; require exact unchanged insertion within 5 seconds",
            ),
            observables=(_observable("exact unchanged text inserted once", 5),),
            safety=NativeSafetyPolicy(
                NativeInputKind.TEXT,
                disposable_target_required=True,
            ),
            exactly_once=("text injection request", "test string insertion"),
        ),
    )
