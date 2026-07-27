"""Bot-free meeting detection: notice a meeting WITHOUT joining anything.

Observes local state only — running processes, visible window titles, the
Windows mic consent store, and loopback-VAD speech probabilities — and
raises typed decisions (suggest capture / opt-in auto-start / suggest stop)
for the server wiring. Deny by default: unknown sources may only suggest.
"""

from engine.detect.auto_start_rules_engine import AutoStartRulesEngine, DetectionRuleSettings
from engine.detect.detection_service import AsyncClock, DetectionService, SystemClock
from engine.detect.detection_signal_types import (
    DEFAULT_AUTO_START_SOURCES,
    KNOWN_DETECTION_SOURCES,
    AdHocCallSuspected,
    AutoStart,
    DesktopSnapshot,
    DetectionDecision,
    DetectionSignal,
    MeetingAppDetected,
    MicrophoneInUse,
    ProcessInfo,
    SuggestCapture,
    SuggestStop,
    WindowInfo,
)
from engine.detect.meeting_process_watcher import MeetingProcessWatcher
from engine.detect.microphone_in_use_detector import (
    ConsentStoreEntry,
    MicrophoneInUseDetector,
    read_microphone_consent_store_via_winreg,
)
from engine.detect.sustained_loopback_vad_trigger import (
    SustainedLoopbackVadConfig,
    SustainedLoopbackVadTrigger,
)
from engine.detect.windows_desktop_snapshot_via_ctypes import read_desktop_snapshot_via_ctypes

__all__ = [
    "DEFAULT_AUTO_START_SOURCES",
    "KNOWN_DETECTION_SOURCES",
    "AdHocCallSuspected",
    "AsyncClock",
    "AutoStart",
    "AutoStartRulesEngine",
    "ConsentStoreEntry",
    "DesktopSnapshot",
    "DetectionDecision",
    "DetectionRuleSettings",
    "DetectionService",
    "DetectionSignal",
    "MeetingAppDetected",
    "MeetingProcessWatcher",
    "MicrophoneInUse",
    "MicrophoneInUseDetector",
    "ProcessInfo",
    "SuggestCapture",
    "SuggestStop",
    "SustainedLoopbackVadConfig",
    "SustainedLoopbackVadTrigger",
    "SystemClock",
    "WindowInfo",
    "read_desktop_snapshot_via_ctypes",
    "read_microphone_consent_store_via_winreg",
]
