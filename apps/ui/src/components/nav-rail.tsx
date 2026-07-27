/**
 * Left navigation rail (components doc §03): 224px, hairline right border,
 * the Omni lockup, one row per screen, and the on-device footer line.
 *
 * Sections are app state (no router dep — state-based routing in App.tsx).
 * The active indicator is a framer-motion shared-layout element; the Live
 * row carries the breathing ring while capture is genuinely live. Motion is
 * suppressed for users with prefers-reduced-motion.
 */
import { Fragment } from "react";
import { motion, useReducedMotion } from "framer-motion";
import { AudioLines, Home, Library, MessageSquareText, Mic, Settings, Sparkles } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { OmniMark } from "./omni-mark";
import { useTranscript } from "../lib/transcript-store";
import { requestCaptureStart, requestCaptureStop } from "../lib/capture-commands";
import { appSettingsStore } from "../lib/settings-store";
import { copy } from "../lib/copy";
import { useNaomiVisibility } from "../lib/use-naomi-visibility";
import { tokenDurationSeconds } from "../lib/design-token-motion";

export type SectionId = "home" | "library" | "live" | "ask" | "dictation" | "naomi" | "settings";

// Display labels are human-facing copy, sourced from the glossary
// (redesign-brief-v2.md §6). Exclude 'live' from the navigation tab list
// because it is rendered as a standalone primary CTA button at the top of
// the rail (redesign brief §5.1). Live capture status is shown on that CTA.
const SECTIONS: ReadonlyArray<{ id: Exclude<SectionId, "live">; label: string; icon: LucideIcon }> = [
  { id: "home", label: "Home", icon: Home },
  { id: "library", label: copy.nav.library, icon: Library },
  { id: "ask", label: copy.nav.ask, icon: MessageSquareText },
  { id: "dictation", label: copy.nav.dictation, icon: AudioLines },
  { id: "naomi", label: copy.nav.naomi, icon: Sparkles },
  { id: "settings", label: copy.nav.settings, icon: Settings },
];

interface NavRailProps {
  readonly active: SectionId;
  readonly onSelect: (section: SectionId) => void;
}

