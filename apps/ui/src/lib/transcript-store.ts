/**
 * Zustand store for the live-meeting capture session: finalised transcript
 * segments, in-flight partials, capture lifecycle, and latency instrumentation.
 *
 * Written only by the engine event dispatcher (live-engine-socket.ts) and the
 * capture command layer (capture-commands.ts); read by the live meeting screen.
 * Factory-based so tests create isolated stores.
 *
 * Ordering contract: display order is (t_start, then seq, then stream) so
 * out-of-order WS delivery still renders in spoken order. Stale partials
 * (seq already finalised for that stream) are dropped, and duplicate
 * segment_ids are ignored — replayed frames must never duplicate rows.
 */
import { createStore, useStore, type StoreApi } from "zustand";
import type {
  CaptureDeviceChangedPayload,
  StreamLabel,
  TranscriptFinalPayload,
  TranscriptPartialPayload,
} from "./capture-protocol";

export type CaptureStatus = "idle" | "starting" | "live" | "stopping" | "stopped" | "error";

export interface TranscriptSegment {
  readonly stream: StreamLabel;
  readonly speakerLabel: string;
  readonly text: string;
  readonly tStart: number;
  readonly tEnd: number;
  readonly seq: number;
  readonly segmentId: string;
  readonly lagMs: number;
}

export interface TranscriptPartial {
  readonly stream: StreamLabel;
  readonly speakerLabel: string;
  readonly text: string;
  readonly tStart: number;
  readonly tEnd: number;
  readonly seq: number;
}

export interface DeviceChangeNotice {
  readonly deviceName: string;
  readonly recoveredMs: number;
}

export interface TranscriptState {
  readonly captureStatus: CaptureStatus;
  readonly meetingId: string | null;
  /** Wall-clock ms when capture.started arrived; anchors bubble timestamps + timer. */
  readonly captureStartedAtMs: number | null;
  readonly segments: readonly TranscriptSegment[];
  readonly partials: Readonly<Record<StreamLabel, TranscriptPartial | null>>;
  /** Per-stream high-water mark of finalised seq — used to drop stale partials. */
  readonly lastFinalSeq: Readonly<Record<StreamLabel, number>>;
  /** Latest audio-end -> emit latency from the engine (speed is a showcase). */
  readonly lastLagMs: number | null;
  readonly deviceNotice: DeviceChangeNotice | null;
  /** Honest failure copy when capture could not start or stopped on error. */
  readonly errorMessage: string | null;
}

export const INITIAL_TRANSCRIPT_STATE: TranscriptState = {
  captureStatus: "idle",
  meetingId: null,
  captureStartedAtMs: null,
  segments: [],
  partials: { me: null, them: null },
  lastFinalSeq: { me: -1, them: -1 },
  lastLagMs: null,
  deviceNotice: null,
  errorMessage: null,
};

export type TranscriptStore = StoreApi<TranscriptState>;

export function createTranscriptStore(): TranscriptStore {
  return createStore<TranscriptState>(() => INITIAL_TRANSCRIPT_STATE);
}

/** The one store the running app uses. Tests create their own via the factory. */
export const transcriptStore: TranscriptStore = createTranscriptStore();

export function useTranscript<T>(selector: (state: TranscriptState) => T): T {
  return useStore(transcriptStore, selector);
}

/** Spoken order: t_start first, seq breaks exact ties, stream is a stable last resort. */
function displayOrder(a: TranscriptSegment, b: TranscriptSegment): number {
  if (a.tStart !== b.tStart) return a.tStart - b.tStart;
  if (a.seq !== b.seq) return a.seq - b.seq;
  return a.stream < b.stream ? -1 : a.stream > b.stream ? 1 : 0;
}

function defaultSpeakerLabel(stream: StreamLabel, payload: TranscriptPartialPayload): string {
  if (payload.speaker_label !== undefined && payload.speaker_label.length > 0) {
    return payload.speaker_label;
  }
  return stream === "me" ? "Me" : "Them";
}

export function applyTranscriptFinal(store: TranscriptStore, payload: TranscriptFinalPayload): void {
  store.setState((state) => {
    if (state.segments.some((s) => s.segmentId === payload.segment_id)) return state;
    const segment: TranscriptSegment = {
      stream: payload.stream,
      speakerLabel: defaultSpeakerLabel(payload.stream, payload),
      text: payload.text,
      tStart: payload.t_start,
      tEnd: payload.t_end,
      seq: payload.seq,
      segmentId: payload.segment_id,
      lagMs: payload.lag_ms,
    };
    const segments = [...state.segments, segment].sort(displayOrder);
    const lastFinalSeq = {
      ...state.lastFinalSeq,
      [payload.stream]: Math.max(state.lastFinalSeq[payload.stream], payload.seq),
    };
    // A partial the final has caught up with is now stale — clear it.
    const openPartial = state.partials[payload.stream];
    const partials =
      openPartial !== null && openPartial.seq <= payload.seq
        ? { ...state.partials, [payload.stream]: null }
        : state.partials;
    return { ...state, segments, lastFinalSeq, partials, lastLagMs: payload.lag_ms };
  });
}

export function applyTranscriptPartial(
  store: TranscriptStore,
  payload: TranscriptPartialPayload,
): void {
  store.setState((state) => {
    // Stale partial: its segment was already finalised — drop, never regress.
    if (payload.seq <= state.lastFinalSeq[payload.stream]) return state;
    const existing = state.partials[payload.stream];
    // Out-of-order older partial must not overwrite a newer one.
    if (existing !== null && existing.seq > payload.seq) return state;
    const partial: TranscriptPartial = {
      stream: payload.stream,
      speakerLabel: defaultSpeakerLabel(payload.stream, payload),
      text: payload.text,
      tStart: payload.t_start,
      tEnd: payload.t_end,
      seq: payload.seq,
    };
    return { ...state, partials: { ...state.partials, [payload.stream]: partial } };
  });
}

export function applyCaptureStarted(store: TranscriptStore, meetingId: string, nowMs: number): void {
  // Fresh meeting: previous session's transcript is cleared, error state resolved.
  store.setState({
    ...INITIAL_TRANSCRIPT_STATE,
    captureStatus: "live",
    meetingId,
    captureStartedAtMs: nowMs,
  });
}

export function applyCaptureStopped(store: TranscriptStore, meetingId: string, reason: string): void {
  store.setState((state) => {
    // A stop for some other (stale) meeting must not kill the live one.
    if (state.meetingId !== null && state.meetingId !== meetingId) return state;
    let errorMessage: string | null = null;
    if (reason === "error") {
      errorMessage = "Capture stopped because of an engine error.";
    } else if (reason === "silence") {
      errorMessage =
        "Stopped after no speech was transcribed — often a muted mic, headphones (no speaker loopback), or a quiet room. Set Silence auto-stop to Off in Settings → Automation if that was too aggressive.";
    }
    return {
      ...state,
      captureStatus: reason === "error" ? "error" : "stopped",
      partials: { me: null, them: null }, // nothing is in flight once stopped
      errorMessage,
    };
  });
}

export function applyCaptureDeviceChanged(
  store: TranscriptStore,
  payload: CaptureDeviceChangedPayload,
): void {
  store.setState({
    deviceNotice: { deviceName: payload.device_name, recoveredMs: payload.recovered_ms },
  });
}

/** Seconds-from-start -> "hh:mm:ss" bubble/timer clock. Floors, never rounds up. */
export function formatMeetingClock(tSeconds: number): string {
  const total = Math.max(0, Math.floor(tSeconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(h)}:${pad(m)}:${pad(s)}`;
}
