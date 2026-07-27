/**
 * Adversarial tests for the transcript store's merge/ordering contract:
 * out-of-order WS delivery, replayed frames, stale partials, cross-stream
 * interleaving, capture lifecycle resets, and exact clock formatting.
 * These would all FAIL against naive append-only rendering.
 */
import { describe, expect, it } from "vitest";
import type { TranscriptFinalPayload, TranscriptPartialPayload } from "./capture-protocol";
import {
  applyCaptureDeviceChanged,
  applyCaptureStarted,
  applyCaptureStopped,
  applyTranscriptFinal,
  applyTranscriptPartial,
  createTranscriptStore,
  formatMeetingClock,
} from "./transcript-store";
import { createCaptureEventDispatcher } from "./live-engine-socket";

function finalPayload(overrides: Partial<TranscriptFinalPayload>): TranscriptFinalPayload {
  return {
    stream: "them",
    text: "x",
    t_start: 0,
    t_end: 1,
    seq: 0,
    segment_id: `seg-${Math.random()}`,
    lag_ms: 100,
    ...overrides,
  };
}

function partialPayload(overrides: Partial<TranscriptPartialPayload>): TranscriptPartialPayload {
  return { stream: "them", text: "p", t_start: 0, t_end: 1, seq: 0, ...overrides };
}

describe("final segment ordering", () => {
  it("renders out-of-order arrivals in spoken (t_start) order", () => {
    const store = createTranscriptStore();
    applyTranscriptFinal(store, finalPayload({ segment_id: "c", t_start: 9.0, seq: 2 }));
    applyTranscriptFinal(store, finalPayload({ segment_id: "a", t_start: 1.0, seq: 0 }));
    applyTranscriptFinal(store, finalPayload({ segment_id: "b", t_start: 4.5, seq: 1 }));
    expect(store.getState().segments.map((s) => s.segmentId)).toEqual(["a", "b", "c"]);
  });

  it("breaks exact t_start ties by seq", () => {
    const store = createTranscriptStore();
    applyTranscriptFinal(store, finalPayload({ segment_id: "later", t_start: 2, seq: 5 }));
    applyTranscriptFinal(store, finalPayload({ segment_id: "earlier", t_start: 2, seq: 4 }));
    expect(store.getState().segments.map((s) => s.segmentId)).toEqual(["earlier", "later"]);
  });

  it("interleaves the two streams by time, not arrival", () => {
    const store = createTranscriptStore();
    applyTranscriptFinal(store, finalPayload({ segment_id: "them-2", stream: "them", t_start: 10, seq: 1 }));
    applyTranscriptFinal(store, finalPayload({ segment_id: "me-1", stream: "me", t_start: 5, seq: 0 }));
    applyTranscriptFinal(store, finalPayload({ segment_id: "them-1", stream: "them", t_start: 2, seq: 0 }));
    expect(store.getState().segments.map((s) => s.segmentId)).toEqual(["them-1", "me-1", "them-2"]);
  });

  it("drops a replayed segment_id — a duplicate frame must not duplicate a row", () => {
    const store = createTranscriptStore();
    applyTranscriptFinal(store, finalPayload({ segment_id: "dup", text: "first" }));
    applyTranscriptFinal(store, finalPayload({ segment_id: "dup", text: "replayed", t_start: 99 }));
    expect(store.getState().segments).toHaveLength(1);
    expect(store.getState().segments[0]?.text).toBe("first");
  });

  it("tracks lastLagMs from the newest final, exactly", () => {
    const store = createTranscriptStore();
    applyTranscriptFinal(store, finalPayload({ segment_id: "1", lag_ms: 312.4 }));
    expect(store.getState().lastLagMs).toBe(312.4);
    applyTranscriptFinal(store, finalPayload({ segment_id: "2", lag_ms: 0 }));
    expect(store.getState().lastLagMs).toBe(0);
  });
});

describe("partials: stale and out-of-order defence", () => {
  it("a final clears the partial it finalises (same seq)", () => {
    const store = createTranscriptStore();
    applyTranscriptPartial(store, partialPayload({ seq: 3, text: "typing…" }));
    applyTranscriptFinal(store, finalPayload({ seq: 3, segment_id: "s3" }));
    expect(store.getState().partials.them).toBeNull();
  });

  it("a partial older than the finalised seq is dropped (late WS delivery)", () => {
    const store = createTranscriptStore();
    applyTranscriptFinal(store, finalPayload({ seq: 5, segment_id: "s5" }));
    applyTranscriptPartial(store, partialPayload({ seq: 5, text: "stale" }));
    applyTranscriptPartial(store, partialPayload({ seq: 4, text: "staler" }));
    expect(store.getState().partials.them).toBeNull();
  });

  it("boundary: seq exactly one above the finalised high-water mark is kept", () => {
    const store = createTranscriptStore();
    applyTranscriptFinal(store, finalPayload({ seq: 5, segment_id: "s5" }));
    applyTranscriptPartial(store, partialPayload({ seq: 6, text: "fresh" }));
    expect(store.getState().partials.them?.text).toBe("fresh");
  });

  it("an older partial never overwrites a newer one for the same stream", () => {
    const store = createTranscriptStore();
    applyTranscriptPartial(store, partialPayload({ seq: 8, text: "newer" }));
    applyTranscriptPartial(store, partialPayload({ seq: 7, text: "older" }));
    expect(store.getState().partials.them?.text).toBe("newer");
  });

  it("same-seq partial updates in place (streaming growth)", () => {
    const store = createTranscriptStore();
    applyTranscriptPartial(store, partialPayload({ seq: 2, text: "hel" }));
    applyTranscriptPartial(store, partialPayload({ seq: 2, text: "hello wor" }));
    expect(store.getState().partials.them?.text).toBe("hello wor");
  });

  it("streams are independent: a me-final never clears a them-partial", () => {
    const store = createTranscriptStore();
    applyTranscriptPartial(store, partialPayload({ stream: "them", seq: 1, text: "still open" }));
    applyTranscriptFinal(store, finalPayload({ stream: "me", seq: 9, segment_id: "me9" }));
    expect(store.getState().partials.them?.text).toBe("still open");
  });
});

