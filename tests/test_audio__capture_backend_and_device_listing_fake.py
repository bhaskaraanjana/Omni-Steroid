"""Adversarial tests for the pyaudiowpatch capture backend + device listing.

Both modules lazy-``import pyaudiowpatch`` INSIDE their functions, so the
whole Windows-only hardware edge is exercised here by injecting a FAKE
``pyaudiowpatch`` module into ``sys.modules`` — no PortAudio, no ctypes, no
audio device required. Every assertion pins EXACT behaviour (device-info
mapping, callback contract, fail-closed teardown, default-flag logic) so it
would FAIL if the mapping, parsing, or error handling regressed.

Also covers two small deterministic edges that the fake-backend controller
tests don't reach: the resampler ``flush`` passthrough return and the
capture ``on_chunk`` malformed/empty guards.
"""

import time
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from engine.audio import audio_device_listing
from engine.audio.audio_frame_types import PIPELINE_SAMPLE_RATE, StreamLabel
from engine.audio.dual_stream_capture_controller import (
    CaptureDeviceSpec,
    DualStreamCaptureController,
)
from engine.audio.pyaudiowpatch_capture_backend import (
    PyAudioWpatchCaptureBackend,
    _PyAudioStreamHandle,
    _spec_from_device_info,
)
from engine.audio.resample_to_16k_mono import StreamingResamplerTo16kMono
from engine.audio.timestamped_audio_ring_buffer import TimestampedAudioRingBuffer
from engine.protocol.device_listing_payloads import (
    DEVICE_KIND_CAPTURE,
    DEVICE_KIND_RENDER,
    AudioDeviceDescription,
)

# --------------------------------------------------------------------------
# _spec_from_device_info: exact PortAudio-dict -> typed-spec mapping.
# --------------------------------------------------------------------------


def test_spec_from_device_info_maps_every_field_exactly() -> None:
    spec = _spec_from_device_info(
        {"index": 3, "name": "Speakers", "defaultSampleRate": 48_000.0, "maxInputChannels": 2}
    )
    assert spec == CaptureDeviceSpec(
        key="3:Speakers", name="Speakers", sample_rate=48_000, channels=2
    )


def test_spec_from_device_info_truncates_float_rate_and_coerces_name() -> None:
    # int(44100.9) truncates toward zero -> 44100 (not rounded to 44101).
    spec = _spec_from_device_info(
        {"index": 7, "name": 12345, "defaultSampleRate": 44_100.9, "maxInputChannels": 1}
    )
    assert spec.sample_rate == 44_100
    assert spec.name == "12345"  # str() coercion
    assert spec.key == "7:12345"


def test_spec_from_device_info_floors_zero_channels_to_one() -> None:
    # A loopback/output device can report 0 input channels; max(1, .) keeps
    # the stream openable (mono) rather than a 0-channel error.
    spec = _spec_from_device_info(
        {"index": 0, "name": "Loopback", "defaultSampleRate": 48_000.0, "maxInputChannels": 0}
    )
    assert spec.channels == 1


# --------------------------------------------------------------------------
# _PyAudioStreamHandle: liveness + idempotent, OSError-suppressing close.
# --------------------------------------------------------------------------


class _RecordingStream:
    """Fake PortAudio stream that records call order and can fail per step."""

    def __init__(
        self, log: list[str], *, active: bool = True,
        active_error: Exception | None = None,
        stop_error: Exception | None = None, close_error: Exception | None = None,
    ) -> None:
        self._log = log
        self._active = active
        self._active_error = active_error
        self._stop_error = stop_error
        self._close_error = close_error

    def is_active(self) -> bool:
        if self._active_error is not None:
            raise self._active_error
        return self._active

    def stop_stream(self) -> None:
        self._log.append("stop")
        if self._stop_error is not None:
            raise self._stop_error

    def close(self) -> None:
        self._log.append("close")
        if self._close_error is not None:
            raise self._close_error


class _RecordingPyAudio:
    def __init__(self, log: list[str], *, terminate_error: Exception | None = None) -> None:
        self._log = log
        self._terminate_error = terminate_error

    def terminate(self) -> None:
        self._log.append("terminate")
        if self._terminate_error is not None:
            raise self._terminate_error


