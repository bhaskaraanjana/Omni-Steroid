/**
 * Settings — Automation group (Advanced): auto-start sources, silence
 * auto-stop, and live translation.
 *
 * Calendar connect rows now live in their own CalendarConnectSection (surfaced
 * under Essentials); this section owns only the capture-automation controls.
 * Every control persists through the REAL settings.update command.
 */
import { useEffect, useState } from "react";
import { useStore } from "zustand";
import { ToggleSwitch } from "../toggle-switch";
import { SettingsGroupCard, SettingsRow } from "./settings-group-card";
import { AUTOSTOP_SILENCE_OPTIONS, DETECTION_SOURCE_OPTIONS } from "../../lib/detection-source-options";
import type { SettingsStore } from "../../lib/settings-store";
import type { SettingsUpdater } from "../../lib/settings-actions";

export function DetectionAutomationSection({
  store,
  update,
}: {
  readonly store: SettingsStore;
  readonly update: SettingsUpdater;
}) {
  const autoStartSources = useStore(store, (s) => s.settings?.detectionAutoStartSources ?? []);
  const autostopSilenceS = useStore(store, (s) => s.settings?.autostopSilenceS ?? 0);

  const liveTranslationLang = useStore(store, (s) => s.settings?.liveTranslationLang ?? "");
  // Local draft so mid-keystroke values do not round-trip through settings.update.
  const [langDraft, setLangDraft] = useState(liveTranslationLang);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLangDraft(liveTranslationLang);
  }, [liveTranslationLang]);

  const apply = async (partial: Parameters<SettingsUpdater>[0]): Promise<void> => {
    const result = await update(partial);
    setError(result.ok ? null : result.message);
  };

  const persistLang = (raw: string): void => {
    if (raw === liveTranslationLang) return;
    void apply({ liveTranslationLang: raw });
  };

  const toggleAutoStart = (sourceId: string, enabled: boolean): void => {
    const current = new Set(autoStartSources);
    if (enabled) current.add(sourceId);
    else current.delete(sourceId);
    void apply({ detectionAutoStartSources: [...current].sort() });
  };

  return (
    <SettingsGroupCard label="Automation">
      <SettingsRow
        title="Auto-start capture"
        subCaption="On by default for every known meeting app. Turn a source off to require a toast click first. “Any app with sustained audio” stays opt-in — it can fire on music/YouTube."
      />
      {DETECTION_SOURCE_OPTIONS.map((option, index) => (
        <SettingsRow
          key={option.id}
          title={option.label}
          last={index === DETECTION_SOURCE_OPTIONS.length - 1}
        >
          <ToggleSwitch
            checked={autoStartSources.includes(option.id)}
            onChange={(next) => toggleAutoStart(option.id, next)}
            label={`Auto-start for ${option.label}`}
          />
        </SettingsRow>
      ))}
      <SettingsRow
        title="Silence auto-stop"
        subCaption="Stop after no new transcript for N seconds. Muted mic + headphones often look like silence — keep Off unless you want this. 0 = off."
      >
        <select
          aria-label="Silence auto-stop timeout"
          className="cursor-pointer border border-[var(--grey-300)] bg-[var(--canvas)] text-[var(--ink)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--focus-ring)]"
          style={{ fontSize: 13, height: "var(--control-height-sm)", borderRadius: "var(--radius-control)", padding: "0 var(--space-2)" }}
          value={autostopSilenceS}
          onChange={(e) => void apply({ autostopSilenceS: Number(e.target.value) })}
        >
          {AUTOSTOP_SILENCE_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </SettingsRow>
      <SettingsRow
        title="Live translation"
        subCaption="Translate recent transcript lines during capture (empty disables)."
        last={error === null}
      >
        <input
          aria-label="Live translation target language"
          className="omni-input"
          style={{ fontSize: 13, height: "var(--control-height-sm)", paddingLeft: 8, paddingRight: 8, width: 160 }}
          placeholder="e.g. Spanish"
          value={langDraft}
          onChange={(e) => setLangDraft(e.target.value)}
          onBlur={() => persistLang(langDraft)}
        />
      </SettingsRow>
      {error !== null && (
        <p role="alert" className="m-0 text-[var(--grey-600)]" style={{ padding: "8px 0", fontSize: 12 }}>
          {error}
        </p>
      )}
    </SettingsGroupCard>
  );
}
