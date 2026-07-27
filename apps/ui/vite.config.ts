// Vite config for the Omni UI. Also carries the vitest config so the whole
// front end builds and tests from one file — no parallel config to drift.
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],

  // Five windows: main app, dictation pill, live captions, meeting toast, capture status bar.
  build: {
    rollupOptions: {
      input: {
        main: "./index.html",
        pill: "./pill.html",
        captions: "./captions.html",
        "meeting-toast": "./meeting-toast.html",
        "capture-status-bar": "./capture-status-bar.html",
      },
    },
  },

  // Tauri expects a fixed dev port (see src-tauri/tauri.conf.json devUrl).
  // strictPort fails fast instead of silently moving — the shell would
  // otherwise load a blank window pointing at the wrong port.
  server: {
    port: 1420,
    strictPort: true,
  },
  // Keep terminal output visible alongside `tauri dev` logs.
  clearScreen: false,

  test: {
    environment: "jsdom",
    // CSS is irrelevant to these tests and tokens.css is design-agent-owned;
    // never let a missing/changed stylesheet fail logic tests.
    css: false,
    // e2e/ holds Playwright specs (own runner); vitest must not collect them.
    exclude: ["**/node_modules/**", "**/dist/**", "e2e/**"],
  },
});
