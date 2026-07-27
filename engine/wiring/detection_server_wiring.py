"""Server wiring: DetectionService -> WS events, VAD feed, device resets.

Purpose: composes M6's bot-free detection into the running engine per the
deferred spec in ``engine/detect/detection_service.py``:

- builds the service over the REAL probes (ctypes desktop snapshots,
  winreg mic consent store) with the deny-by-default rule settings;
- maps every ``DetectionDecision`` to its pinned WS event
  (``meeting.detected`` / ``capture.suggest_stop``) on the broadcast hub;
- exposes ``feed_vad_sample`` for the loopback VAD tap the capture service
  carries, and resets the sustained-VAD trigger on ``capture.device_changed``
  (a device swap must not carry stale speech accounting across endpoints).

Pipeline position: constructed by ``engine.server``'s production app;
``start()`` in lifespan startup, ``stop()`` on shutdown.

Security invariants:
- Observation only: decisions become SUGGESTION events; starting/stopping
  capture stays behind the user-driven command path
  (approval-before-execute). Auto-start requires the source to be in the
  user's ``detection_auto_start_sources`` list — product default enables
  every known meeting-app source (adhoc loopback stays opt-in).
- A failing broadcast is logged and dropped — detection can never take the
  engine down (fail closed, stay up).
"""

import asyncio
import logging
from collections.abc import Callable

from engine.detect import (
    AutoStart,
    AutoStartRulesEngine,
    DetectionDecision,
    DetectionService,
    MeetingProcessWatcher,
    MicrophoneInUseDetector,
    SuggestCapture,
    SuggestStop,
    SustainedLoopbackVadTrigger,
    read_desktop_snapshot_via_ctypes,
    read_microphone_consent_store_via_winreg,
)
from engine.detect.detection_settings_from_app import detection_rule_settings_from_effective
from engine.protocol import (
    EVENT_CAPTURE_DEVICE_CHANGED,
    EVENT_CAPTURE_SUGGEST_STOP,
    EVENT_MEETING_DETECTED,
    Envelope,
    EnvelopeKind,
    EventBroadcastHub,
    build_capture_suggest_stop_payload,
    build_meeting_detected_payload,
)

logger = logging.getLogger(__name__)


def decision_to_event(decision: DetectionDecision) -> tuple[str, dict[str, object]]:
    """Pure decision -> (event name, payload) mapping (tested exactly).

    SuggestCapture -> ``meeting.detected``     {source, reason, confidence, dedupe_key}
    AutoStart      -> ``meeting.detected``     {source, reason, confidence, auto_start: true}
    SuggestStop    -> ``capture.suggest_stop`` {reason}
    """
    if isinstance(decision, SuggestCapture):
        return EVENT_MEETING_DETECTED, build_meeting_detected_payload(
            decision.source, decision.reason, decision.confidence, dedupe_key=decision.dedupe_key
        )
    if isinstance(decision, AutoStart):
        return EVENT_MEETING_DETECTED, build_meeting_detected_payload(
            decision.source, decision.reason, decision.confidence, auto_start=True
        )
    if isinstance(decision, SuggestStop):
        return EVENT_CAPTURE_SUGGEST_STOP, build_capture_suggest_stop_payload(decision.reason)
    # Deny by default: an unknown decision type is a programming error, not
    # a broadcast — fail loudly here rather than invent a wire shape.
    raise TypeError(f"unknown detection decision: {decision!r}")


class DetectionServerWiring:
    """Owns the DetectionService + its hub bridges for one engine process."""

    def __init__(
        self,
        hub: EventBroadcastHub,
        is_capture_active: Callable[[], bool],
        service: DetectionService | None = None,
        vad_trigger: SustainedLoopbackVadTrigger | None = None,
    ) -> None:
        self._hub = hub
        self._vad_trigger = (
            vad_trigger if vad_trigger is not None else SustainedLoopbackVadTrigger()
        )
        # Real probes by default; tests inject a fully-faked service instead.
        self._service = (
            service
            if service is not None
            else DetectionService(
                process_watcher=MeetingProcessWatcher(read_desktop_snapshot_via_ctypes),
                microphone_detector=MicrophoneInUseDetector(
                    read_microphone_consent_store_via_winreg
                ),
                vad_trigger=self._vad_trigger,
                # Product default auto-starts known meeting apps; adhoc stays opt-in.
                # until the user opts sources in (settings UI, later).
                rules_engine=AutoStartRulesEngine(),
                is_capture_active=is_capture_active,
                on_decision=self._on_decision,
            )
        )
        # Strong refs for broadcast tasks so they are not GC'd mid-flight.
        self._broadcast_tasks: set[asyncio.Task[None]] = set()
        # Device swaps must reset the sustained-VAD accounting (stale speech
        # time from the old endpoint must not bill the new one).
        self._unsubscribe = hub.subscribe(self._on_hub_event)

    @property
    def service(self) -> DetectionService:
        """The service the dismiss dispatcher drives."""
        return self._service

    def feed_vad_sample(self, sample_ts_s: float, speech_probability: float) -> None:
        """The loopback VAD tap (event-loop thread; see capture service)."""
        self._service.feed_vad_sample(sample_ts_s, speech_probability)

    def apply_detection_settings(self, effective: dict[str, object]) -> None:
        """Hot-reload detection rules from the effective settings map."""
        self._service.apply_detection_settings(
            detection_rule_settings_from_effective(effective)
        )

    def _on_decision(self, decision: DetectionDecision) -> None:
        """DetectionService callback (event loop): broadcast the WS event."""
        try:
            name, payload = decision_to_event(decision)
        except TypeError:
            logger.exception("unmappable detection decision dropped")
            return
        # The poll tick is sync; the broadcast is async — schedule it.
        # Keep a strong ref + done-callback discard so the task is not GC'd
        # mid-flight (RUF006 / silent event drop).
        task = asyncio.get_running_loop().create_task(
            self._hub.broadcast_event(name, payload)
        )
        self._broadcast_tasks.add(task)
        task.add_done_callback(self._broadcast_tasks.discard)

    async def _on_hub_event(self, envelope: Envelope) -> None:
        """Hub subscriber: cheap, and NEVER raises (a raiser gets dropped)."""
        if envelope.kind is EnvelopeKind.EVENT and envelope.name == EVENT_CAPTURE_DEVICE_CHANGED:
            self._vad_trigger.reset()

    def start(self) -> None:
        """Begin polling (lifespan startup). Idempotent."""
        self._service.start()

    async def stop(self) -> None:
        """Stop polling and release the hub subscription (shutdown)."""
        self._unsubscribe()
        await self._service.stop()
