/**
 * Overlay-local content for the capture status bar. Main window pushes
 * payloads via a Tauri event — this store never opens an engine socket.
 */
import { createStore, type StoreApi } from "zustand";

export interface CaptureStatusBarContent {
  readonly status: string;
  readonly elapsedSeconds: number | null;
  readonly title: string | null;
}

export const INITIAL_CAPTURE_STATUS_BAR_CONTENT: CaptureStatusBarContent = {
  status: "idle",
  elapsedSeconds: null,
  title: null,
};

export type CaptureStatusBarContentStore = StoreApi<CaptureStatusBarContent>;

/** Overlay-local store (not shared with the main window JS heap). */
export const captureStatusBarContentStore: CaptureStatusBarContentStore = createStore(
  () => ({ ...INITIAL_CAPTURE_STATUS_BAR_CONTENT }),
);

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Apply a content payload from the main window. Fail-closed: malformed
 * frames clear to idle so we never render a stale Recording state.
 */
export function applyCaptureStatusBarContent(
  store: CaptureStatusBarContentStore,
  payload: unknown,
): void {
  if (payload === null || payload === undefined || !isPlainObject(payload)) {
    store.setState({ ...INITIAL_CAPTURE_STATUS_BAR_CONTENT }, true);
    return;
  }
  const status = payload["status"];
  if (typeof status !== "string" || status.length === 0) {
    store.setState({ ...INITIAL_CAPTURE_STATUS_BAR_CONTENT }, true);
    return;
  }
  const elapsedRaw = payload["elapsedSeconds"];
  const elapsedSeconds =
    elapsedRaw === null || elapsedRaw === undefined
      ? null
      : typeof elapsedRaw === "number" && Number.isFinite(elapsedRaw) && elapsedRaw >= 0
        ? Math.floor(elapsedRaw)
        : null;
  const titleRaw = payload["title"];
  const title =
    titleRaw === null || titleRaw === undefined
      ? null
      : typeof titleRaw === "string" && titleRaw.length > 0
        ? titleRaw
        : null;
  store.setState({ status, elapsedSeconds, title });
}
