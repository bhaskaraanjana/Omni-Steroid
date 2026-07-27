"""Meeting-app detection from process names + visible window titles.

Purpose: classify a ``DesktopSnapshot`` (running processes + window titles)
into ``MeetingAppDetected`` signals — Zoom / Teams / Discord / Slack native
apps and browser tabs on meet.google.com / zoom.us / teams.microsoft.com /
whereby / webex. This is how Omni notices a meeting WITHOUT joining anything.

Pipeline position: ``windows_desktop_snapshot_via_ctypes`` (or a test fake)
-> ``MeetingProcessWatcher.poll_once`` -> ``AutoStartRulesEngine``.

Evidence model (documented contract):
- ``process`` evidence is WEAK: Zoom/Teams/Discord/Slack all idle in the
  tray, so a running exe alone proves nothing. Weak signals only matter when
  the rules engine corroborates them with a mic-in-use signal.
- ``window_title`` evidence is STRONG(er): an actual meeting-shaped window
  title ("Zoom Meeting", a Slack huddle window, a Meet tab). Browser-tab
  matches stay MEDIUM: an open tab is not necessarily a joined call.
- Process-name matching is EXACT (case-insensitive) on the executable base
  name — substring matching would make ``teamspeak.exe`` look like Teams.
- Slack huddle matching REQUIRES the window's owning process to be
  ``slack.exe`` — "huddle" is an ordinary English word that appears in
  article titles.

Security/compliance invariants:
- Observation only: reads a snapshot handed to it; never touches the
  network, never injects into or joins anything.
- Fail closed to silence: a snapshot-provider failure yields NO signals
  (and a recorded ``last_error``) — detection must never crash the engine
  and must never fabricate a meeting.
"""

import logging
from collections.abc import Callable

from engine.detect.detection_signal_types import (
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
    DesktopSnapshot,
    MeetingAppDetected,
)

logger = logging.getLogger(__name__)

# Exact executable base names (lower-case) -> (source, confidence).
# WHY exact equality: substring matching turns "teamspeak.exe" into Teams
# and "zoomit.exe" (Sysinternals) into Zoom — near-misses must not match.
# Meeting-grade processes (>= 0.6) clear the suggest threshold alone; idle
# tray apps stay weak (< 0.6) until a title or mic corroborates them.
_PROCESS_SIGNATURES: dict[str, tuple[str, float]] = {
    "zoom.exe": (SOURCE_ZOOM, 0.3),
    "zoomhybridconf.exe": (SOURCE_ZOOM, 0.7),  # Zoom's in-call helper
    "zoomrooms.exe": (SOURCE_ZOOM, 0.65),
    "ms-teams.exe": (SOURCE_TEAMS, 0.3),
    "teams.exe": (SOURCE_TEAMS, 0.3),
    "cpthost.exe": (SOURCE_TEAMS, 0.55),  # call host — needs mic to clear 0.6 alone
    "discord.exe": (SOURCE_DISCORD, 0.3),
    "slack.exe": (SOURCE_SLACK, 0.2),
    "skype.exe": (SOURCE_SKYPE, 0.3),
    "skypeapp.exe": (SOURCE_SKYPE, 0.3),
    "webexhost.exe": (SOURCE_BROWSER_WEBEX, 0.65),
    "ciscocollabhost.exe": (SOURCE_BROWSER_WEBEX, 0.65),
    "webex.exe": (SOURCE_BROWSER_WEBEX, 0.3),
    "bluejeans.exe": (SOURCE_BLUEJEANS, 0.35),
    "bluejeans.desktop.exe": (SOURCE_BLUEJEANS, 0.35),
    "g2mcomm.exe": (SOURCE_GOTO, 0.55),
    "g2mlauncher.exe": (SOURCE_GOTO, 0.3),
    "gotomeeting.exe": (SOURCE_GOTO, 0.35),
    "goto.exe": (SOURCE_GOTO, 0.3),
    "ringcentral.exe": (SOURCE_RINGCENTRAL, 0.35),
    "softphoneclient.exe": (SOURCE_RINGCENTRAL, 0.55),
    "chime.exe": (SOURCE_CHIME, 0.35),
    "whatsapp.exe": (SOURCE_WHATSAPP, 0.25),
    "telegram.exe": (SOURCE_TELEGRAM, 0.25),
}

