/**
 * Live meeting — the flagship screen: notepad left (flex:2), live transcript
 * right (flex:1), capture bar below, answers panel floating bottom-right.
 *
 * Transcript, lag and capture lifecycle are LIVE-WIRED to the engine's
 * transcript.partial / transcript.final / capture.* events via
 * transcript-store; answers-panel hits come from live-answers-store, fed by
 * the engine's answers.hit events (M3 live tier). States: idle (pre-capture,
 * honest about an offline engine), starting, live, stopped, and error — no
 * state is faked.
 */
import { useEffect, useState, type ReactNode } from "react";
import { useStore } from "zustand";
import { Mic } from "lucide-react";
import { OmniButton } from "../components/button";
import { OmniMark } from "../components/omni-mark";
import { AnswersPanel } from "../components/live/answers-panel";
import { LiveSummaryPanel } from "../components/live/live-summary-panel";
import { LiveTranslationPanel } from "../components/live/live-translation-panel";
import { VaultSuggestionsPanel } from "../components/live/vault-suggestions-panel";
import { CaptureBar } from "../components/live/capture-bar";
import { FinalizeMeetingPanel } from "../components/live/finalize-meeting-panel";
import { NotepadPane } from "../components/live/notepad-pane";
import { TranscriptStream } from "../components/live/transcript-stream";
import { cancelCaptureStart, requestCaptureStart } from "../lib/capture-commands";
import { useEngineStatus } from "../lib/engine-status-store";
import { bindNotepadToMeeting, notepadStore } from "../lib/notepad-store";
import { useTranscript } from "../lib/transcript-store";
import { appSettingsStore, setMicrophone } from "../lib/settings-store";
import { updateSetting } from "../lib/settings-actions";
import { useMicLevelPercent } from "../lib/use-mic-level-percent";

