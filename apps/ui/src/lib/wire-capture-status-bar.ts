/**
 * Desktop capture status bar bridge (main window): show/hide the always-on-top
 * overlay from transcript capture lifecycle, push elapsed ticks while live,
 * and handle Stop events emitted by the overlay shell command.
 */
import { invoke } from "@tauri-apps/api/core";
import { requestCaptureStop } from "./capture-commands";
import {
  transcriptStore,
  type CaptureStatus,
  type TranscriptStore,
} from "./transcript-store";

/** Event the shell emits to the overlay with the payload to render. */
export const CAPTURE_STATUS_BAR_CONTENT_EVENT = "capture-status-bar-content";
/** Event the overlay Stop command emits on the main window. */
export const CAPTURE_STATUS_BAR_STOP_EVENT = "capture-status-bar-stop-capture";

export interface CaptureStatusBarContent {
  readonly status: string;
  readonly elapsedSeconds?: number;
  readonly title?: string;
}

const ACTIVE_STATUSES: ReadonlySet<CaptureStatus> = new Set([
  "starting",
  "live",
  "stopping",
]);

function shouldShowBar(status: CaptureStatus): boolean {
  return ACTIVE_STATUSES.has(status);
}

function buildContent(
  transcript: TranscriptStore,
  nowMs: number,
): CaptureStatusBarContent {
  const { captureStatus, captureStartedAtMs } = transcript.getState();
  const content: CaptureStatusBarContent = { status: captureStatus };
  if (captureStatus === "live" && captureStartedAtMs !== null) {
    return {
      ...content,
      elapsedSeconds: Math.max(0, Math.floor((nowMs - captureStartedAtMs) / 1000)),
    };
  }
  return content;
}

async function applyVisibility(
  visible: boolean,
  content: CaptureStatusBarContent | null,
): Promise<void> {
  try {
    await invoke("set_capture_status_bar_visible", { visible, content });
  } catch {
    // Web build / tests: no Tauri shell — desktop bar unavailable.
  }
}

/**
 * Subscribe capture status to the desktop status bar window.
 * Returns an unsubscribe that also hides the overlay and clears the timer.
 */
export function wireCaptureStatusBar(
  transcript: TranscriptStore = transcriptStore,
  listen: (
    event: string,
    handler: (event: { payload: unknown }) => void,
  ) => Promise<() => void> = async () => () => {},
  now: () => number = () => Date.now(),
): () => void {
  const store = transcript;
  let elapsedTimer: ReturnType<typeof setInterval> | null = null;

  const clearElapsedTimer = (): void => {
    if (elapsedTimer !== null) {
      clearInterval(elapsedTimer);
      elapsedTimer = null;
    }
  };

  const sync = (): void => {
    const { captureStatus } = transcript.getState();
    const visible = shouldShowBar(captureStatus);
    if (!visible) {
      clearElapsedTimer();
      void applyVisibility(false, null);
      return;
    }
    const content = buildContent(transcript, now());
    void applyVisibility(true, content);

    if (captureStatus === "live") {
      if (elapsedTimer === null) {
        elapsedTimer = setInterval(() => {
          if (transcript.getState().captureStatus !== "live") {
            clearElapsedTimer();
            return;
          }
          void applyVisibility(true, buildContent(transcript, now()));
        }, 1000);
      }
    } else {
      clearElapsedTimer();
    }
  };

  const unsubTranscript = transcript.subscribe(sync);
  sync();

  const unlisteners: Array<() => void> = [];
  void (async () => {
    try {
      unlisteners.push(
        await listen(CAPTURE_STATUS_BAR_STOP_EVENT, () => {
          requestCaptureStop(transcript);
        }),
      );
    } catch {
      // Non-Tauri environments: event listen unavailable.
    }
  })();

  return () => {
    unsubTranscript();
    clearElapsedTimer();
    for (const unlisten of unlisteners) unlisten();
    void applyVisibility(false, null);
  };
}
