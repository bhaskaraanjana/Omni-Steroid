/**
 * Tests for the capture command layer: correct wire commands when the socket
 * is up, and FAIL-CLOSED honesty when it is not — no engine, no capture, and
 * the UI is told the truth. Error replies must unwedge "starting".
 */
import { describe, expect, it, vi } from "vitest";
import {
  cancelCaptureStart,
  ENGINE_OFFLINE_MESSAGE,
  requestCaptureStart,
  requestCaptureStop,
  type CaptureCommandTransport,
} from "./capture-commands";
import { PROTOCOL_VERSION, type Envelope } from "./protocol";
import { createTranscriptStore } from "./transcript-store";

describe("requestCaptureStart", () => {
  it("sends capture.start with a trimmed title and marks starting", () => {
    const store = createTranscriptStore();
    const send = vi.fn().mockReturnValue(true);
    expect(requestCaptureStart("  Vendor call  ", undefined, store, send)).toBe(true);
    expect(send).toHaveBeenCalledExactlyOnceWith("capture.start", { title: "Vendor call" });
    expect(store.getState().captureStatus).toBe("starting");
    expect(store.getState().errorMessage).toBeNull();
  });

  it("includes mic_device_id when options.micDeviceId is set", () => {
    const store = createTranscriptStore();
    const send = vi.fn().mockReturnValue(true);
    expect(
      requestCaptureStart("Standup", { micDeviceId: "9:USB Mic" }, store, send),
    ).toBe(true);
    expect(send).toHaveBeenCalledExactlyOnceWith("capture.start", {
      title: "Standup",
      mic_device_id: "9:USB Mic",
    });
  });

  it("omits the title field entirely when blank (engine forbids extras/nulls)", () => {
    const store = createTranscriptStore();
    const send = vi.fn().mockReturnValue(true);
    requestCaptureStart("   ", undefined, store, send);
    expect(send).toHaveBeenCalledExactlyOnceWith("capture.start", {});
  });

  it("FAIL CLOSED: refused send -> idle + honest offline message, never 'starting'", () => {
    const store = createTranscriptStore();
    const send = vi.fn().mockReturnValue(false);
    expect(requestCaptureStart(undefined, undefined, store, send)).toBe(false);
    expect(store.getState().captureStatus).toBe("idle");
    expect(store.getState().errorMessage).toBe(ENGINE_OFFLINE_MESSAGE);
  });

  it("FAIL CLOSED: engine error reply unwedes starting with the engine message", () => {
    const store = createTranscriptStore();
    let listener: ((data: unknown) => void) | null = null;
    let sent: Envelope | null = null;
    const transport: CaptureCommandTransport = {
      sendEnvelope: (envelope) => {
        sent = envelope;
        return true;
      },
      subscribeFrames: (fn) => {
        listener = fn;
        return () => {
          listener = null;
        };
      },
    };
    // Emitting through a function boundary keeps `listener` at its declared union
    // type; called inline it narrows to the `null` it was initialised with.
    const emit = (frame: unknown): void => listener?.(frame);
    expect(requestCaptureStart(undefined, undefined, store, transport)).toBe(true);
    expect(store.getState().captureStatus).toBe("starting");
    expect(sent).not.toBeNull();
    emit(
      JSON.stringify({
        v: PROTOCOL_VERSION,
        kind: "reply",
        name: "error",
        id: sent!.id,
        payload: { code: "capture_error", message: "could not start capture: no mic" },
      }),
    );
    expect(store.getState().captureStatus).toBe("idle");
    expect(store.getState().errorMessage).toBe("could not start capture: no mic");
  });
});

describe("cancelCaptureStart", () => {
  it("clears a wedged starting status so the user can retry", () => {
    const store = createTranscriptStore();
    store.setState({ captureStatus: "starting", errorMessage: null });
    cancelCaptureStart(store);
    expect(store.getState().captureStatus).toBe("idle");
  });
});

describe("requestCaptureStop", () => {
  it("sends capture.stop and marks stopping while awaiting the engine event", () => {
    const store = createTranscriptStore();
    store.setState({ captureStatus: "live" });
    const send = vi.fn().mockReturnValue(true);
    expect(requestCaptureStop(store, send)).toBe(true);
    expect(send).toHaveBeenCalledExactlyOnceWith("capture.stop", {});
    expect(store.getState().captureStatus).toBe("stopping");
  });

  it("FAIL CLOSED: refused send keeps the live status but surfaces the truth", () => {
    const store = createTranscriptStore();
    store.setState({ captureStatus: "live" });
    const send = vi.fn().mockReturnValue(false);
    expect(requestCaptureStop(store, send)).toBe(false);
    expect(store.getState().captureStatus).toBe("live"); // no phantom stop
    expect(store.getState().errorMessage).toBe(ENGINE_OFFLINE_MESSAGE);
  });
});
