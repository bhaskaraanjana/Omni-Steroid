/**
 * User-initiated capture lifecycle: start / stop commands plus the optimistic
 * store transitions around them.
 *
 * Sits between the live meeting screen (caller) and live-engine-socket.ts
 * (wire). The engine's capture.started / capture.stopped events are the source
 * of truth for live/stopped; this layer marks "starting"/"stopping" and
 * fail-closes to idle/error when the engine refuses the command, times out,
 * or is unreachable — never leave the UI wedged on "starting" with a disabled
 * button (deny by default, honest failure).
 */
import {
  CAPTURE_START_COMMAND_NAME,
  CAPTURE_STOP_COMMAND_NAME,
} from "./capture-protocol";
import { sendEngineEnvelope, subscribeToEngineFrames } from "./live-engine-socket";
import { makeCommand, parseInboundMessage, type Envelope } from "./protocol";
import { appSettingsStore } from "./settings-store";
import { transcriptStore, type TranscriptStore } from "./transcript-store";

export type CommandSender = (name: string, payload?: Record<string, unknown>) => boolean;

/** Injectable seam: production uses the live socket; tests pass fakes. */
export interface CaptureCommandTransport {
  readonly sendEnvelope: (envelope: Envelope) => boolean;
  readonly subscribeFrames: (listener: (data: unknown) => void) => () => void;
}

const liveTransport: CaptureCommandTransport = {
  sendEnvelope: sendEngineEnvelope,
  subscribeFrames: subscribeToEngineFrames,
};

export const ENGINE_OFFLINE_MESSAGE =
  "The engine is offline. Capture needs the engine running on this device.";

/** Model load + device open can take a while after cold start; then fail closed. */
export const CAPTURE_START_REPLY_TIMEOUT_MS = 90_000;

export interface CaptureStartOptions {
  readonly micDeviceId?: string;
}

/** Active start-reply watchers so a Cancel can drop a wedged "starting" UI. */
let startWatchCleanup: (() => void) | null = null;

function clearStartWatch(): void {
  if (startWatchCleanup !== null) {
    startWatchCleanup();
    startWatchCleanup = null;
  }
}

/**
 * Abort a wedged "starting"/"stopping" UI without talking to the engine.
 * Use when the user cancels, or after an ignored error left the button disabled.
 */
export function cancelCaptureStart(store: TranscriptStore = transcriptStore): void {
  clearStartWatch();
  const status = store.getState().captureStatus;
  if (status === "starting" || status === "stopping") {
    store.setState({
      captureStatus: "idle",
      errorMessage: null,
    });
  }
}

function watchCaptureReply(
  commandId: string,
  store: TranscriptStore,
  transport: CaptureCommandTransport,
  opts: {
    readonly onErrorStatus: "idle" | "error";
    readonly timeoutMs: number;
    readonly timeoutMessage: string;
  },
): void {
  clearStartWatch();
  let settled = false;
  let cleanup: (() => void) | null = null;
  const finish = (apply: () => void): void => {
    if (settled) return;
    settled = true;
    if (cleanup !== null) {
      if (startWatchCleanup === cleanup) startWatchCleanup = null;
      cleanup();
      cleanup = null;
    }
    apply();
  };
  const unsubscribe = transport.subscribeFrames((data) => {
    const parsed = parseInboundMessage(data);
    if (!parsed.ok || parsed.envelope.kind !== "reply") return;
    if (parsed.envelope.id !== commandId) return;
    if (parsed.envelope.name === "ok") {
      // Success: capture.started / capture.stopped events own the store.
      finish(() => undefined);
      return;
    }
    const message = parsed.envelope.payload["message"];
    const text =
      typeof message === "string" && message.trim().length > 0
        ? message.trim()
        : "Capture could not start.";
    finish(() =>
      store.setState({
        captureStatus: opts.onErrorStatus,
        errorMessage: text,
      }),
    );
  });
  const timer = setTimeout(() => {
    finish(() =>
      store.setState({
        captureStatus: opts.onErrorStatus,
        errorMessage: opts.timeoutMessage,
      }),
    );
  }, opts.timeoutMs);
  cleanup = (): void => {
    unsubscribe();
    clearTimeout(timer);
  };
  startWatchCleanup = cleanup;
}

export function requestCaptureStart(
  title?: string,
  options?: CaptureStartOptions,
  store: TranscriptStore = transcriptStore,
  transport: CaptureCommandTransport | CommandSender = liveTransport,
): boolean {
  const payload: Record<string, unknown> = {};
  if (title !== undefined && title.trim().length > 0) {
    payload.title = title.trim();
  }
  // Explicit option wins; otherwise the Settings mic pick (device id).
  const micDeviceId =
    options !== undefined
      ? options.micDeviceId
      : appSettingsStore.getState().microphone;
  if (typeof micDeviceId === "string" && micDeviceId.trim().length > 0) {
    payload.mic_device_id = micDeviceId.trim();
  }

  // Test seam: plain (name, payload) => boolean sender.
  if (typeof transport === "function") {
    const sent = transport(CAPTURE_START_COMMAND_NAME, payload);
    if (!sent) {
      store.setState({ captureStatus: "idle", errorMessage: ENGINE_OFFLINE_MESSAGE });
      return false;
    }
    store.setState({ captureStatus: "starting", errorMessage: null });
    return true;
  }

  const envelope = makeCommand(CAPTURE_START_COMMAND_NAME, payload);
  const sent = transport.sendEnvelope(envelope);
  if (!sent) {
    store.setState({ captureStatus: "idle", errorMessage: ENGINE_OFFLINE_MESSAGE });
    return false;
  }
  store.setState({ captureStatus: "starting", errorMessage: null });
  watchCaptureReply(envelope.id, store, transport, {
    onErrorStatus: "idle",
    timeoutMs: CAPTURE_START_REPLY_TIMEOUT_MS,
    timeoutMessage:
      "Capture did not start in time. Check that speech models finished loading, then try again.",
  });
  return true;
}

export function requestCaptureStop(
  store: TranscriptStore = transcriptStore,
  transport: CaptureCommandTransport | CommandSender = liveTransport,
): boolean {
  if (typeof transport === "function") {
    const sent = transport(CAPTURE_STOP_COMMAND_NAME, {});
    if (!sent) {
      store.setState({ errorMessage: ENGINE_OFFLINE_MESSAGE });
      return false;
    }
    store.setState({ captureStatus: "stopping", errorMessage: null });
    return true;
  }

  const envelope = makeCommand(CAPTURE_STOP_COMMAND_NAME, {});
  const sent = transport.sendEnvelope(envelope);
  if (!sent) {
    store.setState({ errorMessage: ENGINE_OFFLINE_MESSAGE });
    return false;
  }
  store.setState({ captureStatus: "stopping", errorMessage: null });
  watchCaptureReply(envelope.id, store, transport, {
    onErrorStatus: "error",
    timeoutMs: 30_000,
    timeoutMessage: "Stop did not complete. Try again, or restart the engine.",
  });
  return true;
}
