"""Decision layer: detection signals + settings -> suggest / auto-start / stop.

Purpose: the single place where raw detection signals become user-facing
decisions. Everything upstream only OBSERVES; only this engine decides, and
it decides conservatively.

Pipeline position: MeetingProcessWatcher + MicrophoneInUseDetector +
SustainedLoopbackVadTrigger -> ``AutoStartRulesEngine.update`` (driven by
``DetectionService`` each poll tick) -> DetectionDecision callbacks.

Decision rules (documented contract):
- DENY BY DEFAULT: auto-start requires the source to be BOTH in
  ``KNOWN_DETECTION_SOURCES`` AND explicitly opted in via
  ``auto_start_sources`` AND above ``auto_start_min_confidence``. An
  unknown source string can therefore never auto-start — at most suggest.
- One suggestion per app-session: a session is continuous presence of a
  source (with ``session_end_grace_s`` tolerance for enumeration flicker);
  it must END and re-begin before the same source suggests again.
- Dismissal: ``dismiss(dedupe_key)`` suppresses that key for
  ``dismissed_cooldown_s``.
- Quiet while capturing: no suggest/auto-start decisions while capture is
  active; sessions that overlap an active capture are marked handled so
  they do not fire the moment capture stops.
- Mic corroboration: a mic-in-use signal attributable to a source boosts
  that source's confidence (capped) — this is how weak "Discord is running"
  evidence becomes a suggestion only when Discord actually holds the mic.
  A mic signal from an UNMAPPED app is ignored (dictation, voice typing).
- Auto-stop hint: if meeting evidence was seen during capture and then
  disappears for ``suggest_stop_grace_s``, emit ONE SuggestStop.

Security/compliance invariants:
- Approval-before-execute: SuggestCapture/SuggestStop are UI cards only;
  AutoStart is gated by the user's explicit per-source opt-in (deny by
  default) — this engine never executes anything itself.
- Deterministic: identical (now, signals, capture_active) histories yield
  identical decisions; time comes only from the injected ``now_s``.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from engine.detect.detection_signal_types import (
    KNOWN_DETECTION_SOURCES,
    SOURCE_BLUEJEANS,
    SOURCE_BROWSER_MEET,
    SOURCE_BROWSER_TEAMS,
    SOURCE_BROWSER_WEBEX,
    SOURCE_BROWSER_WHEREBY,
    SOURCE_BROWSER_ZOOM,
    SOURCE_CHIME,
    SOURCE_DISCORD,
    SOURCE_GOTO,
    SOURCE_RINGCENTRAL,
    SOURCE_SKYPE,
    SOURCE_SLACK,
    SOURCE_TEAMS,
    SOURCE_TELEGRAM,
    SOURCE_WHATSAPP,
    SOURCE_ZOOM,
    AdHocCallSuspected,
    AutoStart,
    DetectionDecision,
    DetectionSignal,
    MeetingAppDetected,
    MicrophoneInUse,
    SuggestCapture,
    SuggestStop,
)

# Exact (case-folded) app names from the mic consent store -> source they
# corroborate. WHY exact names: substring mapping would let "teamspeak"
# corroborate Teams — the same near-miss trap as process matching.
_MIC_APP_TO_SOURCE: dict[str, str] = {
    "zoom.exe": SOURCE_ZOOM,
    "zoomhybridconf.exe": SOURCE_ZOOM,
    "zoomrooms.exe": SOURCE_ZOOM,
    "ms-teams.exe": SOURCE_TEAMS,
    "teams.exe": SOURCE_TEAMS,
    "cpthost.exe": SOURCE_TEAMS,
    "msteams": SOURCE_TEAMS,  # packaged Teams family name prefix
    "discord.exe": SOURCE_DISCORD,
    "slack.exe": SOURCE_SLACK,
    "skype.exe": SOURCE_SKYPE,
    "skypeapp.exe": SOURCE_SKYPE,
    "webexhost.exe": SOURCE_BROWSER_WEBEX,
    "webex.exe": SOURCE_BROWSER_WEBEX,
    "bluejeans.exe": SOURCE_BLUEJEANS,
    "bluejeans.desktop.exe": SOURCE_BLUEJEANS,
    "g2mcomm.exe": SOURCE_GOTO,
    "gotomeeting.exe": SOURCE_GOTO,
    "goto.exe": SOURCE_GOTO,
    "ringcentral.exe": SOURCE_RINGCENTRAL,
    "softphoneclient.exe": SOURCE_RINGCENTRAL,
    "chime.exe": SOURCE_CHIME,
    "whatsapp.exe": SOURCE_WHATSAPP,
    "telegram.exe": SOURCE_TELEGRAM,
}

# A browser holding the mic corroborates any active browser_* source.
_BROWSER_MIC_APPS: frozenset[str] = frozenset(
    {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe", "vivaldi.exe"}
)
_BROWSER_SOURCES: frozenset[str] = frozenset(
    {
        SOURCE_BROWSER_MEET,
        SOURCE_BROWSER_ZOOM,
        SOURCE_BROWSER_TEAMS,
        SOURCE_BROWSER_WHEREBY,
        SOURCE_BROWSER_WEBEX,
    }
)

_CORROBORATED_CONFIDENCE_CAP = 0.95


@dataclass(frozen=True)
class DetectionRuleSettings:
    """User-facing knobs. Product default (SETTINGS_DEFAULTS) auto-starts every
    known meeting-app source; the engine itself still denies auto-start when
    ``auto_start_sources`` is empty (tests + explicit user opt-out)."""

    source_enabled: Mapping[str, bool] = field(default_factory=dict)  # absent -> enabled
    auto_start_sources: frozenset[str] = frozenset()  # empty = no auto-start
    suggest_min_confidence: float = 0.6
    auto_start_min_confidence: float = 0.85
    mic_corroboration_boost: float = 0.4
    dismissed_cooldown_s: float = 1800.0
    session_end_grace_s: float = 10.0
    suggest_stop_grace_s: float = 60.0

    def __post_init__(self) -> None:
        for name in ("suggest_min_confidence", "auto_start_min_confidence"):
            value = getattr(self, name)
            if not (0.0 < value <= 1.0):
                raise ValueError(f"{name} must be in (0, 1]")
        if not (0.0 <= self.mic_corroboration_boost <= 1.0):
            raise ValueError("mic_corroboration_boost must be in [0, 1]")
        for name in ("dismissed_cooldown_s", "session_end_grace_s", "suggest_stop_grace_s"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be >= 0")


@dataclass
class _SourceSession:
    """Mutable per-source presence tracking (one app-session)."""

    first_seen_s: float
    last_seen_s: float
    handled: bool = False  # suggested / auto-started / covered by a capture


class AutoStartRulesEngine:
    """Stateful, clock-injected decision engine (see module docstring)."""

    def __init__(self, settings: DetectionRuleSettings | None = None) -> None:
        self._settings = settings or DetectionRuleSettings()
        self._sessions: dict[str, _SourceSession] = {}
        self._dismissed_until_s: dict[str, float] = {}
        # Auto-stop tracking for the CURRENT capture run.
        self._meeting_seen_during_capture = False
        self._last_meeting_seen_during_capture_s = 0.0
        self._stop_suggested = False

    def apply_settings(self, settings: DetectionRuleSettings) -> None:
        """Hot-reload user knobs without resetting session state."""
        self._settings = settings

    def dismiss(self, dedupe_key: str, now_s: float) -> None:
        """User dismissed a suggestion card: suppress that key for the cooldown."""
        self._dismissed_until_s[dedupe_key] = now_s + self._settings.dismissed_cooldown_s
        session = self._sessions.get(dedupe_key)
        if session is not None:
            session.handled = True

    def rearm_suggestions_for_ui(self, now_s: float) -> None:
        """Clear ``handled`` so a freshly connected UI can see an active meeting.

        Why: suggest fires once per app-session. If the UI missed that event
        (wasn't mounted / reconnecting), the session stays handled forever
        while Zoom/Teams stays open — no toast ever appears. Rearm on the
        hub's 0→1 UI subscriber transition only; honour dismiss cooldown so
        "Not now" still sticks.

        Auto-start-eligible sources are excluded: clearing ``handled`` after a
        manual stop would re-emit ``AutoStart`` and restart capture against
        the user's explicit stop while the meeting app is still open.
        """
        for source, session in self._sessions.items():
            if now_s < self._dismissed_until_s.get(source, float("-inf")):
                continue
            # Exclude auto-start sources: reconnect must not resurrect auto-start.
            if (
                source in KNOWN_DETECTION_SOURCES
                and source in self._settings.auto_start_sources
            ):
                continue
            session.handled = False

    def update(
        self,
        now_s: float,
        signals: Sequence[DetectionSignal],
        capture_active: bool,
    ) -> list[DetectionDecision]:
        """One poll tick: reconcile presence, then decide. Deterministic."""
        confidences = self._aggregate_confidences(signals)
        self._reconcile_sessions(now_s, confidences.keys())

        decisions: list[DetectionDecision] = []
        if capture_active:
            self._observe_capture(now_s, confidences, decisions)
        else:
            # Capture ended (or never ran): reset per-capture auto-stop state.
            self._meeting_seen_during_capture = False
            self._stop_suggested = False
            self._decide_suggestions(now_s, confidences, decisions)
        return decisions

    # --- signal aggregation --------------------------------------------------

    def _aggregate_confidences(self, signals: Sequence[DetectionSignal]) -> dict[str, float]:
        """Per-source best confidence, with mic corroboration applied."""
        best: dict[str, float] = {}
        mic_sources: set[str] = set()
        browser_mic = False
        for signal in signals:
            if isinstance(signal, MeetingAppDetected | AdHocCallSuspected):
                best[signal.source] = max(best.get(signal.source, 0.0), signal.confidence)
            elif isinstance(signal, MicrophoneInUse):
                app_cf = signal.app_name.casefold()
                mapped = _MIC_APP_TO_SOURCE.get(app_cf)
                if mapped is not None:
                    mic_sources.add(mapped)
                elif app_cf in _BROWSER_MIC_APPS:
                    browser_mic = True
                # Unmapped mic use (dictation app, voice typing) is IGNORED:
                # mic-in-use alone is corroboration, never evidence of a meeting.
        for source in list(best):
            corroborated = source in mic_sources or (browser_mic and source in _BROWSER_SOURCES)
            if corroborated:
                best[source] = min(
                    best[source] + self._settings.mic_corroboration_boost,
                    _CORROBORATED_CONFIDENCE_CAP,
                )
        return best

    # --- session lifecycle ---------------------------------------------------

    def _reconcile_sessions(self, now_s: float, present_sources: Iterable[str]) -> None:
        """Open/refresh sessions for present sources; expire absent ones."""
        present = set(present_sources)
        for source in present:
            session = self._sessions.get(source)
            if session is None:
                self._sessions[source] = _SourceSession(first_seen_s=now_s, last_seen_s=now_s)
            else:
                session.last_seen_s = now_s
        # WHY a grace period: window/process enumeration flickers (minimised
        # windows, slow polls) — a blip must not end the session and re-arm
        # a duplicate suggestion for the SAME meeting.
        expired = [
            source
            for source, session in self._sessions.items()
            if source not in present
            and now_s - session.last_seen_s > self._settings.session_end_grace_s
        ]
        for source in expired:
            del self._sessions[source]

    # --- decisions -------------------------------------------------------------

    def _enabled(self, source: str) -> bool:
        return self._settings.source_enabled.get(source, True)

    def _decide_suggestions(
        self,
        now_s: float,
        confidences: Mapping[str, float],
        decisions: list[DetectionDecision],
    ) -> None:
        """Suggest/auto-start for unhandled, enabled, non-dismissed sessions."""
        for source in sorted(confidences):  # sorted: deterministic decision order
            confidence = confidences[source]
            session = self._sessions[source]
            if session.handled or not self._enabled(source):
                continue
            if now_s < self._dismissed_until_s.get(source, float("-inf")):
                continue  # user said no recently; honour it for the cooldown
            # DENY BY DEFAULT: all three gates must hold to auto-start —
            # known source AND explicit user opt-in AND high confidence.
            if (
                source in KNOWN_DETECTION_SOURCES
                and source in self._settings.auto_start_sources
                and confidence >= self._settings.auto_start_min_confidence
            ):
                session.handled = True
                decisions.append(
                    AutoStart(
                        reason=f"{source} meeting detected (user-enabled auto-start)",
                        source=source,
                        confidence=confidence,
                    )
                )
            elif confidence >= self._settings.suggest_min_confidence:
                session.handled = True
                decisions.append(
                    SuggestCapture(
                        reason=f"{source} meeting activity detected",
                        source=source,
                        confidence=confidence,
                        dedupe_key=source,
                    )
                )

    def _observe_capture(
        self,
        now_s: float,
        confidences: Mapping[str, float],
        decisions: list[DetectionDecision],
    ) -> None:
        """While capturing: stay quiet, mark overlapping sessions, hint stop."""
        meeting_present = False
        for source in confidences:
            # Covered by the running capture -> must not fire when it stops.
            self._sessions[source].handled = True
            if self._enabled(source):
                meeting_present = True
        if meeting_present:
            self._meeting_seen_during_capture = True
            self._last_meeting_seen_during_capture_s = now_s
            self._stop_suggested = False  # a (new) meeting is live again
        elif (
            self._meeting_seen_during_capture
            and not self._stop_suggested
            and now_s - self._last_meeting_seen_during_capture_s
            >= self._settings.suggest_stop_grace_s
        ):
            self._stop_suggested = True
            decisions.append(
                SuggestStop(reason="meeting app closed while capture is still running")
            )