def test_is_alive_true_when_stream_active() -> None:
    log: list[str] = []
    handle = _PyAudioStreamHandle(
        _RecordingPyAudio(log), _RecordingStream(log, active=True), sample_rate=48_000, channels=1
    )
    assert handle.is_alive is True


def test_is_alive_false_when_stream_inactive() -> None:
    log: list[str] = []
    handle = _PyAudioStreamHandle(
        _RecordingPyAudio(log), _RecordingStream(log, active=False), sample_rate=48_000, channels=1
    )
    assert handle.is_alive is False


def test_is_alive_false_after_close_without_touching_stream() -> None:
    log: list[str] = []
    # is_active would raise if consulted; a closed handle must NOT consult it.
    handle = _PyAudioStreamHandle(
        _RecordingPyAudio(log),
        _RecordingStream(log, active_error=OSError("gone")),
        sample_rate=48_000,
        channels=1,
    )
    handle.close()
    assert handle.is_alive is False


def test_is_alive_false_when_is_active_raises_oserror() -> None:
    log: list[str] = []
    handle = _PyAudioStreamHandle(
        _RecordingPyAudio(log),
        _RecordingStream(log, active_error=OSError("torn down")),
        sample_rate=48_000,
        channels=1,
    )
    assert handle.is_alive is False  # device vanished under us -> treated dead


def test_close_releases_in_order_and_is_idempotent() -> None:
    log: list[str] = []
    handle = _PyAudioStreamHandle(
        _RecordingPyAudio(log), _RecordingStream(log), sample_rate=48_000, channels=1
    )
    handle.close()
    assert log == ["stop", "close", "terminate"]
    handle.close()  # second close is a no-op: no duplicate releases
    assert log == ["stop", "close", "terminate"]


def test_close_suppresses_oserror_on_each_step_and_still_releases_the_rest() -> None:
    log: list[str] = []
    # stop_stream raising OSError (device already gone) must NOT prevent
    # close() and terminate() from running -> no leaked PortAudio refs.
    handle = _PyAudioStreamHandle(
        _RecordingPyAudio(log),
        _RecordingStream(log, stop_error=OSError("already gone")),
        sample_rate=48_000,
        channels=1,
    )
    handle.close()  # must not raise
    assert log == ["stop", "close", "terminate"]


def test_close_suppresses_oserror_on_terminate() -> None:
    log: list[str] = []
    handle = _PyAudioStreamHandle(
        _RecordingPyAudio(log, terminate_error=OSError("pa gone")),
        _RecordingStream(log),
        sample_rate=48_000,
        channels=1,
    )
    handle.close()  # terminate OSError suppressed
    assert log == ["stop", "close", "terminate"]


# --------------------------------------------------------------------------
# probe_default_device / open_capture_stream via injected fake pyaudiowpatch.
# --------------------------------------------------------------------------


class _FakePyAudioInstance:
    """One fake PyAudio() instance. Records open() kwargs; scriptable errors."""

    def __init__(self, *, loopback: dict[str, Any] | None = None,
                 input_info: dict[str, Any] | None = None,
                 open_result: Any = None, open_error: Exception | None = None) -> None:
        self.terminated = False
        self._loopback = loopback
        self._input_info = input_info
        self._open_result = open_result
        self._open_error = open_error
        self.open_calls: list[dict[str, Any]] = []

    def get_default_wasapi_loopback(self) -> dict[str, Any]:
        assert self._loopback is not None
        return self._loopback

    def get_default_input_device_info(self) -> dict[str, Any]:
        assert self._input_info is not None
        return self._input_info

    def open(self, **kwargs: Any) -> Any:
        self.open_calls.append(kwargs)
        if self._open_error is not None:
            raise self._open_error
        return self._open_result

    def terminate(self) -> None:
        self.terminated = True


