"""Adversarial pattern table for meeting-app process/window classification.

Pins the exact-match discipline (teamspeak.exe is NOT Teams, a discord.com
blog tab is NOT a voice call), unicode/case handling, one-signal-per-source
dedup, evidence strengths, and the watcher's fail-closed poll behaviour.
"""

import pytest

from engine.detect.detection_signal_types import (
    SOURCE_BROWSER_MEET,
    SOURCE_BROWSER_TEAMS,
    SOURCE_BROWSER_WEBEX,
    SOURCE_BROWSER_WHEREBY,
    SOURCE_BROWSER_ZOOM,
    SOURCE_DISCORD,
    SOURCE_SLACK,
    SOURCE_TEAMS,
    SOURCE_ZOOM,
    DesktopSnapshot,
    MeetingAppDetected,
    ProcessInfo,
    WindowInfo,
)
from engine.detect.meeting_process_watcher import (
    MeetingProcessWatcher,
    classify_desktop_snapshot,
)


def snap(
    processes: list[tuple[int, str]] | None = None,
    windows: list[tuple[int, str]] | None = None,
) -> DesktopSnapshot:
    return DesktopSnapshot(
        processes=tuple(ProcessInfo(pid=p, exe_name=n) for p, n in (processes or [])),
        windows=tuple(WindowInfo(pid=p, title=t) for p, t in (windows or [])),
    )


def by_source(signals: tuple[MeetingAppDetected, ...]) -> dict[str, MeetingAppDetected]:
    return {s.source: s for s in signals}


# --- process-name matching: exact, case-insensitive, near-misses excluded ---


@pytest.mark.parametrize(
    ("exe_name", "expected_source"),
    [
        ("Zoom.exe", SOURCE_ZOOM),
        ("zoom.exe", SOURCE_ZOOM),
        ("ZOOM.EXE", SOURCE_ZOOM),
        ("ms-teams.exe", SOURCE_TEAMS),
        ("MS-Teams.exe", SOURCE_TEAMS),
        ("Teams.exe", SOURCE_TEAMS),
        ("Discord.exe", SOURCE_DISCORD),
        ("Slack.exe", SOURCE_SLACK),
    ],
)
def test_known_process_names_match_case_insensitively(exe_name: str, expected_source: str) -> None:
    signals = classify_desktop_snapshot(snap(processes=[(100, exe_name)]))
    assert len(signals) == 1
    assert signals[0].source == expected_source
    assert signals[0].evidence == "process"
    assert signals[0].app == exe_name


@pytest.mark.parametrize(
    "exe_name",
    [
        "teamspeak.exe",  # substring near-miss for teams
        "TeamSpeak3.exe",
        "zoomit.exe",  # Sysinternals ZoomIt is not Zoom
        "zoom.exe.bak",
        "notdiscord.exe",
        "discords.exe",
        "slack-cleaner.exe",
        "chrome.exe",
        "explorer.exe",
        "",
    ],
)
def test_near_miss_process_names_never_match(exe_name: str) -> None:
    assert classify_desktop_snapshot(snap(processes=[(100, exe_name)])) == ()


def test_process_evidence_is_weak_below_suggestion_grade() -> None:
    """Idling tray apps must stay below the default 0.6 suggest threshold."""
    for exe in ("Zoom.exe", "ms-teams.exe", "Discord.exe", "Slack.exe"):
        signals = classify_desktop_snapshot(snap(processes=[(1, exe)]))
        assert signals[0].confidence < 0.6


# --- window-title matching --------------------------------------------------


def test_zoom_meeting_window_is_strong_evidence() -> None:
    signals = classify_desktop_snapshot(snap(windows=[(5, "Zoom Meeting")]))
    only = by_source(signals)[SOURCE_ZOOM]
    assert only.evidence == "window_title"
    assert only.confidence == 0.9
    assert only.window_title_hint == "Zoom Meeting"


@pytest.mark.parametrize(
    "title",
    [
        "Zoom Meeting",
        "Zoom Webinar",
        "Zoom Workplace - Meeting",
        "in a Zoom meeting",
        "Zoom - Standup sync",
    ],
)
def test_modern_zoom_meeting_titles_are_strong(title: str) -> None:
    signals = classify_desktop_snapshot(snap(windows=[(5, title)]))
    assert by_source(signals)[SOURCE_ZOOM].confidence >= 0.85


def test_zoom_hybrid_conf_process_clears_suggest_threshold() -> None:
    """Zoom's in-call helper process must clear the suggest threshold alone."""
    signals = classify_desktop_snapshot(snap(processes=[(9, "ZoomHybridConf.exe")]))
    only = by_source(signals)[SOURCE_ZOOM]
    assert only.evidence == "process"
    assert only.confidence >= 0.6


