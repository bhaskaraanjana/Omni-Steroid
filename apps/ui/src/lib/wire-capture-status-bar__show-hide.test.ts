/**
 * Capture status bar wiring: show while starting/live/stopping, hide otherwise;
 * Stop event requests capture stop.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  createTranscriptStore,
  INITIAL_TRANSCRIPT_STATE,
  transcriptStore,
} from "./transcript-store";
import {
  CAPTURE_STATUS_BAR_STOP_EVENT,
  wireCaptureStatusBar,
} from "./wire-capture-status-bar";

const invoke = vi.fn(async (..._args: unknown[]) => undefined);
vi.mock("@tauri-apps/api/core", () => ({
  invoke: (...args: unknown[]) => invoke(...args),
}));

const send = vi.fn(() => true);
vi.mock("./capture-commands", async () => {
  const actual = await vi.importActual<typeof import("./capture-commands")>("./capture-commands");
  return {
    ...actual,
    requestCaptureStop: vi.fn((store?: unknown) => {
      const target = (store as { setState?: (s: object) => void }) ?? null;
      if (target && typeof target.setState === "function") {
        target.setState({ captureStatus: "stopping", errorMessage: null });
      }
      return true;
    }),
  };
});

beforeEach(() => {
  invoke.mockClear();
  send.mockClear();
  transcriptStore.setState(INITIAL_TRANSCRIPT_STATE, true);
});

afterEach(() => {
  vi.useRealTimers();
});

describe("wireCaptureStatusBar", () => {
  it("shows on starting/live and hides on idle", () => {
    const store = createTranscriptStore();
    const unwire = wireCaptureStatusBar(store);
    store.setState({ captureStatus: "starting" });
    expect(invoke).toHaveBeenCalledWith(
      "set_capture_status_bar_visible",
      expect.objectContaining({
        visible: true,
        content: expect.objectContaining({ status: "starting" }),
      }),
    );
    store.setState({
      captureStatus: "live",
      captureStartedAtMs: 1_000_000,
    });
    expect(invoke).toHaveBeenCalledWith(
      "set_capture_status_bar_visible",
      expect.objectContaining({
        visible: true,
        content: expect.objectContaining({ status: "live" }),
      }),
    );
    store.setState({ captureStatus: "idle", captureStartedAtMs: null });
    expect(invoke).toHaveBeenLastCalledWith("set_capture_status_bar_visible", {
      visible: false,
      content: null,
    });
    unwire();
  });

  it("Stop event requests capture stop", async () => {
    const { requestCaptureStop } = await import("./capture-commands");
    const handlers = new Map<string, (event: { payload: unknown }) => void>();
    const listen = vi.fn(async (event: string, handler: (e: { payload: unknown }) => void) => {
      handlers.set(event, handler);
      return () => {
        handlers.delete(event);
      };
    });
    const store = createTranscriptStore();
    store.setState({ captureStatus: "live", captureStartedAtMs: Date.now() });
    const unwire = wireCaptureStatusBar(store, listen);
    await vi.waitFor(() => expect(handlers.has(CAPTURE_STATUS_BAR_STOP_EVENT)).toBe(true));
    handlers.get(CAPTURE_STATUS_BAR_STOP_EVENT)!({ payload: null });
    expect(requestCaptureStop).toHaveBeenCalled();
    unwire();
  });
});
