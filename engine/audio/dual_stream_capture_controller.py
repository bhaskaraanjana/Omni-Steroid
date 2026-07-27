"""Controller for simultaneous two-stream capture with device-change recovery.

Purpose: owns the two live capture streams — ``them`` (WASAPI loopback of
the default render device) and ``me`` (default microphone) — normalises
their audio through per-stream resamplers into the shared ring buffer, and
runs the default-device watchdog that reopens a stream when its endpoint
changes or dies.

Device-change / continuity mechanism (documented contract):
- A monitor task polls the backend for each stream's CURRENT default
  device every ``poll_interval_s`` (0.4 s). A change of device identity, or
  a dead stream (device vanished), triggers recovery: close old handle,
  open the new default with a FRESH resampler. Poll (0.4 s) + reopen
  (tens of ms) keeps recovery inside the 1 s requirement.
- Continuity is stitched by TIME, not by splicing samples: every frame is
  stamped from the shared ``time.monotonic()`` clock, so audio lost while
  the endpoint switched appears as an honest gap in the timeline — never
  stretched, never fabricated. Downstream (STT windowing) treats a gap as
  a discontinuity and resets its chunk alignment.

Pipeline position: instantiated per capture session by
``engine.stt.live_capture_service``; feeds
``engine.audio.timestamped_audio_ring_buffer``.

Security invariant: audio flows callback -> resampler -> ring buffer, all
in memory; nothing here touches disk or network (local-only invariant).
"""

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from engine.audio.audio_frame_types import PIPELINE_SAMPLE_RATE, AudioFrame, StreamLabel
from engine.audio.resample_to_16k_mono import StreamingResamplerTo16kMono
from engine.audio.stream_echo_canceller import StreamEchoCanceller
from engine.audio.timestamped_audio_ring_buffer import TimestampedAudioRingBuffer

logger = logging.getLogger(__name__)

# How often the monitor re-probes the default devices. WHY 0.4 s: with
# reopen time (~tens of ms) this bounds recovery well under the 1 s budget
# while keeping PortAudio re-enumeration cost negligible.
DEFAULT_DEVICE_POLL_INTERVAL_S = 0.4


@dataclass(frozen=True)
class CaptureDeviceSpec:
    """Identity + open parameters for one capture endpoint.

    ``key`` is the stable identity used for change detection (backend
    device index + name); ``name`` is the human-readable label surfaced in
    ``capture.device_changed`` events.
    """

    key: str
    name: str
    sample_rate: int
    channels: int


class CaptureStreamHandle(Protocol):
    """An open, running capture stream owned by the backend."""

    def close(self) -> None:
        """Stop and release the stream (idempotent)."""
        ...

    @property
    def is_alive(self) -> bool:
        """False once the underlying device stalls or vanishes."""
        ...


class CaptureBackend(Protocol):
    """Injectable audio backend. Production: pyaudiowpatch; tests: fakes.

    ``on_chunk`` receives (raw int16 PCM bytes, monotonic time just AFTER
    the chunk's last sample) and is called from an audio callback thread.
    """

    def probe_default_device(self, stream: StreamLabel) -> CaptureDeviceSpec:
        """Return the CURRENT default endpoint for the given stream."""
        ...

    def resolve_input_device(self, key: str) -> CaptureDeviceSpec:
        """Look up a capture input by ``"{index}:{name}"`` key (fail closed)."""
        ...

    def open_capture_stream(
        self, spec: CaptureDeviceSpec, on_chunk: Callable[[bytes, float], None]
    ) -> CaptureStreamHandle:
        """Open a callback-driven capture stream on the given endpoint."""
        ...


@dataclass
class _StreamState:
    """Book-keeping for one live stream (device, handle, resampler)."""

    spec: CaptureDeviceSpec
    handle: CaptureStreamHandle
    resampler: StreamingResamplerTo16kMono