/** Ticks once a second while live so the timer and bubbles share one clock. */
function useElapsedSeconds(startedAtMs: number | null): number {
  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    if (startedAtMs === null) return undefined;
    const timer = setInterval(() => setNowMs(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [startedAtMs]);
  if (startedAtMs === null) return 0;
  return Math.max(0, (nowMs - startedAtMs) / 1000);
}

function MicCheckWidget() {
  const store = appSettingsStore;
  const devicesSource = useStore(store, (s) => s.devicesSource);
  const microphone = useStore(store, (s) => s.microphone);
  const options = useStore(store, (s) => s.microphoneOptions);
  const { level: micLevel, micActive } = useMicLevelPercent(true, microphone);

  return (
    <div className="w-full p-4 border border-[var(--grey-200)] rounded-[var(--radius-card)] bg-[var(--grey-50)] flex flex-col gap-3 text-left">
      <div className="flex items-center gap-2">
        <Mic size={16} className="text-[var(--accent)]" />
        <span className="text-xs font-semibold text-[var(--ink)]">Microphone check</span>
      </div>

      {devicesSource === "engine" ? (
        <select
          aria-label="Select Microphone"
          value={microphone}
          onChange={(e) => {
            const id = e.target.value;
            setMicrophone(store, id);
            void updateSetting(store, { micDeviceId: id });
          }}
          className="w-full omni-input"
          style={{ fontSize: 13, height: "var(--control-height-sm)", paddingLeft: 8, paddingRight: 8 }}
        >
          {options.map((option) => (
            <option key={option.id} value={option.id}>
              {option.name}
            </option>
          ))}
        </select>
      ) : (
        <span className="text-xs text-[var(--ink-secondary)]">
          {devicesSource === "pending"
            ? "Reading devices from Omni Steroid..."
            : "Omni Steroid is offline — devices unavailable"}
        </span>
      )}

      {micActive ? (
        <div className="flex flex-col gap-1.5">
          <div className="flex justify-between text-[10px] font-mono text-[var(--ink-secondary)]">
            <span>Audio level</span>
            <span>{micLevel}%</span>
          </div>
          <div className="h-1.5 bg-[var(--grey-200)] rounded-full overflow-hidden">
            <div 
              className="h-full bg-[var(--accent)] rounded-full transition-all duration-75"
              style={{ width: `${micLevel}%` }}
            />
          </div>
        </div>
      ) : (
        <span className="text-[11px] text-[var(--ink-secondary)]">
          Grant microphone access to check input level.
        </span>
      )}
    </div>
  );
}

function PreCaptureState({
  heading,
  body,
  errorMessage,
  children,
}: {
  readonly heading: string;
  readonly body: string;
  readonly errorMessage: string | null;
  /** Extra flow content (e.g. the finalize panel after a stop). */
  readonly children?: ReactNode;
}) {
  const engineStatus = useEngineStatus((s) => s.status);
  const sttReady = useEngineStatus((s) => s.sttReady);
  const captureStatus = useTranscript((s) => s.captureStatus);
  const engineDown = engineStatus !== "connected";
  const starting = captureStatus === "starting";
  const modelsLoading = !engineDown && !sttReady;

  return (
    <div className="flex h-full items-center justify-center">
      <div className="flex w-full max-w-md flex-col items-stretch gap-[var(--space-4)] px-[var(--space-8)] text-center">
        <div className="omni-breathe mb-[var(--space-2)] self-center">
          <OmniMark size={64} />
        </div>
        <h1
          className="m-0 font-[family-name:var(--font-display)] font-semibold text-[var(--ink)]"
          style={{
            fontSize: "var(--text-title-size)",
            lineHeight: "var(--text-title-lh)",
            letterSpacing: "var(--text-title-ls)",
          }}
        >
          {heading}
        </h1>
        <p
          className="m-0 text-[var(--grey-600)]"
          style={{ fontSize: "var(--text-body-size)", lineHeight: "var(--text-body-lh)" }}
        >
          {body}
        </p>

        {!engineDown && <MicCheckWidget />}

        <OmniButton
          variant="primary"
          disabled={engineDown || starting || modelsLoading}
          onClick={() => {
            const mic = appSettingsStore.getState().microphone;
            requestCaptureStart(undefined, mic ? { micDeviceId: mic } : undefined);
          }}
          className="w-full justify-center"
        >
          {starting
            ? "Starting capture…"
            : modelsLoading
              ? "Loading speech models…"
              : "Start capture"}
        </OmniButton>
        {starting && (
          <OmniButton
            variant="secondary"
            onClick={() => cancelCaptureStart()}
            className="w-full justify-center"
          >
            Cancel
          </OmniButton>
        )}
        {engineDown && (
          <div
            className="w-full text-center px-[var(--space-4)] py-[var(--space-3)] border border-solid border-[var(--warning)] bg-[var(--warning-bg)] text-[var(--warning-text)] rounded-[var(--radius-control)]"
            style={{ fontSize: 13 }}
          >
            The engine is offline — capture needs the engine running on this device.
          </div>
        )}
        {modelsLoading && !starting && (
          <div
            className="w-full text-center px-[var(--space-4)] py-[var(--space-3)] border border-solid border-[var(--warning)] bg-[var(--warning-bg)] text-[var(--warning-text)] rounded-[var(--radius-control)]"
            style={{ fontSize: 13 }}
          >
            Speech models are still loading. Wait until this clears, then start.
          </div>
        )}
        {errorMessage !== null && (
          <div
            role="alert"
            className="w-full text-center px-[var(--space-4)] py-[var(--space-3)] border border-solid border-[var(--error)] bg-[var(--error-bg)] text-[var(--error-text)] rounded-[var(--radius-control)]"
            style={{ fontSize: 13 }}
          >
            {errorMessage}
          </div>
        )}
        {children}
      </div>
    </div>
  );
}

export function LiveMeetingScreen() {
  const captureStatus = useTranscript((s) => s.captureStatus);
  const meetingId = useTranscript((s) => s.meetingId);
  const startedAtMs = useTranscript((s) => s.captureStartedAtMs);
  const errorMessage = useTranscript((s) => s.errorMessage);
  const elapsedSeconds = useElapsedSeconds(startedAtMs);

  // A new meeting gets a fresh notepad page; the same meeting keeps its buffer.
  useEffect(() => {
    if (meetingId !== null) bindNotepadToMeeting(notepadStore, meetingId);
  }, [meetingId]);

  if (captureStatus === "idle" || captureStatus === "starting") {
    return (
      <div className="relative h-full">
        <PreCaptureState
          heading="Record a meeting"
          body="Capture the room and your mic as two labelled streams, transcribed on this device. No bot joins the call and nothing leaves this machine."
          errorMessage={errorMessage}
        />
      </div>
    );
  }

  if (captureStatus === "stopped" || captureStatus === "error") {
    return (
      <div className="relative h-full">
        <PreCaptureState
          heading={captureStatus === "error" ? "Capture ended with an error" : "Capture stopped"}
          body={
            captureStatus === "error"
              ? "The engine reported an error and capture ended. Everything transcribed so far is saved on this device."
              : "The meeting is saved on this device. Finalize it to fuse your notes with the transcript into the enhanced vault note."
          }
          errorMessage={errorMessage}
        >
          {/* Finalize needs a real ended meeting; the buffer travels verbatim. */}
          {meetingId !== null && <FinalizeMeetingPanel meetingId={meetingId} />}
        </PreCaptureState>
      </div>
    );
  }

  // live / stopping: the full flagship layout. Detection toast lives on App shell.
  return (
    <div className="relative flex h-full min-h-0 flex-col">
      <div className="flex min-h-0 flex-1 flex-col">
        <div className="flex min-h-0 flex-1">
          {/* Left column: auxiliary panels as collapsible drawers (summary and
              translation default-closed; notes default-open) so the default
              view stays transcript-forward. */}
          <div className="flex min-w-0 flex-col overflow-y-auto border-r border-solid border-[var(--grey-200)]" style={{ flex: 1 }}>
            <LiveSummaryPanel />
            <LiveTranslationPanel />
            <NotepadPane meetingTitle="Live meeting" elapsedSeconds={elapsedSeconds} />
          </div>
          <TranscriptStream />
        </div>
      </div>
      <CaptureBar elapsedSeconds={elapsedSeconds} />
      <VaultSuggestionsPanel />
      <AnswersPanel />
    </div>
  );
}
