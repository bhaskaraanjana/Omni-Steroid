/**
 * Entry point for the desktop capture-status-bar window
 * (Vite entry: capture-status-bar.html). Content is pushed from the main
 * window — no engine WebSocket here.
 */
import { StrictMode, useEffect } from "react";
import { createRoot } from "react-dom/client";

import "../styles/tokens.css";
import "../styles/fonts.css";
import "./capture-status-bar.css";
import { CAPTURE_STATUS_BAR_CONTENT_EVENT } from "../lib/wire-capture-status-bar";
import {
  applyCaptureStatusBarContent,
  captureStatusBarContentStore,
} from "./capture-status-bar-content-store";
import { CaptureStatusBarView } from "./capture-status-bar-view";

function CaptureStatusBarRoot() {
  useEffect(() => {
    let cancelled = false;
    let unlisten: (() => void) | undefined;
    void (async () => {
      try {
        const { listen } = await import("@tauri-apps/api/event");
        if (cancelled) return;
        unlisten = await listen(CAPTURE_STATUS_BAR_CONTENT_EVENT, (event) => {
          applyCaptureStatusBarContent(captureStatusBarContentStore, event.payload);
        });
        if (cancelled) {
          unlisten();
        }
      } catch {
        // Web build / tests: no Tauri shell.
      }
    })();
    return () => {
      cancelled = true;
      unlisten?.();
    };
  }, []);

  return <CaptureStatusBarView />;
}

const rootElement = document.getElementById("capture-status-bar-root");
if (rootElement === null) {
  throw new Error("Root element #capture-status-bar-root not found");
}

createRoot(rootElement).render(
  <StrictMode>
    <CaptureStatusBarRoot />
  </StrictMode>,
);