class DualStreamCaptureController:
    """Runs both capture streams and their device-change watchdog."""

    def __init__(
        self,
        backend: CaptureBackend,
        ring_buffer: TimestampedAudioRingBuffer,
        on_device_changed: Callable[[StreamLabel, str, float], None] | None = None,
        poll_interval_s: float = DEFAULT_DEVICE_POLL_INTERVAL_S,
        echo_canceller: StreamEchoCanceller | None = None,
        preferred_me_device_key: str | None = None,
    ) -> None:
        self._backend = backend
        self._ring_buffer = ring_buffer
        self._on_device_changed = on_device_changed
        self._poll_interval_s = poll_interval_s
        self._echo_canceller = echo_canceller
        # When set, ME prefers this key; open/probe failures fall back to default.
        self._preferred_me_device_key = preferred_me_device_key
        self._streams: dict[StreamLabel, _StreamState] = {}
        self._monitor_task: asyncio.Task[None] | None = None
        self._running = False

    def _probe_for_label(self, label: StreamLabel) -> CaptureDeviceSpec:
        """Default endpoint, or the user-preferred ME mic when one is pinned."""
        if label is StreamLabel.ME and self._preferred_me_device_key is not None:
            return self._backend.resolve_input_device(self._preferred_me_device_key)
        return self._backend.probe_default_device(label)

    async def start(self) -> None:
        """Open both streams and start the device watchdog.

        Fails closed: if EITHER stream cannot open, everything opened so
        far is torn down and the error propagates — a half-capturing
        session that silently misses one side is worse than a loud error.
        """
        if self._running:
            raise RuntimeError("capture controller is already running")
        try:
            for label in (StreamLabel.THEM, StreamLabel.ME):
                # PortAudio probing/opening blocks -> keep it off the loop.
                self._streams[label] = await asyncio.to_thread(self._open_stream, label)
                # Brief gap: opening mic immediately after loopback can trip
                # WASAPI -9999 when Zoom/Teams already owns the session.
                if label is StreamLabel.THEM:
                    await asyncio.sleep(0.05)
        except Exception:
            await asyncio.to_thread(self._close_all_streams)
            raise
        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_default_devices())

    async def stop(self) -> None:
        """Stop the watchdog and close both streams (idempotent)."""
        self._running = False
        if self._monitor_task is not None:
            self._monitor_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._monitor_task
            self._monitor_task = None
        await asyncio.to_thread(self._close_all_streams)

    @property
    def device_names(self) -> dict[str, str]:
        """Current device name per stream label (for capture.started events)."""
        return {label.value: state.spec.name for label, state in self._streams.items()}

    def _open_stream(self, label: StreamLabel) -> _StreamState:
        """Probe the endpoint for ``label`` (preferred ME mic when set) and open it.

        Preferred ME mic is best-effort: if Zoom/Teams holds that endpoint
        (-9999 / LookupError), fall back to the Windows default mic so
        capture can still start rather than fail closed on a stale pick.
        """
        preferred_key = self._preferred_me_device_key
        preferred_failed: str | None = None
        try:
            spec = self._probe_for_label(label)
        except LookupError as exc:
            if label is StreamLabel.ME and preferred_key is not None:
                preferred_failed = str(exc)
                spec = self._backend.probe_default_device(label)
            else:
                raise

        state_box: dict[str, StreamingResamplerTo16kMono] = {
            "resampler": StreamingResamplerTo16kMono(spec.sample_rate, spec.channels)
        }

        def on_chunk(raw: bytes, t_end_monotonic: float) -> None:
            # Runs on a PortAudio callback thread: resample + buffer only,
            # never block. Errors are swallowed into a log because raising
            # inside the driver callback would kill the whole stream.
            try:
                samples = state_box["resampler"].process(raw)
            except ValueError:
                logger.exception("dropping malformed audio chunk on stream %s", label.value)
                return
            if samples.size == 0:
                return
            canceller = self._echo_canceller
            if canceller is not None:
                if label is StreamLabel.THEM:
                    canceller.feed_loopback(samples)
                elif label is StreamLabel.ME:
                    samples = canceller.process_mic(samples)
            t_start = t_end_monotonic - samples.size / PIPELINE_SAMPLE_RATE
            self._ring_buffer.append(
                AudioFrame(stream=label, samples=samples, t_start_monotonic=t_start)
            )

        try:
            handle = self._backend.open_capture_stream(spec, on_chunk)
        except OSError:
            if label is StreamLabel.ME and preferred_key is not None and preferred_failed is None:
                logger.warning(
                    "preferred mic %r failed to open; falling back to default",
                    preferred_key,
                )
                spec = self._backend.probe_default_device(label)
                state_box["resampler"] = StreamingResamplerTo16kMono(
                    spec.sample_rate, spec.channels
                )
                handle = self._backend.open_capture_stream(spec, on_chunk)
            else:
                raise
        # Align resampler with the format PortAudio actually opened.
        opened_rate = getattr(handle, "sample_rate", spec.sample_rate)
        opened_channels = getattr(handle, "channels", spec.channels)
        if opened_rate != spec.sample_rate or opened_channels != spec.channels:
            spec = CaptureDeviceSpec(
                key=spec.key,
                name=spec.name,
                sample_rate=int(opened_rate),
                channels=int(opened_channels),
            )
            state_box["resampler"] = StreamingResamplerTo16kMono(
                spec.sample_rate, spec.channels
            )
        if preferred_failed is not None:
            logger.warning(
                "preferred mic unavailable (%s); using default %r",
                preferred_failed,
                spec.name,
            )
        logger.info(
            "capture stream %s open on %r (%d Hz, %d ch)",
            label.value,
            spec.name,
            spec.sample_rate,
            spec.channels,
        )
        return _StreamState(spec=spec, handle=handle, resampler=state_box["resampler"])

    def _close_all_streams(self) -> None:
        for state in self._streams.values():
            with contextlib.suppress(Exception):  # Best-effort teardown.
                state.handle.close()
        self._streams.clear()

    async def _monitor_default_devices(self) -> None:
        """Watchdog: re-probe defaults; reopen a stream on change or death."""
        while self._running:
            await asyncio.sleep(self._poll_interval_s)
            for label in list(self._streams):
                try:
                    await self._recover_stream_if_needed(label)
                except Exception:
                    # Keep watching: a transient probe failure (device list
                    # mid-churn) must not kill the watchdog. Next tick retries.
                    logger.exception("device watchdog error on stream %s", label.value)

    async def _recover_stream_if_needed(self, label: StreamLabel) -> None:
        """One watchdog tick for one stream: detect, then recover."""
        state = self._streams[label]
        current_spec = await asyncio.to_thread(self._probe_for_label, label)
        if current_spec.key == state.spec.key and state.handle.is_alive:
            return  # Same default device and still flowing — nothing to do.
        recovery_started = time.perf_counter()
        with contextlib.suppress(Exception):  # Old handle may already be dead.
            await asyncio.to_thread(state.handle.close)
        self._streams[label] = await asyncio.to_thread(self._open_stream, label)
        recovered_ms = (time.perf_counter() - recovery_started) * 1000.0
        new_name = self._streams[label].spec.name
        logger.info(
            "stream %s recovered onto %r in %.0f ms", label.value, new_name, recovered_ms
        )
        if self._on_device_changed is not None:
            self._on_device_changed(label, new_name, recovered_ms)
