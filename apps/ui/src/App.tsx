/**
 * App shell: left nav rail, the active screen, status footer.
 *
 * State-based routing (no router dep): NavRail drives which screen renders,
 * with the 300ms view-transition motion from the design tokens. The single
 * engine connection (status heartbeats + capture/transcript events over one
 * socket) is started here so every screen sees live state from first paint.
 */
import { useEffect, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { NavRail, type SectionId } from "./components/nav-rail";
import { OmniMark } from "./components/omni-mark";
import { StatusFooter } from "./components/status-footer";
import { tokenDurationSeconds } from "./lib/design-token-motion";
import { startLiveEngineConnection } from "./lib/live-engine-socket";
import { wireTrayStartCapture } from "./lib/wire-tray-capture";
import { wireCaptionsOverlay } from "./lib/wire-captions-overlay";
import { wireAutoSummary } from "./lib/wire-auto-summary";
import { wireMeetingToastDesktop } from "./lib/wire-meeting-toast-desktop";
import { wireCaptureStatusBar } from "./lib/wire-capture-status-bar";
import { setAutoStartNavigateLive } from "./lib/auto-start-reaction";
import { loadSettings } from "./lib/settings-actions";
import { refreshDevicesIntoSettings } from "./lib/engine-devices";
import { appSettingsStore } from "./lib/settings-store";
import { transcriptStore } from "./lib/transcript-store";
import { getSetupStatus } from "./lib/setup-settings-repository";
import { syncConfiguredDictationHotkey } from "./lib/sync-dictation-hotkey";
import { useNaomiVisibility } from "./lib/use-naomi-visibility";
import type { SetupStatus } from "./lib/setup-settings-payloads";
import { ToastHost } from "./components/toast-host";
import { ApprovalRack } from "./components/approval/approval-rack";
import { NaomiView } from "./naomi/NaomiView";
import { OnboardingWizard } from "./screens/onboarding/onboarding-wizard";
import { HomeScreen } from "./screens/home-screen";
import { AskScreen } from "./screens/ask-screen";
import { LibraryScreen } from "./screens/library-screen";
import { LiveMeetingScreen } from "./screens/live-meeting-screen";
import { DictationHistoryScreen } from "./screens/dictation-history-screen";
import { SettingsScreen } from "./screens/settings-screen";
import { requestCaptureStart } from "./lib/capture-commands";
import { apiKeysStore, hydrateApiKeysFromSetupStatus } from "./lib/api-keys-store";
import { showToast } from "./lib/toast-store";

/** Boot gate: first-run onboarding vs the main shell, from real setup.status. */
type Gate = "checking" | "onboarding" | "app" | "offline";

/**
 * App root. On boot it starts the single engine connection and asks the engine
 * for the real setup.status: an incomplete setup renders the first-run wizard;
 * otherwise the main shell. If the engine stays unreachable, show an honest
 * offline screen with Retry — never skip a first-run user past onboarding.
 */
export default function App({
  checkStatus = getSetupStatus,
  bootRetryBudgetMs = 10_000,
}: {
  readonly checkStatus?: () => Promise<SetupStatus>;
  // Bounded retry window for the cold-boot setup.status probe. Injectable so
  // tests can assert the give-up path without a real 10 s wait.
  readonly bootRetryBudgetMs?: number;
} = {}) {
  const [gate, setGate] = useState<Gate>("checking");
  const [bootAttempt, setBootAttempt] = useState(0);

  useEffect(() => {
    startLiveEngineConnection(); // idempotent; safe under StrictMode double-mount
    const savedTheme = localStorage.getItem("omni-theme") || "evergreen";
    document.documentElement.setAttribute("data-theme", savedTheme);
    let cancelled = false;
    const deadline = Date.now() + bootRetryBudgetMs;
    const attempt = (): void => {
      void checkStatus()
        .then((status) => {
          if (cancelled) return;
          hydrateApiKeysFromSetupStatus(apiKeysStore, status.keys);
          setGate(status.onboardingComplete ? "app" : "onboarding");
          // Hotkey sync after first successful engine status (WS is up).
          void syncConfiguredDictationHotkey(undefined, bootRetryBudgetMs);
        })
        .catch(() => {
          if (cancelled) return;
          if (Date.now() < deadline) {
            window.setTimeout(attempt, 400);
          } else {
            // Fail closed on first-run: do not invent "setup complete".
            setGate("offline");
          }
        });
    };
    attempt();
    return () => {
      cancelled = true;
    };
  }, [checkStatus, bootRetryBudgetMs, bootAttempt]);

  if (gate === "checking") {
    return (
      <div className="flex h-full items-center justify-center bg-[var(--canvas)]" aria-label="Starting Omni">
        <span className="omni-breathe" aria-hidden>
          <OmniMark size={64} />
        </span>
      </div>
    );
  }
  if (gate === "offline") {
    return (
      <div
        className="flex h-full flex-col items-center justify-center gap-4 bg-[var(--canvas)] px-8 text-center"
        role="alert"
        aria-label="Engine offline"
      >
        <OmniMark size={48} />
        <h1
          className="m-0 font-[family-name:var(--font-display)] font-semibold text-[var(--ink)]"
          style={{ fontSize: 22 }}
        >
          Can’t reach the Omni engine
        </h1>
        <p className="m-0 max-w-md text-[var(--ink-secondary)]" style={{ fontSize: 14, lineHeight: 1.5 }}>
          The app needs the local engine before setup or meetings can continue. Start the engine (or wait for the
          sidecar), then retry — we won’t skip first-run setup.
        </p>
        <button
          type="button"
          className="cursor-pointer rounded-[var(--radius-control)] bg-[var(--accent)] px-4 py-2 font-medium text-[var(--on-accent)]"
          onClick={() => {
            setGate("checking");
            setBootAttempt((n) => n + 1);
          }}
        >
          Retry connection
        </button>
      </div>
    );
  }
  if (gate === "onboarding") {
    return <OnboardingWizard onComplete={() => setGate("app")} />;
  }
  return <MainShell />;
}

function MainShell() {
  const [activeSection, setActiveSection] = useState<SectionId>("home");
  const [dictationAutoRecord, setDictationAutoRecord] = useState(false);
  const reducedMotion = useReducedMotion();
  const { showNaomi } = useNaomiVisibility();

  useEffect(() => {
    if (activeSection === "naomi" && !showNaomi) {
      setActiveSection("home");
    }
  }, [activeSection, showNaomi]);

  useEffect(() => {
    void loadSettings(appSettingsStore);
    void refreshDevicesIntoSettings(appSettingsStore);
    const goLive = (): void => setActiveSection("live");
    setAutoStartNavigateLive(goLive);
    let cancelled = false;
    let unwireCaptions: (() => void) | undefined;
    let unwireMeetingToast: (() => void) | undefined;
    let unwireCaptureStatusBar: (() => void) | undefined;
    let unlistenTray: (() => void) | undefined;
    let unlistenEngineUnhealthy: (() => void) | undefined;
    try {
      unwireCaptions = wireCaptionsOverlay(appSettingsStore);
    } catch {
      // Web build / tests: no Tauri shell.
    }
    void (async () => {
      try {
        const { listen } = await import("@tauri-apps/api/event");
        if (cancelled) return;
        unlistenTray = await wireTrayStartCapture(
          (event, handler) => listen(event, handler).then((fn) => fn),
          goLive,
        );
        if (cancelled) {
          unlistenTray();
          return;
        }
        unwireMeetingToast = wireMeetingToastDesktop(goLive, undefined, undefined, (event, handler) =>
          listen(event, handler).then((fn) => fn),
        );
        if (cancelled) {
          unwireMeetingToast();
          return;
        }
        unwireCaptureStatusBar = wireCaptureStatusBar(transcriptStore, (event, handler) =>
          listen(event, handler).then((fn) => fn),
        );
        if (cancelled) {
          unwireCaptureStatusBar();
          return;
        }
        unlistenEngineUnhealthy = await listen(
          "engine:unhealthy",
          (event: { payload: unknown }) => {
            const payload = event.payload;
            const message =
              typeof payload === "object" &&
              payload !== null &&
              "reason" in payload &&
              typeof (payload as { reason: unknown }).reason === "string"
                ? (payload as { reason: string }).reason
                : "The local engine is not staying running.";
            showToast(message, "error", undefined, 8_000);
          },
        );
        if (cancelled) {
          unlistenEngineUnhealthy();
        }
      } catch {
        // Web build / tests: no Tauri shell — tray / desktop toast unavailable.
      }
    })();
    const unwireAutoSummary = wireAutoSummary();
    return () => {
      cancelled = true;
      setAutoStartNavigateLive(undefined);
      unwireCaptions?.();
      unwireMeetingToast?.();
      unwireCaptureStatusBar?.();
      unlistenTray?.();
      unlistenEngineUnhealthy?.();
      unwireAutoSummary();
    };
  }, []);

  return (
    <div className="flex h-full flex-col bg-[var(--canvas)] text-[var(--ink)]">
      <div className="flex min-h-0 flex-1">
        <NavRail active={activeSection} onSelect={setActiveSection} />
        <main className="relative min-w-0 flex-1 overflow-hidden">
          <AnimatePresence mode="wait" initial={false}>
            <motion.div
              key={activeSection}
              className="h-full"
              // View transition: 300ms ease-out, transform/opacity only.
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={{
                type: "tween",
                ease: [0, 0, 0.2, 1],
                duration: reducedMotion ? 0 : tokenDurationSeconds("--dur-page"),
              }}
            >
              {activeSection === "home" && (
                <HomeScreen
                  onNavigate={(sec) => setActiveSection(sec)}
                  onStartCapture={() => {
                    setActiveSection("live");
                    // Primary CTA must actually start capture — not only navigate.
                    const mic = appSettingsStore.getState().microphone;
                    requestCaptureStart(
                      undefined,
                      mic ? { micDeviceId: mic } : undefined,
                    );
                  }}
                  onRecordInline={() => {
                    setDictationAutoRecord(true);
                    setActiveSection("dictation");
                  }}
                />
              )}
              {activeSection === "library" && <LibraryScreen />}
              {activeSection === "live" && <LiveMeetingScreen />}
              {activeSection === "ask" && <AskScreen />}
              {activeSection === "dictation" && (
                <DictationHistoryScreen
                  autoStartRecording={dictationAutoRecord}
                  onAutoStartConsumed={() => setDictationAutoRecord(false)}
                />
              )}
              {activeSection === "naomi" && <NaomiView />}
              {activeSection === "settings" && <SettingsScreen />}
            </motion.div>
          </AnimatePresence>
        </main>
      </div>
      <StatusFooter />
      <ToastHost />
      <div className="pointer-events-none fixed bottom-16 right-4 z-40 max-w-md [&_*]:pointer-events-auto">
        <ApprovalRack meetingId={null} includeGlobal />
      </div>
    </div>
  );
}