# Case-folded substrings of window titles that mark an in-meeting NATIVE app
# window. Zoom's meeting window is reliably titled "Zoom Meeting"/"Zoom
# Webinar"; newer shells use "Zoom Workplace - Meeting" / "Zoom - <topic>".
_ZOOM_TITLE_MARKERS = (
    "zoom meeting",
    "zoom webinar",
    "zoom workplace - meeting",
    "in a zoom meeting",
)
_TEAMS_TITLE_MARKER = "microsoft teams"  # NB: NOT a substring of "teams.microsoft.com"
_TEAMS_MEETING_WORDS = ("meeting", "call", "compact view", "| meeting")
_SLACK_HUDDLE_MARKER = "huddle"
_SKYPE_CALL_MARKERS = ("call with", "skype call", " - skype")
_WEBEX_TITLE_MARKERS = ("cisco webex", "webex meeting", "webex |")
_DISCORD_CALL_MARKERS = ("voice connected", "streaming", "discord overlay")
_BLUEJEANS_TITLE_MARKERS = ("bluejeans", "blue jeans")
_GOTO_TITLE_MARKERS = ("gotomeeting", "goto meeting", "goto webinar")
_RINGCENTRAL_TITLE_MARKERS = ("ringcentral", "ring central")
_CHIME_TITLE_MARKERS = ("amazon chime", "chime meeting")
_WHATSAPP_CALL_MARKERS = ("whatsapp call", "voice call", "video call")
_TELEGRAM_CALL_MARKERS = ("telegram call", "voice chat", "video chat")

# Browser-tab title substrings (case-folded) -> source. A tab title normally
# embeds the page title and often the domain; these are the patterns the
# product contract names. Medium confidence: an open tab != a joined call.
_BROWSER_TITLE_SIGNATURES: tuple[tuple[str, str], ...] = (
    ("meet.google.com", SOURCE_BROWSER_MEET),
    ("google meet", SOURCE_BROWSER_MEET),
    ("zoom.us", SOURCE_BROWSER_ZOOM),
    ("zoom.com/j/", SOURCE_BROWSER_ZOOM),
    ("app.zoom.us", SOURCE_BROWSER_ZOOM),
    ("teams.microsoft.com", SOURCE_BROWSER_TEAMS),
    ("teams.live.com", SOURCE_BROWSER_TEAMS),
    ("whereby", SOURCE_BROWSER_WHEREBY),
    ("webex", SOURCE_BROWSER_WEBEX),
    ("bluejeans.com", SOURCE_BLUEJEANS),
    ("gotomeeting.com", SOURCE_GOTO),
    ("meet.goto.com", SOURCE_GOTO),
    ("ringcentral.com", SOURCE_RINGCENTRAL),
    ("chime.aws", SOURCE_CHIME),
)

_WINDOW_TITLE_CONFIDENCE_ZOOM = 0.9
_WINDOW_TITLE_CONFIDENCE_TEAMS = 0.75
_WINDOW_TITLE_CONFIDENCE_SLACK_HUDDLE = 0.85
_WINDOW_TITLE_CONFIDENCE_SKYPE = 0.8
_WINDOW_TITLE_CONFIDENCE_WEBEX = 0.8
_WINDOW_TITLE_CONFIDENCE_DISCORD = 0.8
_WINDOW_TITLE_CONFIDENCE_GENERIC = 0.8
_BROWSER_TAB_CONFIDENCE = 0.65


def _is_zoom_meeting_title(title_cf: str) -> bool:
    if any(marker in title_cf for marker in _ZOOM_TITLE_MARKERS):
        return True
    # "Zoom - <topic>" meeting windows; exclude the idle "Zoom Workplace" shell.
    return bool(title_cf.startswith("zoom - ") and "workplace" not in title_cf)