export function NavRail({ active, onSelect }: NavRailProps) {
  const reducedMotion = useReducedMotion();
  const captureStatus = useTranscript((s) => s.captureStatus);
  const captureLive = captureStatus === "live";
  const captureBusy = captureStatus === "starting" || captureStatus === "stopping";
  const { showNaomi } = useNaomiVisibility();

  const visibleSections = SECTIONS.filter((s) => s.id !== "naomi" || showNaomi);

  function onRecordCtaClick() {
    if (captureLive || captureStatus === "stopping") {
      requestCaptureStop();
      return;
    }
    onSelect("live");
    if (captureStatus === "starting") return;
    const mic = appSettingsStore.getState().microphone;
    requestCaptureStart(undefined, mic ? { micDeviceId: mic } : undefined);
  }

  const ctaLabel = captureLive
    ? "Stop recording"
    : captureStatus === "starting"
      ? "Starting…"
      : captureStatus === "stopping"
        ? "Stopping…"
        : "Record Meeting";

  return (
    <nav
      aria-label="Primary"
      className="flex shrink-0 flex-col border-r border-[var(--grey-200)]"
      style={{ width: 224, padding: "24px 16px" }} // doc: rail 224px, 24/16 padding
    >
      <div
        className="mb-[var(--space-8)] flex items-center px-[var(--space-3)]"
        style={{ gap: 20 }}
      >
        <OmniMark size={58} />
        <span
          // Daylight §4.2: the wordmark is the one place Space Grotesk still
          // appears — --font-display moved to Source Serif 4 for titles.
          className="font-[family-name:var(--font-wordmark)] font-extrabold text-[var(--ink)]"
          style={{ fontSize: 25, letterSpacing: "-0.03em" }} // doc: rail wordmark
        >
          Omni Steroid
        </span>
      </div>

      {/* Record CTA — idle starts capture; live stops (same as bottom bar). */}
      <div className="mb-6 px-1">
        <button
          type="button"
          aria-label={ctaLabel}
          disabled={captureBusy}
          onClick={onRecordCtaClick}
          className={`flex items-center justify-center gap-2.5 w-full border-none transition-all duration-[var(--dur-micro)] relative font-semibold ${
            captureBusy ? "cursor-wait opacity-80" : "cursor-pointer"
          } ${
            active === "live" || captureLive
              ? "bg-[var(--live)] text-white hover:bg-[var(--live-strong)] shadow-float"
              : "bg-[var(--ink)] text-[var(--canvas)] hover:opacity-90 shadow-raise"
          }`}
          style={{
            height: "var(--control-height)",
            borderRadius: "var(--radius-control)",
            fontSize: "var(--text-body-size)",
            transition: "all var(--dur-micro) var(--ease-out)",
          }}
        >
          {captureLive || captureStatus === "stopping" ? (
            <>
              <span className="h-2 w-2 rounded-full bg-white animate-pulse" />
              <span>{captureStatus === "stopping" ? "Stopping…" : "Stop recording"}</span>
            </>
          ) : (
            <>
              <Mic size={16} />
              <span>{captureStatus === "starting" ? "Starting…" : "Record Meeting"}</span>
            </>
          )}
        </button>
      </div>

      <ul className="m-0 flex list-none flex-col gap-[var(--space-1)] p-0">
        {visibleSections.map((section) => {
          const isActive = section.id === active;
          const Icon = section.icon;
          const showDivider = section.id === "settings";
          return (
            <Fragment key={section.id}>
              {showDivider && (
                <li
                  className="my-[var(--space-2)] border-t border-[var(--grey-200)]"
                  aria-hidden="true"
                />
              )}
              <li className="relative">
                {isActive && (
                  <>
                    <motion.span
                      aria-hidden
                      layoutId="nav-active-indicator"
                      // Duration comes from the --dur-micro design token; zero when
                      // the user prefers reduced motion (accessibility contract).
                      transition={{
                        type: "tween",
                        duration: reducedMotion ? 0 : tokenDurationSeconds("--dur-micro"),
                      }}
                      // Selected-nav wash is the accent (v2): a calm ink-blue tint,
                      // not grey — the one place accent marks "you are here".
                      className="absolute inset-0 rounded-[var(--radius-control)] bg-[var(--accent-muted)]"
                    />
                    <motion.span
                      aria-hidden
                      layoutId="nav-active-bar"
                      transition={{
                        type: "tween",
                        duration: reducedMotion ? 0 : tokenDurationSeconds("--dur-micro"),
                      }}
                      className="absolute left-0 top-[8px] bottom-[8px] w-[3px] rounded-r-full bg-[var(--accent)]"
                    />
                  </>
                )}
                <button
                  type="button"
                  aria-current={isActive ? "page" : undefined}
                  onClick={() => onSelect(section.id)}
                  className={
                    "group relative flex w-full cursor-pointer items-center gap-[var(--space-3)] border-none bg-transparent text-left transition-colors " +
                    (isActive
                      ? "font-semibold text-[var(--ink)]"
                      : "text-[var(--ink-secondary)] hover:text-[var(--ink)] hover:bg-[var(--grey-50)]")
                  }
                  // Doc nav row: padding 10px 12px (upgraded for 44px touch target), 14px body size.
                  style={{
                    padding: "10px 12px",
                    fontSize: "var(--text-body-size)",
                    borderRadius: "var(--radius-control)",
                    transition: "background-color var(--dur-micro) var(--ease-out), color var(--dur-micro) var(--ease-out)",
                  }}
                >
                  <Icon
                    aria-hidden
                    size={20}
                    strokeWidth={1.75}
                    className={`shrink-0 transition-all duration-[var(--dur-micro)] ${
                      isActive ? "text-[var(--accent)] opacity-100" : "text-[var(--ink-secondary)] opacity-70 group-hover:opacity-100 group-hover:text-[var(--ink)]"
                    }`}
                  />
                  <span>{section.label}</span>
                </button>
              </li>
            </Fragment>
          );
        })}
      </ul>
      <div className="mt-auto flex flex-col gap-[var(--space-3)]">
        {/* Local Security Shield Widget */}
        <div
          className="flex flex-col gap-2 p-3.5 border border-[var(--border)] bg-[var(--surface-sunken)]"
          style={{
            borderRadius: "var(--radius-card)",
          }}
        >
          <div className="flex items-center justify-between">
            <span
              className="font-semibold text-[var(--ink-secondary)]"
              style={{ fontSize: 10, letterSpacing: "0.08em", textTransform: "uppercase" }}
            >
              Security Status
            </span>
            <span className="flex h-2 w-2 rounded-full bg-emerald-500" />
          </div>
          <div className="flex items-center gap-2">
            <span className="text-[var(--ink)] font-semibold" style={{ fontSize: 12 }}>
              100% On-Device
            </span>
          </div>
          <span
            className="text-[var(--ink-secondary)] leading-normal"
            style={{ fontSize: 10 }}
          >
            Audio and transcripts never leave your computer without explicit consent.
          </span>
        </div>

        <div
          className="border-t border-[var(--border)] pt-3 px-1"
        >
          <p className="m-0 text-[var(--ink-secondary)]" style={{ fontSize: "var(--text-meta-size)" }}>
            {copy.nav.trustLine}
          </p>
        </div>
      </div>
    </nav>
  );
}
