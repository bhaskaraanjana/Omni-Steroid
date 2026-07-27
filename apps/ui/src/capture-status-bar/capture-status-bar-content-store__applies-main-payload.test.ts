/**
 * Overlay content store: main-window payloads are the single source of truth.
 */
import { describe, expect, it } from "vitest";
import {
  applyCaptureStatusBarContent,
  captureStatusBarContentStore,
  INITIAL_CAPTURE_STATUS_BAR_CONTENT,
} from "./capture-status-bar-content-store";
import { createStore } from "zustand";

describe("applyCaptureStatusBarContent", () => {
  it("applies a live payload with elapsed seconds and title", () => {
    const store = createStore(() => ({ ...INITIAL_CAPTURE_STATUS_BAR_CONTENT }));
    applyCaptureStatusBarContent(store, {
      status: "live",
      elapsedSeconds: 42,
      title: "Standup",
    });
    expect(store.getState()).toEqual({
      status: "live",
      elapsedSeconds: 42,
      title: "Standup",
    });
  });

  it("applies starting / stopping without requiring elapsed", () => {
    const store = createStore(() => ({ ...INITIAL_CAPTURE_STATUS_BAR_CONTENT }));
    applyCaptureStatusBarContent(store, { status: "starting" });
    expect(store.getState().status).toBe("starting");
    expect(store.getState().elapsedSeconds).toBeNull();

    applyCaptureStatusBarContent(store, { status: "stopping", elapsedSeconds: 10 });
    expect(store.getState().status).toBe("stopping");
    expect(store.getState().elapsedSeconds).toBe(10);
  });

  it("clears on null / malformed content (fail-closed)", () => {
    captureStatusBarContentStore.setState({
      status: "live",
      elapsedSeconds: 99,
      title: "Old",
    });
    applyCaptureStatusBarContent(captureStatusBarContentStore, null);
    expect(captureStatusBarContentStore.getState()).toEqual(INITIAL_CAPTURE_STATUS_BAR_CONTENT);

    captureStatusBarContentStore.setState({
      status: "live",
      elapsedSeconds: 1,
      title: null,
    });
    applyCaptureStatusBarContent(captureStatusBarContentStore, { status: 123 });
    expect(captureStatusBarContentStore.getState()).toEqual(INITIAL_CAPTURE_STATUS_BAR_CONTENT);
  });
});