def _inject_pyaudio(monkeypatch: pytest.MonkeyPatch, instance: _FakePyAudioInstance) -> None:
    fake = SimpleNamespace(
        PyAudio=lambda: instance,
        paContinue=0,
        paInt16=8,
        paWASAPI=13,
    )
    monkeypatch.setitem(__import__("sys").modules, "pyaudiowpatch", fake)


def test_resolve_input_device_looks_up_by_portaudio_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = _FakePyAudioInstance(
        input_info={"index": 9, "name": "USB Mic", "defaultSampleRate": 48_000.0,
                    "maxInputChannels": 1},
    )
    # get_device_info_by_index is the resolve path (not default-input).
    instance.get_device_info_by_index = (  # type: ignore[attr-defined]
        lambda idx: {
            "index": idx,
            "name": "USB Mic",
            "defaultSampleRate": 48_000.0,
            "maxInputChannels": 1,
        }
    )
    _inject_pyaudio(monkeypatch, instance)
    spec = PyAudioWpatchCaptureBackend().resolve_input_device("9:USB Mic")
    assert spec == CaptureDeviceSpec("9:USB Mic", "USB Mic", 48_000, 1)
    assert instance.terminated is True


def test_resolve_input_device_fails_closed_for_non_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = _FakePyAudioInstance()
    instance.get_device_info_by_index = (  # type: ignore[attr-defined]
        lambda idx: {
            "index": idx,
            "name": "Speakers",
            "defaultSampleRate": 48_000.0,
            "maxInputChannels": 0,
        }
    )
    _inject_pyaudio(monkeypatch, instance)
    with pytest.raises(LookupError, match="not an input device"):
        PyAudioWpatchCaptureBackend().resolve_input_device("3:Speakers")


def test_probe_them_uses_loopback_and_terminates(monkeypatch: pytest.MonkeyPatch) -> None:
    instance = _FakePyAudioInstance(
        loopback={"index": 3, "name": "Speakers", "defaultSampleRate": 48_000.0,
                  "maxInputChannels": 2},
        input_info={"index": 1, "name": "Mic", "defaultSampleRate": 44_100.0,
                    "maxInputChannels": 1},
    )
    _inject_pyaudio(monkeypatch, instance)
    spec = PyAudioWpatchCaptureBackend().probe_default_device(StreamLabel.THEM)
    assert spec == CaptureDeviceSpec("3:Speakers", "Speakers", 48_000, 2)
    assert instance.terminated is True  # fresh instance always released


def test_probe_me_uses_input_device_and_terminates(monkeypatch: pytest.MonkeyPatch) -> None:
    instance = _FakePyAudioInstance(
        loopback={"index": 3, "name": "Speakers", "defaultSampleRate": 48_000.0,
                  "maxInputChannels": 2},
        input_info={"index": 1, "name": "Mic", "defaultSampleRate": 44_100.0,
                    "maxInputChannels": 1},
    )
    _inject_pyaudio(monkeypatch, instance)
    spec = PyAudioWpatchCaptureBackend().probe_default_device(StreamLabel.ME)
    assert spec == CaptureDeviceSpec("1:Mic", "Mic", 44_100, 1)
    assert instance.terminated is True


def test_open_capture_stream_builds_stream_with_exact_parameters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel_stream = object()
    instance = _FakePyAudioInstance(open_result=sentinel_stream)
    _inject_pyaudio(monkeypatch, instance)
    spec = CaptureDeviceSpec(key="7:My Mic", name="My Mic", sample_rate=48_000, channels=2)

    handle = PyAudioWpatchCaptureBackend().open_capture_stream(spec, lambda data, t: None)

    assert isinstance(handle, _PyAudioStreamHandle)
    (kwargs,) = instance.open_calls
    assert kwargs["format"] == 8  # paInt16
    assert kwargs["channels"] == 2
    assert kwargs["rate"] == 48_000
    assert kwargs["input"] is True
    assert kwargs["input_device_index"] == 7  # parsed from "7:My Mic"
    # 48000 * 0.02 = 960 frames, above the 128 floor.
    assert kwargs["frames_per_buffer"] == 960
    assert instance.terminated is False  # success: instance is retained, not torn down


