"""Production capture backend: pyaudiowpatch (PortAudio + WASAPI loopback).

Purpose: implements ``engine.audio.dual_stream_capture_controller.CaptureBackend``
on real Windows hardware — probes the CURRENT default render device's
WASAPI loopback ("them") and the default microphone ("me"), and opens
callback-driven int16 capture streams on them.

WHY a fresh PyAudio instance per probe: PortAudio freezes its device list
and default-device indices at ``Pa_Initialize``. Re-instantiating per
probe (~tens of ms, off the event loop) is the reliable way to observe a
default-device change; instances are refcounted so this is safe alongside
open streams.

Open resilience (Zoom / exclusive-mode hosts):
- Cap channels at 2 — requesting maxInputChannels (often 8+) against a
  stereo mix format is a common -9999 Unanticipated host error source.
- Retry with short backoff and alternate sample rates (device default,
  48000, 44100) when the first open fails.
- Prefer shared-mode WASAPI defaults (PortAudio's default); never request
  exclusive mode.

Pipeline position: the hardware edge of the capture path; everything above
it is testable with fake backends.

Security invariant: raw audio goes straight to the controller callback and
is never persisted or logged here (local-only invariant).
"""

from __future__ import annotations

import contextlib
import logging
import time
from collections.abc import Callable
from typing import Any

from engine.audio.audio_frame_types import StreamLabel
from engine.audio.dual_stream_capture_controller import CaptureDeviceSpec

logger = logging.getLogger(__name__)

# ~20 ms callback chunks: small enough for low latency, large enough that
# the callback rate (50/s) costs nothing.
_CHUNK_SECONDS = 0.02
_MIN_FRAMES_PER_BUFFER = 128
# Stereo is enough for loopback/mic; asking for 6–8ch against a 2ch mix → -9999.
_MAX_OPEN_CHANNELS = 2
_OPEN_ATTEMPTS = 3
_OPEN_RETRY_SLEEP_S = 0.2
_ALT_SAMPLE_RATES = (48000, 44100, 16000)


def _spec_from_device_info(info: dict[str, Any]) -> CaptureDeviceSpec:
    """Map a PortAudio device-info dict to our typed spec.

    ``key`` combines index and name: PortAudio may reuse an index after a
    topology change, and names alone can collide (two identical headsets),
    so the pair is the stable-enough identity for change detection.
    """
    raw_channels = max(1, int(info["maxInputChannels"]))
    return CaptureDeviceSpec(
        key=f"{info['index']}:{info['name']}",
        name=str(info["name"]),
        sample_rate=int(info["defaultSampleRate"]),
        channels=min(_MAX_OPEN_CHANNELS, raw_channels),
    )


def _candidate_rates(preferred: int) -> list[int]:
    """Device default first, then common mix rates (deduped)."""
    ordered = [preferred, *_ALT_SAMPLE_RATES]
    seen: set[int] = set()
    out: list[int] = []
    for rate in ordered:
        if rate > 0 and rate not in seen:
            seen.add(rate)
            out.append(rate)
    return out


def _candidate_channels(preferred: int) -> list[int]:
    """Preferred channel count first, then mono/stereo fallbacks for -9999."""
    preferred_ch = min(_MAX_OPEN_CHANNELS, max(1, preferred))
    ordered = [preferred_ch]
    for alt in (1, 2):
        if alt not in ordered:
            ordered.append(alt)
    return ordered


class _PyAudioStreamHandle:
    """Owns one PyAudio instance + one open stream; closes both together."""

    def __init__(
        self,
        pyaudio_instance: Any,
        stream: Any,
        *,
        sample_rate: int,
        channels: int,
    ) -> None:
        self._pyaudio = pyaudio_instance
        self._stream = stream
        self._closed = False
        # Actual open format (may differ from the probe spec after rate retry).
        self.sample_rate = sample_rate
        self.channels = channels

    @property
    def is_alive(self) -> bool:
        """False once the device stalls/vanishes (PortAudio deactivates it)."""
        if self._closed:
            return False
        try:
            return bool(self._stream.is_active())
        except OSError:
            return False  # Stream torn down under us — treat as dead.

    def close(self) -> None:
        """Stop and release stream + PortAudio instance (idempotent)."""
        if self._closed:
            return
        self._closed = True
        for step in (self._stream.stop_stream, self._stream.close, self._pyaudio.terminate):
            # Device may already be gone; releasing the rest still matters.
            with contextlib.suppress(OSError):
                step()