def test_teams_call_host_process_needs_mic_to_suggest() -> None:
    """CptHost can linger; keep it under the suggest floor without mic."""
    signals = classify_desktop_snapshot(snap(processes=[(11, "CptHost.exe")]))
    only = by_source(signals)[SOURCE_TEAMS]
    assert only.confidence < 0.6


def test_idle_zoom_workplace_title_alone_is_not_a_meeting() -> None:
    """Idle Zoom shell must not toast — needs Meeting / HybridConf / mic."""
    signals = classify_desktop_snapshot(
        snap(processes=[(1, "Zoom.exe")], windows=[(1, "Zoom Workplace")])
    )
    zoom = by_source(signals).get(SOURCE_ZOOM)
    assert zoom is not None
    assert zoom.confidence < 0.6


def test_webex_host_process_and_meeting_title() -> None:
    by_proc = by_source(
        classify_desktop_snapshot(snap(processes=[(2, "WebexHost.exe")]))
    )
    assert by_proc[SOURCE_BROWSER_WEBEX].confidence >= 0.6
    by_both = by_source(
        classify_desktop_snapshot(
            snap(
                processes=[(2, "WebexHost.exe")],
                windows=[(2, "Cisco Webex Meeting")],
            )
        )
    )
    assert by_both[SOURCE_BROWSER_WEBEX].confidence >= 0.75


def test_skype_call_window_owned_by_skype() -> None:
    from engine.detect.detection_signal_types import SOURCE_SKYPE

    signals = classify_desktop_snapshot(
        snap(
            processes=[(3, "Skype.exe")],
            windows=[(3, "Call with Alex - Skype")],
        )
    )
    assert by_source(signals)[SOURCE_SKYPE].confidence >= 0.75



def test_zoom_webinar_and_unicode_titles_match() -> None:
    signals = classify_desktop_snapshot(
        # Real-world titles carry en/em dashes; deliberate here. noqa: RUF001
        snap(windows=[(5, "会議 – ZOOM WEBINAR – ズーム"), (6, "Réunion — Zoom Meeting")])  # noqa: RUF001
    )
    assert by_source(signals)[SOURCE_ZOOM].confidence == 0.9


def test_window_title_beats_process_evidence_one_signal_per_source() -> None:
    signals = classify_desktop_snapshot(
        snap(processes=[(10, "Zoom.exe")], windows=[(10, "Zoom Meeting")])
    )
    assert len(signals) == 1  # deduped: one signal for the zoom source
    assert signals[0].confidence == 0.9
    assert signals[0].evidence == "window_title"


def test_teams_title_requires_meeting_word() -> None:
    chat_only = classify_desktop_snapshot(snap(windows=[(1, "Chat | Microsoft Teams")]))
    assert SOURCE_TEAMS not in by_source(chat_only)
    meeting = classify_desktop_snapshot(
        snap(windows=[(1, "Meeting with Alex | Microsoft Teams")])
    )
    assert by_source(meeting)[SOURCE_TEAMS].confidence == 0.75


def test_teams_browser_url_is_browser_teams_not_native_teams() -> None:
    signals = classify_desktop_snapshot(
        snap(windows=[(1, "Meeting | teams.microsoft.com - Google Chrome")])
    )
    sources = by_source(signals)
    assert SOURCE_BROWSER_TEAMS in sources
    # "teams.microsoft.com" must NOT satisfy the native "microsoft teams" marker.
    assert SOURCE_TEAMS not in sources


def test_slack_huddle_requires_slack_owner_process() -> None:
    processes = [(20, "Slack.exe"), (30, "chrome.exe")]
    owned = classify_desktop_snapshot(
        snap(processes=processes, windows=[(20, "Huddle: #standup - Slack")])
    )
    assert by_source(owned)[SOURCE_SLACK].confidence == 0.85
    # Same word in a browser window: only the weak slack PROCESS signal remains.
    unowned = classify_desktop_snapshot(
        snap(processes=processes, windows=[(30, "How we run huddles - blog - Chrome")])
    )
    slack = by_source(unowned).get(SOURCE_SLACK)
    assert slack is not None and slack.evidence == "process" and slack.confidence == 0.2


@pytest.mark.parametrize(
    ("title", "expected_source"),
    [
        # En dashes below are deliberate: Meet/Whereby really title tabs this way.
        ("Meet – abc-defg-hij – Google Meet - Google Chrome", SOURCE_BROWSER_MEET),  # noqa: RUF001
        ("meet.google.com/abc-defg-hij - Microsoft Edge", SOURCE_BROWSER_MEET),
        ("GOOGLE MEET - lobby", SOURCE_BROWSER_MEET),
        ("Launch Meeting - zoom.us - Mozilla Firefox", SOURCE_BROWSER_ZOOM),
        ("Standup | teams.microsoft.com - Brave", SOURCE_BROWSER_TEAMS),
        ("Whereby – Design room", SOURCE_BROWSER_WHEREBY),  # noqa: RUF001
        ("Webex | join meeting", SOURCE_BROWSER_WEBEX),
        ("Обсуждение — meet.google.com — Яндекс.Браузер", SOURCE_BROWSER_MEET),
    ],
)
def test_browser_tab_titles_match_medium_confidence(title: str, expected_source: str) -> None:
    signals = classify_desktop_snapshot(snap(windows=[(1, title)]))
    match = by_source(signals)[expected_source]
    assert match.confidence == 0.65
    assert match.evidence == "window_title"
    assert match.window_title_hint == title