def classify_desktop_snapshot(snapshot: DesktopSnapshot) -> tuple[MeetingAppDetected, ...]:
    """Pure classification: snapshot in, at most one signal per source out.

    Deterministic: for each source the single strongest piece of evidence
    wins (window title beats process presence). Output order is sorted by
    source name so repeated identical snapshots yield identical tuples.
    """
    pid_to_exe = {p.pid: p.exe_name.casefold() for p in snapshot.processes}
    best: dict[str, MeetingAppDetected] = {}

    def offer(candidate: MeetingAppDetected) -> None:
        current = best.get(candidate.source)
        if current is None or candidate.confidence > current.confidence:
            best[candidate.source] = candidate

    for proc in snapshot.processes:
        signature = _PROCESS_SIGNATURES.get(proc.exe_name.casefold())
        if signature is not None:
            source, confidence = signature
            offer(
                MeetingAppDetected(
                    source=source,
                    app=proc.exe_name,
                    window_title_hint=None,
                    confidence=confidence,
                    evidence="process",
                )
            )

    for window in snapshot.windows:
        title_cf = window.title.casefold()
        owner_exe = pid_to_exe.get(window.pid, "")

        if _is_zoom_meeting_title(title_cf):
            offer(
                MeetingAppDetected(
                    source=SOURCE_ZOOM,
                    app=owner_exe or "zoom.exe",
                    window_title_hint=window.title,
                    confidence=_WINDOW_TITLE_CONFIDENCE_ZOOM,
                    evidence="window_title",
                )
            )
        # Teams: needs BOTH the app marker and a meeting-shaped word — every
        # Teams window carries "Microsoft Teams", only calls carry the rest.
        if _TEAMS_TITLE_MARKER in title_cf and any(
            word in title_cf for word in _TEAMS_MEETING_WORDS
        ):
            offer(
                MeetingAppDetected(
                    source=SOURCE_TEAMS,
                    app=owner_exe or "ms-teams.exe",
                    window_title_hint=window.title,
                    confidence=_WINDOW_TITLE_CONFIDENCE_TEAMS,
                    evidence="window_title",
                )
            )
        # Slack huddle: owner MUST be slack.exe ("huddle" is a common word).
        if _SLACK_HUDDLE_MARKER in title_cf and owner_exe == "slack.exe":
            offer(
                MeetingAppDetected(
                    source=SOURCE_SLACK,
                    app="slack.exe",
                    window_title_hint=window.title,
                    confidence=_WINDOW_TITLE_CONFIDENCE_SLACK_HUDDLE,
                    evidence="window_title",
                )
            )
        if owner_exe == "skype.exe" and any(m in title_cf for m in _SKYPE_CALL_MARKERS):
            offer(
                MeetingAppDetected(
                    source=SOURCE_SKYPE,
                    app="skype.exe",
                    window_title_hint=window.title,
                    confidence=_WINDOW_TITLE_CONFIDENCE_SKYPE,
                    evidence="window_title",
                )
            )
        if owner_exe == "discord.exe" and any(m in title_cf for m in _DISCORD_CALL_MARKERS):
            offer(
                MeetingAppDetected(
                    source=SOURCE_DISCORD,
                    app="discord.exe",
                    window_title_hint=window.title,
                    confidence=_WINDOW_TITLE_CONFIDENCE_DISCORD,
                    evidence="window_title",
                )
            )
        if any(m in title_cf for m in _WEBEX_TITLE_MARKERS) and (
            owner_exe in {"webexhost.exe", "webex.exe", "ciscocollabhost.exe"}
            or owner_exe.startswith("webex")
        ):
            offer(
                MeetingAppDetected(
                    source=SOURCE_BROWSER_WEBEX,
                    app=owner_exe or "webex",
                    window_title_hint=window.title,
                    confidence=_WINDOW_TITLE_CONFIDENCE_WEBEX,
                    evidence="window_title",
                )
            )
        if owner_exe.startswith("bluejeans") and any(
            m in title_cf for m in _BLUEJEANS_TITLE_MARKERS
        ):
            offer(
                MeetingAppDetected(
                    source=SOURCE_BLUEJEANS,
                    app=owner_exe,
                    window_title_hint=window.title,
                    confidence=_WINDOW_TITLE_CONFIDENCE_GENERIC,
                    evidence="window_title",
                )
            )
        if owner_exe in {"g2mcomm.exe", "g2mlauncher.exe", "gotomeeting.exe", "goto.exe"} and any(
            m in title_cf for m in _GOTO_TITLE_MARKERS
        ):
            offer(
                MeetingAppDetected(
                    source=SOURCE_GOTO,
                    app=owner_exe,
                    window_title_hint=window.title,
                    confidence=_WINDOW_TITLE_CONFIDENCE_GENERIC,
                    evidence="window_title",
                )
            )
        if (
            "ringcentral" in owner_exe or owner_exe == "softphoneclient.exe"
        ) and any(m in title_cf for m in _RINGCENTRAL_TITLE_MARKERS):
            offer(
                MeetingAppDetected(
                    source=SOURCE_RINGCENTRAL,
                    app=owner_exe,
                    window_title_hint=window.title,
                    confidence=_WINDOW_TITLE_CONFIDENCE_GENERIC,
                    evidence="window_title",
                )
            )
        if "chime" in owner_exe and any(m in title_cf for m in _CHIME_TITLE_MARKERS):
            offer(
                MeetingAppDetected(
                    source=SOURCE_CHIME,
                    app=owner_exe,
                    window_title_hint=window.title,
                    confidence=_WINDOW_TITLE_CONFIDENCE_GENERIC,
                    evidence="window_title",
                )
            )
        if owner_exe == "whatsapp.exe" and any(m in title_cf for m in _WHATSAPP_CALL_MARKERS):
            offer(
                MeetingAppDetected(
                    source=SOURCE_WHATSAPP,
                    app="whatsapp.exe",
                    window_title_hint=window.title,
                    confidence=_WINDOW_TITLE_CONFIDENCE_GENERIC,
                    evidence="window_title",
                )
            )
        if owner_exe == "telegram.exe" and any(m in title_cf for m in _TELEGRAM_CALL_MARKERS):
            offer(
                MeetingAppDetected(
                    source=SOURCE_TELEGRAM,
                    app="telegram.exe",
                    window_title_hint=window.title,
                    confidence=_WINDOW_TITLE_CONFIDENCE_GENERIC,
                    evidence="window_title",
                )
            )
        for marker, source in _BROWSER_TITLE_SIGNATURES:
            if marker in title_cf:
                offer(
                    MeetingAppDetected(
                        source=source,
                        app=owner_exe or "browser",
                        window_title_hint=window.title,
                        confidence=_BROWSER_TAB_CONFIDENCE,
                        evidence="window_title",
                    )
                )

    return tuple(best[source] for source in sorted(best))