class PyAudioWpatchCaptureBackend:
    """Real-hardware ``CaptureBackend`` backed by pyaudiowpatch."""

    def probe_default_device(self, stream: StreamLabel) -> CaptureDeviceSpec:
        """Return the current default endpoint for the stream label.

        ``them``: the WASAPI loopback twin of the default render device —
        this is what makes capture headphone-proof (we tap the render mix,
        not a microphone picking up speakers).
        ``me``: the default input device (microphone).
        """
        import pyaudiowpatch as pyaudio  # Lazy: Windows-only dependency.

        instance = pyaudio.PyAudio()  # Fresh instance -> fresh default-device view.
        try:
            if stream is StreamLabel.THEM:
                info = instance.get_default_wasapi_loopback()
            else:
                info = instance.get_default_input_device_info()
            return _spec_from_device_info(dict(info))
        finally:
            instance.terminate()

    def resolve_input_device(self, key: str) -> CaptureDeviceSpec:
        """Look up an input device by ``"{index}:{name}"`` PortAudio key.

        Fail closed: unknown index, non-input device, or PortAudio errors
        raise — never silently substitute the Windows default mic.
        """
        import pyaudiowpatch as pyaudio  # Lazy: Windows-only dependency.

        try:
            device_index = int(key.split(":", 1)[0])
        except (ValueError, IndexError) as exc:
            raise LookupError(f"invalid mic device key: {key!r}") from exc
        instance = pyaudio.PyAudio()
        try:
            info = dict(instance.get_device_info_by_index(device_index))
            info.setdefault("index", device_index)
            if int(info.get("maxInputChannels", 0)) < 1:
                raise LookupError(f"device {key!r} is not an input device")
            return _spec_from_device_info(info)
        except LookupError:
            raise
        except Exception as exc:
            raise LookupError(f"could not resolve mic device {key!r}: {exc}") from exc
        finally:
            instance.terminate()

    def open_capture_stream(
        self, spec: CaptureDeviceSpec, on_chunk: Callable[[bytes, float], None]
    ) -> _PyAudioStreamHandle:
        """Open a callback-driven int16 capture stream on ``spec``.

        Retries across sample rates — Zoom and other hosts often leave the
        device in a mix format that rejects the first open attempt (-9999).
        """
        import pyaudiowpatch as pyaudio  # Lazy: Windows-only dependency.

        device_index = int(spec.key.split(":", 1)[0])
        last_error: OSError | None = None

        for attempt in range(_OPEN_ATTEMPTS):
            for rate in _candidate_rates(spec.sample_rate):
                for channels in _candidate_channels(spec.channels):
                    instance = pyaudio.PyAudio()

                    def callback(
                        in_data: bytes | None,
                        frame_count: int,
                        time_info: Any,
                        status: Any,
                        _on_chunk: Callable[[bytes, float], None] = on_chunk,
                    ) -> tuple[None, int]:
                        if in_data:
                            _on_chunk(in_data, time.monotonic())
                        return (None, pyaudio.paContinue)

                    try:
                        stream = instance.open(
                            format=pyaudio.paInt16,
                            channels=channels,
                            rate=rate,
                            frames_per_buffer=max(
                                _MIN_FRAMES_PER_BUFFER, int(rate * _CHUNK_SECONDS)
                            ),
                            input=True,
                            input_device_index=device_index,
                            stream_callback=callback,
                        )
                    except OSError as exc:
                        last_error = exc
                        with contextlib.suppress(OSError):
                            instance.terminate()
                        logger.warning(
                            "open failed for %r (rate=%d ch=%d attempt=%d): %s",
                            spec.name,
                            rate,
                            channels,
                            attempt + 1,
                            exc,
                        )
                        continue
                    if rate != spec.sample_rate or channels != spec.channels:
                        logger.info(
                            "opened %r at rate=%d ch=%d (spec was %d Hz / %d ch)",
                            spec.name,
                            rate,
                            channels,
                            spec.sample_rate,
                            spec.channels,
                        )
                    return _PyAudioStreamHandle(
                        instance, stream, sample_rate=rate, channels=channels
                    )
            if attempt + 1 < _OPEN_ATTEMPTS:
                time.sleep(_OPEN_RETRY_SLEEP_S)

        assert last_error is not None  # noqa: S101 — loop always assigns on failure
        raise OSError(
            f"{last_error} — device {spec.name!r} may be held by Zoom/Teams "
            "(try Start capture again, or pick another mic in Settings → Audio)"
        ) from last_error