@pytest.mark.parametrize(
    ("sample_rate", "expected_frames"),
    [
        (6_350, 128),  # int(127.0)=127 -> clamped up to the 128 floor
        (6_400, 128),  # int(128.0)=128 -> exactly at the floor
        (6_450, 129),  # int(129.0)=129 -> above the floor, used as-is
        (48_000, 960),
    ],
)
def test_open_capture_stream_frames_per_buffer_floor_boundary(
    monkeypatch: pytest.MonkeyPatch, sample_rate: int, expected_frames: int
) -> None:
    instance = _FakePyAudioInstance(open_result=object())
    _inject_pyaudio(monkeypatch, instance)
    spec = CaptureDeviceSpec(key="0:Dev", name="Dev", sample_rate=sample_rate, channels=1)
    PyAudioWpatchCaptureBackend().open_capture_stream(spec, lambda data, t: None)
    assert instance.open_calls[0]["frames_per_buffer"] == expected_frames


def test_open_capture_stream_device_index_parse_ignores_colons_in_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = _FakePyAudioInstance(open_result=object())
    _inject_pyaudio(monkeypatch, instance)
    # split(":", 1) keeps everything after the first colon in the name.
    spec = CaptureDeviceSpec(key="12:Weird:Name", name="Weird:Name", sample_rate=16_000, channels=1)
    PyAudioWpatchCaptureBackend().open_capture_stream(spec, lambda data, t: None)
    assert instance.open_calls[0]["input_device_index"] == 12


def test_capture_callback_forwards_chunk_with_monotonic_time_and_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(time, "monotonic", lambda: 1234.5)
    instance = _FakePyAudioInstance(open_result=object())
    _inject_pyaudio(monkeypatch, instance)
    received: list[tuple[bytes, float]] = []
    spec = CaptureDeviceSpec(key="0:Dev", name="Dev", sample_rate=16_000, channels=1)
    PyAudioWpatchCaptureBackend().open_capture_stream(
        spec, lambda data, t: received.append((data, t))
    )
    callback = instance.open_calls[0]["stream_callback"]

    result = callback(b"\x01\x02", 1, None, None)
    assert received == [(b"\x01\x02", 1234.5)]  # exact monotonic stamp forwarded
    assert result == (None, 0)  # (no output, paContinue)


@pytest.mark.parametrize("empty_in", [None, b""])
def test_capture_callback_ignores_empty_input_but_still_continues(
    monkeypatch: pytest.MonkeyPatch, empty_in: bytes | None
) -> None:
    instance = _FakePyAudioInstance(open_result=object())
    _inject_pyaudio(monkeypatch, instance)
    received: list[tuple[bytes, float]] = []
    spec = CaptureDeviceSpec(key="0:Dev", name="Dev", sample_rate=16_000, channels=1)
    PyAudioWpatchCaptureBackend().open_capture_stream(
        spec, lambda data, t: received.append((data, t))
    )
    callback = instance.open_calls[0]["stream_callback"]

    result = callback(empty_in, 0, None, None)
    assert received == []  # falsy input -> on_chunk NOT invoked
    assert result == (None, 0)  # must still tell PortAudio to keep going


def test_open_capture_stream_oserror_terminates_instance_and_reraises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = _FakePyAudioInstance(open_error=OSError("no such device"))
    _inject_pyaudio(monkeypatch, instance)
    spec = CaptureDeviceSpec(key="9:Dead", name="Dead", sample_rate=48_000, channels=2)
    with pytest.raises(OSError, match="no such device"):
        PyAudioWpatchCaptureBackend().open_capture_stream(spec, lambda data, t: None)
    assert instance.terminated is True  # fail closed: no orphaned PortAudio ref
    # Retries across rates × channels × attempts before giving up.
    assert len(instance.open_calls) >= 4


