/**
 * Autostop copy must describe STT/transcript inactivity — not "audio streams".
 */
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { DetectionAutomationSection } from "./detection-automation-section";
import { createSettingsStore } from "../../lib/settings-store";
import type { EngineSettings } from "../../lib/setup-settings-payloads";
import { installJsdomMatchMediaShim } from "../../test-support/install-jsdom-match-media-shim";

beforeAll(installJsdomMatchMediaShim);
afterEach(cleanup);

const BASE: EngineSettings = {
  vaultDir: "C:/vault",
  pushToTalkHotkey: ["F9"],
  keepAudio: true,
  disclosureReminder: true,
  killSwitch: false,
  instantExecuteWhitelist: [],
  activeTemplate: "auto",
  customTemplates: [],
  onboardingComplete: true,
  detectionAutoStartSources: [],
  autostopSilenceS: 60,
  liveCaptionsOverlay: false,
  aecEnabled: false,
  liveTranslationLang: "",
  summaryLanguage: "",
  speakerIdentity: "Me",
  speakerVoiceEnrolled: false,
  dictationCleanupStyle: "classic",
  sttEngine: "parakeet",
  sttModelId: "",
  sttOpenaiBaseUrl: "",
  selectionTranslationLang: "",
  summaryModelId: "llama3.2",
  ollamaBaseUrl: "http://127.0.0.1:11434",
  summaryProvider: "ollama",
  autoSummary: false,
  cartesiaVoiceId: "",
  micDeviceId: "",
};

describe("DetectionAutomationSection autostop copy", () => {
  it("describes transcript/STT inactivity, not audio-stream silence", () => {
    const store = createSettingsStore();
    store.setState({ settings: { ...BASE }, settingsPhase: "ready" });
    render(
      <DetectionAutomationSection
        store={store}
        update={vi.fn(async () => ({ ok: true, message: null }))}
      />,
    );
    expect(screen.queryByText(/sustained silence on both audio streams/i)).toBeNull();
    expect(screen.getByText(/Muted mic \+ headphones often look like silence/i)).toBeTruthy();
  });
});
