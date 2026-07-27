/**
 * Desktop capture status bar UI — always-on-top overlay while capturing.
 * Content is pushed from the main window; Stop goes through a Tauri shell
 * command. Drag chrome uses data-tauri-drag-region (not the Stop button).
 */
import { invoke } from "@tauri-apps/api/core";
import { useStore } from "zustand";
import { formatMeetingClock } from "../lib/transcript-store";
import {
  captureStatusBarContentStore,
  type CaptureStatusBarContentStore,
} from "./capture-status-bar-content-store";

function statusLabel(status: string): string {
  if (status === "starting") return "Starting…";
  if (status === "stopping") return "Stopping…";
  if (status === "live") return "Recording";
  return status;
}

export function CaptureStatusBarView({
  store = captureStatusBarContentStore,
}: {
  readonly store?: CaptureStatusBarContentStore;
}) {
  const status = useStore(store, (s) => s.status);
  const elapsedSeconds = useStore(store, (s) => s.elapsedSeconds);
  const title = useStore(store, (s) => s.title);
  const isActive = status === "starting" || status === "live" || status === "stopping";
  const isLive = status === "live";

  if (!isActive) {
    return <div className="capture-status-bar-shell" aria-hidden />;
  }

  return (
    <div className="capture-status-bar-shell">
      <div
        className="capture-status-bar-card"
        role="status"
        aria-label="Capture status"
        data-tauri-drag-region
      >
        <span
          className={
            "capture-status-bar-dot" + (isLive ? " capture-status-bar-dot--live" : "")
          }
          aria-hidden
          data-tauri-drag-region
        />
        <div className="capture-status-bar-copy" data-tauri-drag-region>
          {title !== null && (
            <p className="capture-status-bar-title" data-tauri-drag-region>
              {title}
            </p>
          )}
          <p className="capture-status-bar-meta" data-tauri-drag-region>
            <span data-tauri-drag-region>{statusLabel(status)}</span>
            {isLive && elapsedSeconds !== null && (
              <span
                className="capture-status-bar-elapsed"
                aria-label="Elapsed capture time"
                data-tauri-drag-region
              >
                {formatMeetingClock(elapsedSeconds)}
              </span>
            )}
          </p>
        </div>
        <button
          type="button"
          className="capture-status-bar-stop"
          onClick={() => {
            void invoke("capture_status_bar_stop_capture");
          }}
        >
          Stop
        </button>
      </div>
    </div>
  );
}