class MeetingProcessWatcher:
    """Polls an injected snapshot provider and classifies each snapshot.

    The provider is injected (ctypes-backed in production, plain fakes in
    tests) so classification is deterministic and unit tests never touch
    Windows APIs. The DetectionService drives the poll cadence using
    ``poll_interval_s`` (default 3s per the product contract).
    """

    def __init__(
        self,
        snapshot_provider: Callable[[], DesktopSnapshot],
        poll_interval_s: float = 3.0,
    ) -> None:
        if poll_interval_s <= 0:
            raise ValueError("poll_interval_s must be > 0")
        self._snapshot_provider = snapshot_provider
        self.poll_interval_s = poll_interval_s
        self.last_error: str | None = None

    def poll_once(self) -> tuple[MeetingAppDetected, ...]:
        """One poll: snapshot -> signals. Fails closed to NO signals."""
        try:
            snapshot = self._snapshot_provider()
        except Exception as exc:  # fail closed: never crash, never fabricate
            first_failure = self.last_error is None
            self.last_error = f"{type(exc).__name__}: {exc}"
            # WHY first-failure-only at WARNING: this runs every ~3s and a
            # persistent failure would otherwise flood the audit-relevant log.
            log = logger.warning if first_failure else logger.debug
            log("desktop snapshot failed; meeting detection degraded: %s", self.last_error)
            return ()
        self.last_error = None
        return classify_desktop_snapshot(snapshot)