describe("capture lifecycle", () => {
  it("capture.started wipes the previous meeting and anchors the clock", () => {
    const store = createTranscriptStore();
    applyTranscriptFinal(store, finalPayload({ segment_id: "old" }));
    applyCaptureStarted(store, "meeting-2", 1_000_000);
    const state = store.getState();
    expect(state.segments).toHaveLength(0);
    expect(state.captureStatus).toBe("live");
    expect(state.meetingId).toBe("meeting-2");
    expect(state.captureStartedAtMs).toBe(1_000_000);
    expect(state.lastFinalSeq).toEqual({ me: -1, them: -1 });
  });

  it("capture.stopped keeps the transcript but clears in-flight partials", () => {
    const store = createTranscriptStore();
    applyCaptureStarted(store, "m1", 0);
    applyTranscriptFinal(store, finalPayload({ segment_id: "kept" }));
    applyTranscriptPartial(store, partialPayload({ seq: 9 }));
    applyCaptureStopped(store, "m1", "command");
    const state = store.getState();
    expect(state.captureStatus).toBe("stopped");
    expect(state.segments).toHaveLength(1);
    expect(state.partials).toEqual({ me: null, them: null });
    expect(state.errorMessage).toBeNull();
  });

  it("an error stop is an error state with honest copy", () => {
    const store = createTranscriptStore();
    applyCaptureStarted(store, "m1", 0);
    applyCaptureStopped(store, "m1", "error");
    expect(store.getState().captureStatus).toBe("error");
    expect(store.getState().errorMessage).not.toBeNull();
  });

  it("a silence stop explains muted mic / headphones / auto-stop", () => {
    const store = createTranscriptStore();
    applyCaptureStarted(store, "m1", 0);
    applyCaptureStopped(store, "m1", "silence");
    expect(store.getState().captureStatus).toBe("stopped");
    expect(store.getState().errorMessage ?? "").toMatch(/muted mic|headphones|Silence auto-stop/i);
  });

  it("a stop for a DIFFERENT meeting id is ignored (stale event)", () => {
    const store = createTranscriptStore();
    applyCaptureStarted(store, "m2", 0);
    applyCaptureStopped(store, "m1", "command");
    expect(store.getState().captureStatus).toBe("live");
  });

  it("device change is surfaced without touching the transcript", () => {
    const store = createTranscriptStore();
    applyTranscriptFinal(store, finalPayload({ segment_id: "s" }));
    applyCaptureDeviceChanged(store, { device_name: "Headset", recovered_ms: 84.2 });
    expect(store.getState().deviceNotice).toEqual({ deviceName: "Headset", recoveredMs: 84.2 });
    expect(store.getState().segments).toHaveLength(1);
  });
});

describe("the WS dispatcher end-to-end (raw frame -> store)", () => {
  const envelope = (name: string, payload: Record<string, unknown>) =>
    JSON.stringify({ v: 1, kind: "event", name, id: "id-1", payload });

  it("routes a valid transcript.final frame into the store", () => {
    const store = createTranscriptStore();
    const dispatch = createCaptureEventDispatcher(store, () => 42);
    dispatch(envelope("transcript.final", { ...finalPayload({ segment_id: "wire-1" }) }));
    expect(store.getState().segments[0]?.segmentId).toBe("wire-1");
  });

  it("drops malformed payloads and unknown events without mutating state", () => {
    const store = createTranscriptStore();
    const before = store.getState();
    const dispatch = createCaptureEventDispatcher(store);
    dispatch(envelope("transcript.final", { stream: "them" })); // missing fields
    dispatch(envelope("transcript.partial", { ...partialPayload({}), seq: -1 }));
    dispatch(envelope("some.unknown.event", { anything: true }));
    dispatch("not json at all");
    dispatch(JSON.stringify({ v: 2, kind: "event", name: "transcript.final", id: "x", payload: {} }));
    expect(store.getState()).toBe(before); // zustand: unchanged state is identical
  });

  it("capture.started via the wire stamps the injected clock", () => {
    const store = createTranscriptStore();
    const dispatch = createCaptureEventDispatcher(store, () => 777);
    dispatch(envelope("capture.started", { meeting_id: "m9", reason: "command" }));
    expect(store.getState().captureStartedAtMs).toBe(777);
    expect(store.getState().captureStatus).toBe("live");
  });
});

describe("formatMeetingClock is exact at boundaries", () => {
  it.each<[number, string]>([
    [0, "00:00:00"],
    [59, "00:00:59"],
    [59.999, "00:00:59"], // floors — never rounds into a fake minute
    [60, "00:01:00"],
    [3599, "00:59:59"],
    [3600, "01:00:00"],
    [3661.5, "01:01:01"],
    [-5, "00:00:00"], // clock skew clamps to zero, never renders negative
  ])("formatMeetingClock(%d) === %s", (input, expected) => {
    expect(formatMeetingClock(input)).toBe(expected);
  });
});
