"""Typed contracts for bot-free meeting detection: signals in, decisions out.

Purpose: the single shared vocabulary for the ``engine.detect`` package.
Detectors (process watcher, mic-consent poller, loopback-VAD trigger) emit
*signals*; the rules engine consumes signals and emits *decisions*; the
detection service forwards decisions to the server wiring (deferred).

Pipeline position: engine/detect/* -> AutoStartRulesEngine -> DetectionService
-> (wiring pass) WS events ``meeting.detected`` / ``capture.suggest_stop``.

Security/compliance invariants upheld here:
- Detection is OBSERVATION ONLY: nothing in this package joins a meeting,
  records audio, or contacts the network. Signals are derived exclusively
  from local process/window/registry/loopback-VAD state.
- Confidence values are validated on construction (fail closed: a garbage
  confidence must never silently drive an auto-start decision).
- ``KNOWN_DETECTION_SOURCES`` is the deny-by-default allowlist: a source
  string outside it may only ever SUGGEST, never auto-start (enforced in
  ``auto_start_rules_engine``).
"""

import math
from dataclasses import dataclass

# --- Canonical detection source identifiers (deny-by-default allowlist) ----
SOURCE_ZOOM = "zoom"
SOURCE_TEAMS = "teams"
SOURCE_DISCORD = "discord"
SOURCE_SLACK = "slack"
SOURCE_SKYPE = "skype"
SOURCE_BROWSER_MEET = "browser_meet"
SOURCE_BROWSER_ZOOM = "browser_zoom"
SOURCE_BROWSER_TEAMS = "browser_teams"
SOURCE_BROWSER_WHEREBY = "browser_whereby"
SOURCE_BROWSER_WEBEX = "browser_webex"
SOURCE_BLUEJEANS = "bluejeans"
SOURCE_GOTO = "gotomeeting"
SOURCE_RINGCENTRAL = "ringcentral"
SOURCE_CHIME = "chime"
SOURCE_WHATSAPP = "whatsapp"
SOURCE_TELEGRAM = "telegram"
SOURCE_ADHOC_LOOPBACK = "adhoc_loopback"

# Deny-by-default: only these sources may EVER auto-start (and then only if
# the user additionally opted the source into auto-start in settings).
KNOWN_DETECTION_SOURCES: frozenset[str] = frozenset(
    {
        SOURCE_ZOOM,
        SOURCE_TEAMS,
        SOURCE_DISCORD,
        SOURCE_SLACK,
        SOURCE_SKYPE,
        SOURCE_BROWSER_MEET,
        SOURCE_BROWSER_ZOOM,
        SOURCE_BROWSER_TEAMS,
        SOURCE_BROWSER_WHEREBY,
        SOURCE_BROWSER_WEBEX,
        SOURCE_BLUEJEANS,
        SOURCE_GOTO,
        SOURCE_RINGCENTRAL,
        SOURCE_CHIME,
        SOURCE_WHATSAPP,
        SOURCE_TELEGRAM,
        SOURCE_ADHOC_LOOPBACK,
    }
)

# Product default: auto-start every known *meeting app* source. Ad-hoc
# loopback stays opt-in — sustained speaker audio alone is too easy to
# confuse with YouTube / music.
DEFAULT_AUTO_START_SOURCES: frozenset[str] = frozenset(
    source for source in KNOWN_DETECTION_SOURCES if source != SOURCE_ADHOC_LOOPBACK
)


def _validate_confidence(confidence: float) -> None:
    """Fail closed: NaN / out-of-range confidence raises immediately."""
    if math.isnan(confidence) or not (0.0 <= confidence <= 1.0):
        raise ValueError(f"confidence must be in [0, 1], got {confidence!r}")


# --- Desktop snapshot (input to the process watcher) -----------------------


@dataclass(frozen=True)
class ProcessInfo:
    """One running process: pid + executable base name (e.g. ``Zoom.exe``)."""

    pid: int
    exe_name: str


@dataclass(frozen=True)
class WindowInfo:
    """One visible top-level window: owning pid + full title text."""

    pid: int
    title: str


@dataclass(frozen=True)
class DesktopSnapshot:
    """Point-in-time view of processes + visible window titles.

    Produced by ``windows_desktop_snapshot_via_ctypes`` in production and by
    plain fakes in tests — the watcher never touches OS APIs directly.
    """

    processes: tuple[ProcessInfo, ...]
    windows: tuple[WindowInfo, ...]


# --- Signals (detector outputs) ---------------------------------------------


@dataclass(frozen=True)
class MeetingAppDetected:
    """A meeting app / meeting-shaped window was observed.

    ``evidence`` is ``"process"`` (app merely running: weak — Zoom idling in
    the tray is not a meeting) or ``"window_title"`` (a meeting-shaped window
    title: strong). The rules engine combines weak evidence with mic-in-use
    corroboration before suggesting.
    """

    source: str
    app: str
    window_title_hint: str | None
    confidence: float
    evidence: str  # "process" | "window_title"

    def __post_init__(self) -> None:
        _validate_confidence(self.confidence)


@dataclass(frozen=True)
class MicrophoneInUse:
    """An app currently holds the microphone per the Windows consent store.

    Corroboration-only: a crashed app can leave a stale in-use marker, so
    this signal alone never suggests and NEVER auto-starts (fail closed).
    """

    app_name: str  # exe base name (NonPackaged) or package family prefix
    is_packaged: bool


@dataclass(frozen=True)
class AdHocCallSuspected:
    """Sustained speech on the render device with no capture running."""

    source: str  # always SOURCE_ADHOC_LOOPBACK
    speech_seconds_in_window: float
    rolling_window_s: float
    confidence: float

    def __post_init__(self) -> None:
        _validate_confidence(self.confidence)


DetectionSignal = MeetingAppDetected | MicrophoneInUse | AdHocCallSuspected


# --- Decisions (rules-engine outputs) ---------------------------------------


@dataclass(frozen=True)
class SuggestCapture:
    """Raise the one-click "Start capturing?" card. Never auto-acts."""

    reason: str
    source: str
    confidence: float
    dedupe_key: str

    def __post_init__(self) -> None:
        _validate_confidence(self.confidence)


@dataclass(frozen=True)
class AutoStart:
    """Start capture without asking — ONLY for known sources the user has
    explicitly opted into auto-start (deny by default everywhere else)."""

    reason: str
    source: str
    confidence: float

    def __post_init__(self) -> None:
        _validate_confidence(self.confidence)


@dataclass(frozen=True)
class SuggestStop:
    """The meeting appears over while capture is still running."""

    reason: str


DetectionDecision = SuggestCapture | AutoStart | SuggestStop