@pytest.mark.parametrize(
    "title",
    [
        "discord.com/blog — the state of voice - Google Chrome",  # blog tab != voice
        "My notes about tomorrow's calls.txt - Notepad",
        "Google Sheets - budget - Chrome",
        "zoominfo.com - sales - Chrome",  # zoominfo is not zoom.us
        "Meat & Greet recipes - Chrome",  # not "meet"
        "",
    ],
)
def test_non_meeting_titles_yield_no_signals(title: str) -> None:
    assert classify_desktop_snapshot(snap(windows=[(1, title)])) == ()


def test_empty_snapshot_yields_nothing() -> None:
    assert classify_desktop_snapshot(snap()) == ()


def test_output_is_deterministic_and_sorted_by_source() -> None:
    snapshot = snap(
        processes=[(1, "Discord.exe"), (2, "Zoom.exe")],
        windows=[(3, "meet.google.com - Edge"), (4, "Zoom Meeting")],
    )
    first = classify_desktop_snapshot(snapshot)
    second = classify_desktop_snapshot(snapshot)
    assert first == second
    assert [s.source for s in first] == sorted(s.source for s in first)


# --- watcher poll behaviour: fail closed, recover honestly ------------------


def test_watcher_poll_fails_closed_to_no_signals_and_records_error() -> None:
    calls = {"n": 0}

    def flaky_provider() -> DesktopSnapshot:
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("EnumWindows failed")
        return snap(windows=[(1, "Zoom Meeting")])

    watcher = MeetingProcessWatcher(flaky_provider)
    assert watcher.poll_once() == ()  # failure -> silence, never a crash
    assert watcher.last_error is not None and "EnumWindows" in watcher.last_error
    recovered = watcher.poll_once()
    assert [s.source for s in recovered] == [SOURCE_ZOOM]
    assert watcher.last_error is None  # recovery clears the degraded marker


def test_watcher_rejects_nonpositive_poll_interval() -> None:
    with pytest.raises(ValueError):
        MeetingProcessWatcher(lambda: snap(), poll_interval_s=0)


def test_signal_confidence_validation_fails_closed() -> None:
    with pytest.raises(ValueError):
        MeetingAppDetected(
            source=SOURCE_ZOOM,
            app="zoom.exe",
            window_title_hint=None,
            confidence=1.5,
            evidence="process",
        )
    with pytest.raises(ValueError):
        MeetingAppDetected(
            source=SOURCE_ZOOM,
            app="zoom.exe",
            window_title_hint=None,
            confidence=float("nan"),
            evidence="process",
        )


@pytest.mark.parametrize(
    ("exe_name", "expected_source"),
    [
        ("BlueJeans.exe", "bluejeans"),
        ("g2mcomm.exe", "gotomeeting"),
        ("RingCentral.exe", "ringcentral"),
        ("Chime.exe", "chime"),
        ("WhatsApp.exe", "whatsapp"),
        ("Telegram.exe", "telegram"),
        ("ZoomRooms.exe", SOURCE_ZOOM),
    ],
)
def test_additional_meeting_apps_match(exe_name: str, expected_source: str) -> None:
    signals = classify_desktop_snapshot(snap(processes=[(42, exe_name)]))
    assert len(signals) == 1
    assert signals[0].source == expected_source


def test_whatsapp_call_title_requires_whatsapp_owner() -> None:
    owned = classify_desktop_snapshot(
        snap(processes=[(7, "WhatsApp.exe")], windows=[(7, "WhatsApp Call")])
    )
    assert by_source(owned)["whatsapp"].evidence == "window_title"
    unowned = classify_desktop_snapshot(snap(windows=[(1, "WhatsApp Call")]))
    assert "whatsapp" not in by_source(unowned)


def test_default_auto_start_sources_cover_meeting_apps_not_adhoc() -> None:
    from engine.detect.detection_signal_types import (
        DEFAULT_AUTO_START_SOURCES,
        KNOWN_DETECTION_SOURCES,
        SOURCE_ADHOC_LOOPBACK,
    )

    assert SOURCE_ADHOC_LOOPBACK not in DEFAULT_AUTO_START_SOURCES
    assert DEFAULT_AUTO_START_SOURCES < KNOWN_DETECTION_SOURCES
    assert SOURCE_ZOOM in DEFAULT_AUTO_START_SOURCES
    assert "bluejeans" in DEFAULT_AUTO_START_SOURCES