def test_open_capture_stream_retries_alternate_channel_after_oserror(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stereo open -9999 then mono success — common Zoom/Teams mix mismatch."""
    calls: list[int] = []

    class _FlakyInstance(_FakePyAudioInstance):
        def open(self, **kwargs: Any) -> Any:
            self.open_calls.append(kwargs)
            calls.append(int(kwargs["channels"]))
            if kwargs["channels"] != 1:
                raise OSError("[Errno -9999] Unanticipated host error")
            return object()

    instance = _FlakyInstance()
    _inject_pyaudio(monkeypatch, instance)
    spec = CaptureDeviceSpec(key="3:Speakers", name="Speakers", sample_rate=48_000, channels=2)
    handle = PyAudioWpatchCaptureBackend().open_capture_stream(spec, lambda data, t: None)
    assert handle.channels == 1
    assert handle.sample_rate == 48_000
    assert 2 in calls and 1 in calls



# --------------------------------------------------------------------------
# list_audio_devices via injected fake enumeration.
# --------------------------------------------------------------------------


class _FakeListingInstance:
    def __init__(self, *, devices: list[dict[str, Any]], wasapi_index: int,
                 default_input: dict[str, Any] | None,
                 default_loopback: dict[str, Any] | None,
                 default_input_error: Exception | None = None,
                 default_loopback_error: Exception | None = None,
                 host_api_error: Exception | None = None) -> None:
        self._devices = devices
        self._wasapi_index = wasapi_index
        self._default_input = default_input
        self._default_loopback = default_loopback
        self._default_input_error = default_input_error
        self._default_loopback_error = default_loopback_error
        self._host_api_error = host_api_error
        self.terminated = False

    def get_host_api_info_by_type(self, api_type: int) -> dict[str, Any]:
        if self._host_api_error is not None:
            raise self._host_api_error
        return {"index": self._wasapi_index}

    def get_default_input_device_info(self) -> dict[str, Any]:
        if self._default_input_error is not None:
            raise self._default_input_error
        assert self._default_input is not None
        return self._default_input

    def get_default_wasapi_loopback(self) -> dict[str, Any]:
        if self._default_loopback_error is not None:
            raise self._default_loopback_error
        assert self._default_loopback is not None
        return self._default_loopback

    def get_device_count(self) -> int:
        return len(self._devices)

    def get_device_info_by_index(self, index: int) -> dict[str, Any]:
        return self._devices[index]

    def terminate(self) -> None:
        self.terminated = True


_DEVICES = [
    {"index": 0, "name": "MME Mic", "hostApi": 0, "maxInputChannels": 2,
     "isLoopbackDevice": False},  # wrong host API -> excluded
    {"index": 1, "name": "Mic A", "hostApi": 2, "maxInputChannels": 1,
     "isLoopbackDevice": False},  # WASAPI capture, is the default input
    {"index": 2, "name": "Speakers", "hostApi": 2, "maxInputChannels": 0,
     "isLoopbackDevice": False},  # output-only half -> excluded
    {"index": 3, "name": "Speakers [Loopback]", "hostApi": 2, "maxInputChannels": 2,
     "isLoopbackDevice": True},  # render endpoint via loopback, the default render
    {"index": 4, "name": "Mic B", "hostApi": 2, "maxInputChannels": 1,
     "isLoopbackDevice": False},  # WASAPI capture, NOT default
]


def _inject_listing(monkeypatch: pytest.MonkeyPatch, instance: _FakeListingInstance) -> None:
    fake = SimpleNamespace(PyAudio=lambda: instance, paWASAPI=13)
    monkeypatch.setitem(__import__("sys").modules, "pyaudiowpatch", fake)


def test_list_audio_devices_maps_kinds_defaults_and_excludes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = _FakeListingInstance(
        devices=_DEVICES,
        wasapi_index=2,
        default_input={"index": 1, "name": "Mic A"},
        default_loopback={"index": 3, "name": "Speakers [Loopback]"},
    )
    _inject_listing(monkeypatch, instance)

    result = audio_device_listing.list_audio_devices()

    assert result == [
        AudioDeviceDescription(id="1:Mic A", name="Mic A", kind=DEVICE_KIND_CAPTURE,
                               is_default=True),
        AudioDeviceDescription(id="3:Speakers [Loopback]", name="Speakers [Loopback]",
                               kind=DEVICE_KIND_RENDER, is_default=True),
        AudioDeviceDescription(id="4:Mic B", name="Mic B", kind=DEVICE_KIND_CAPTURE,
                               is_default=False),
    ]
    assert instance.terminated is True


def test_list_audio_devices_degrades_when_defaults_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # No default mic (OSError) and no default render (LookupError): every
    # endpoint must still list, just with is_default=False everywhere.
    instance = _FakeListingInstance(
        devices=_DEVICES,
        wasapi_index=2,
        default_input=None,
        default_loopback=None,
        default_input_error=OSError("no default input"),
        default_loopback_error=LookupError("no loopback"),
    )
    _inject_listing(monkeypatch, instance)

    result = audio_device_listing.list_audio_devices()

    assert [d.id for d in result] == ["1:Mic A", "3:Speakers [Loopback]", "4:Mic B"]
    assert all(d.is_default is False for d in result)  # degraded, never fabricated
    assert instance.terminated is True


def test_list_audio_devices_terminates_even_when_host_api_lookup_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = _FakeListingInstance(
        devices=_DEVICES,
        wasapi_index=2,
        default_input={"index": 1, "name": "Mic A"},
        default_loopback={"index": 3, "name": "Speakers [Loopback]"},
        host_api_error=OSError("audio subsystem down"),
    )
    _inject_listing(monkeypatch, instance)
    with pytest.raises(OSError, match="audio subsystem down"):
        audio_device_listing.list_audio_devices()
    assert instance.terminated is True  # finally releases the instance


# --------------------------------------------------------------------------
# Small deterministic edges the controller/resampler suites don't reach.
# --------------------------------------------------------------------------


def test_resampler_flush_passthrough_returns_empty_float32() -> None:
    # At 16 kHz the resampler is a pass-through (no soxr stream), so flush
    # must return an empty float32 tail, never touch a None stream.
    resampler = StreamingResamplerTo16kMono(PIPELINE_SAMPLE_RATE, 1)
    tail = resampler.flush()
    assert tail.dtype == np.float32
    assert tail.size == 0


class _CapturingBackend:
    """Backend whose open_capture_stream just records the on_chunk callback."""

    def __init__(self, spec: CaptureDeviceSpec) -> None:
        self._spec = spec
        self.on_chunk: Any = None

    def probe_default_device(self, stream: StreamLabel) -> CaptureDeviceSpec:
        return self._spec

    def resolve_input_device(self, key: str) -> CaptureDeviceSpec:
        return CaptureDeviceSpec(
            key, key.split(":", 1)[-1], self._spec.sample_rate, self._spec.channels
        )

    def open_capture_stream(self, spec: CaptureDeviceSpec, on_chunk: Any) -> Any:
        self.on_chunk = on_chunk
        return SimpleNamespace(close=lambda: None, is_alive=True)


def test_on_chunk_drops_malformed_chunk_without_buffering() -> None:
    # A torn chunk (1 int16 sample on a 2-channel stream) makes the real
    # resampler raise ValueError; on_chunk must swallow it (raising inside a
    # driver callback would kill the stream) and append NOTHING.
    ring = TimestampedAudioRingBuffer()
    spec = CaptureDeviceSpec(key="3:Speakers", name="Speakers", sample_rate=48_000, channels=2)
    backend = _CapturingBackend(spec)
    controller = DualStreamCaptureController(backend, ring)
    controller._open_stream(StreamLabel.THEM)

    backend.on_chunk(b"\x01\x02", 100.0)  # 1 sample, not divisible by 2 channels
    assert ring.drain() == []  # malformed audio never reaches the buffer


def test_on_chunk_ignores_empty_resampled_output() -> None:
    # Empty raw bytes -> resampler returns 0 samples -> the size==0 guard
    # returns before any AudioFrame is appended.
    ring = TimestampedAudioRingBuffer()
    spec = CaptureDeviceSpec(key="1:Mic", name="Mic", sample_rate=16_000, channels=1)
    backend = _CapturingBackend(spec)
    controller = DualStreamCaptureController(backend, ring)
    controller._open_stream(StreamLabel.ME)

    backend.on_chunk(b"", 50.0)
    assert ring.drain() == []
