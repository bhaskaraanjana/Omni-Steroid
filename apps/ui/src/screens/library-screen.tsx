/**
 * Library — home screen: every captured meeting, newest first, grouped by
 * day, with a search filter that narrows as you type, and a detail pane
 * (enhanced notes / my notes / transcript) opened by clicking a row.
 *
 * Data flows from meetings-store through the MeetingsRepository interface —
 * the LIVE engine repository (meetings.list over WS) by default; tests
 * inject fakes. States: loading (shimmer, never a spinner), error (+ retry),
 * empty, and populated with a separate no-matches state for a live query.
 */
import { useEffect, useMemo, useState } from "react";
import { useStore } from "zustand";
import { Search } from "lucide-react";
import { OmniButton } from "../components/button";
import { ToggleSwitch } from "../components/toggle-switch";
import { OmniMark } from "../components/omni-mark";
import { SectionLabel } from "../components/section-label";
import { SkeletonShimmer } from "../components/skeleton-shimmer";
import {
  calendarUpcomingStore,
  getActiveCalendarUpcoming,
} from "../lib/calendar-upcoming-store";
import {
  formatClockShort,
  formatDayLabel,
  formatDurationMin,
  formatStartsIn,
} from "../lib/format-quantities";
import { useEngineStatus } from "../lib/engine-status-store";
import {
  meetingsDetailStore,
  openMeetingDetail,
  useMeetingsDetail,
} from "../lib/meetings-detail-store";
import {
  createLiveMeetingsRepository,
  getMeetingDetail,
  importMediaFile,
  requestMeetingFinalize,
} from "../lib/meetings-live-repository";
import { pickMediaFile } from "../lib/pick-media-file";
import {
  filterMeetings,
  loadMeetings,
  meetingsStore,
  setMeetingsQuery,
  useMeetings,
  type MeetingsRepository,
  type MeetingSummaryRow,
} from "../lib/meetings-store";
import {
  LibraryMeetingDetailPane,
  type DetailLoader,
  type MeetingFinalizer,
} from "./library-meeting-detail-pane";
import { wireLibraryDragDrop } from "../lib/wire-library-drag-drop";
import { subscribeToEngineFrames } from "../lib/live-engine-socket";
import { parseInboundMessage } from "../lib/protocol";
import { CAPTURE_STOPPED_EVENT_NAME } from "../lib/capture-protocol";
import {
  IMPORT_MEDIA_PROGRESS_EVENT,
  parseImportMediaProgressPayload,
} from "../lib/import-media-progress";

/** LIVE engine repository (meetings.list over the WS protocol). */
const defaultRepository: MeetingsRepository = createLiveMeetingsRepository();
const defaultDetailLoader: DetailLoader = (id) => getMeetingDetail(id);
const defaultFinalizer: MeetingFinalizer = (id, notepad) => requestMeetingFinalize(id, notepad);

function MeetingRow({
  meeting,
  onOpen,
}: {
  readonly meeting: MeetingSummaryRow;
  readonly onOpen: (meetingId: string) => void;
}) {
  const startsIn = formatStartsIn(meeting.startIso);
  const upcoming = startsIn !== null;
  return (
    <li className="list-none">
      <button
        type="button"
        aria-label={`Open ${meeting.title}`}
        onClick={() => onOpen(meeting.id)}
        className="grid w-full cursor-pointer items-baseline border-0 border-t border-solid border-[var(--grey-200)] bg-transparent text-left hover:bg-[var(--grey-50)] hover:translate-x-[2px] hover:shadow-[var(--shadow-float)]"
        // Doc row spec: 88px | 1fr | 120px, gap 24, padding 18px 16px, -16px bleed.
        style={{
          gridTemplateColumns: "88px 1fr 120px",
          gap: "var(--space-6)",
          padding: "18px 16px",
          margin: "0 -16px",
          width: "calc(100% + 32px)",
          borderRadius: "var(--radius-control)",
          transition: "transform var(--dur-micro) var(--ease-out), background-color var(--dur-micro) var(--ease-out), box-shadow var(--dur-micro) var(--ease-out)",
        }}
      >
        <span
          className={`font-[family-name:var(--font-mono)] ${upcoming ? "text-[var(--ink)]" : "text-[var(--ink-secondary)]"}`}
          style={{ fontSize: "var(--text-meta-size)" }}
        >
          {formatClockShort(meeting.startIso)}
        </span>
        <span className="flex min-w-0 flex-col gap-[var(--space-1)]">
          <span className="truncate font-medium text-[var(--ink)]" style={{ fontSize: 15 }}>
            {meeting.title}
          </span>
          {meeting.summary.length > 0 && (
            <span className="truncate text-[var(--ink-secondary)]" style={{ fontSize: 13 }}>
              {meeting.summary}
            </span>
          )}
        </span>
        <span
          className={`text-right font-[family-name:var(--font-mono)] ${upcoming ? "text-[var(--grey-600)]" : "text-[var(--ink-secondary)]"}`}
          style={{ fontSize: "var(--text-meta-size)" }}
        >
          {upcoming ? startsIn : formatDurationMin(meeting.durationMin)}
        </span>
      </button>
    </li>
  );
}

export function LibraryScreen({
  repository = defaultRepository,
  detailLoader = defaultDetailLoader,
  finalizer = defaultFinalizer,
}: {
  readonly repository?: MeetingsRepository;
  readonly detailLoader?: DetailLoader;
  readonly finalizer?: MeetingFinalizer;
}) {
  const status = useMeetings((s) => s.status);
  const meetings = useMeetings((s) => s.meetings);
  const query = useMeetings((s) => s.query);
  const errorMessage = useMeetings((s) => s.errorMessage);
  const selectedId = useMeetingsDetail((s) => s.selectedId);
  const engineStatus = useEngineStatus((s) => s.status);
  const [importBusy, setImportBusy] = useState(false);
  const [importMessage, setImportMessage] = useState<string | null>(null);
  const [importProgress, setImportProgress] = useState<{
    stage: string;
    percent: number;
  } | null>(null);
  const [identifySpeakers, setIdentifySpeakers] = useState(false);
  const upcomingCalendar = useStore(calendarUpcomingStore, () =>
    getActiveCalendarUpcoming(calendarUpcomingStore),
  );

  useEffect(() => {
    // Always reload on mount so a capture finished while away from Library
    // still appears. Retry / error recovery remain explicit elsewhere.
    void loadMeetings(meetingsStore, repository);
  }, [repository]);

  useEffect(() => {
    // Cold-boot race recovery: the Library is the default screen, so it mounts
    // before the engine WebSocket has finished opening — the first meetings.list
    // then fails "offline" even though the engine is fine. When the connection
    // comes up, re-load once so the user never sees a false offline state and
    // never has to click Retry. Only re-loads out of the error state (a healthy
    // ready/loading state is left untouched — no redundant refetch).
    if (engineStatus === "connected" && meetingsStore.getState().status === "error") {
      void loadMeetings(meetingsStore, repository);
    }
  }, [engineStatus, repository]);

  useEffect(() => {
    // Refresh while Library is open when a capture ends (new meeting row).
    return subscribeToEngineFrames((data) => {
      const result = parseInboundMessage(data);
      if (!result.ok || result.envelope.kind !== "event") return;
      if (result.envelope.name === CAPTURE_STOPPED_EVENT_NAME) {
        void loadMeetings(meetingsStore, repository);
        return;
      }
      if (result.envelope.name !== IMPORT_MEDIA_PROGRESS_EVENT) return;
      const progress = parseImportMediaProgressPayload(result.envelope.payload);
      if (progress === null) return;
      setImportProgress({ stage: progress.stage, percent: progress.percent });
    });
  }, [repository]);

  useEffect(() => {
    return wireLibraryDragDrop(
      () => {
        void loadMeetings(meetingsStore, repository);
      },
      {
        identifySpeakers: () => identifySpeakers,
        onError: (message) => setImportMessage(message),
      },
    );
  }, [repository, identifySpeakers]);

  const visible = useMemo(() => filterMeetings(meetings, query), [meetings, query]);
  const groups = useMemo(() => {
    const byDay = new Map<string, MeetingSummaryRow[]>();
    for (const meeting of visible) {
      const label = formatDayLabel(meeting.startIso);
      const bucket = byDay.get(label);
      if (bucket === undefined) byDay.set(label, [meeting]);
      else bucket.push(meeting);
    }
    return [...byDay.entries()];
  }, [visible]);

  const capturedMin = meetings.reduce((acc, m) => acc + m.durationMin, 0);
  const openDetail = (meetingId: string): void =>
    openMeetingDetail(meetingsDetailStore, meetingId);

  const importMedia = async (): Promise<void> => {
    setImportMessage(null);
    setImportProgress(null);
    const path = await pickMediaFile();
    if (path === null) return;
    setImportBusy(true);
    try {
      const meetingId = await importMediaFile(path, undefined, {
        identifySpeakers,
      });
      await loadMeetings(meetingsStore, repository);
      openDetail(meetingId);
    } catch (err) {
      setImportMessage(err instanceof Error ? err.message : "Import failed.");
    } finally {
      setImportBusy(false);
      setImportProgress(null);
    }
  };

  return (
    <div className="flex h-full">
      <div className="h-full flex-1 overflow-y-auto" style={{ padding: "48px 64px" }}>
      <header className="flex items-start justify-between gap-[var(--space-4)]">
        <div className="flex flex-col gap-[var(--space-2)]">
          <h1
            className="m-0 font-[family-name:var(--font-display)] font-semibold text-[var(--ink)]"
            style={{
              fontSize: "var(--text-title-size)",
              lineHeight: "var(--text-title-lh)",
              letterSpacing: "var(--text-title-ls)",
            }}
          >
            Meetings
          </h1>
          {status === "ready" && meetings.length > 0 && (
            <span
              className="font-[family-name:var(--font-mono)] text-[var(--ink-secondary)]"
              style={{ fontSize: "var(--text-meta-size)" }}
            >
              {meetings.length} meetings · {formatDurationMin(capturedMin)} captured · all on this device
            </span>
          )}
        </div>
        <div className="flex flex-col items-end gap-2">
          <div className="flex items-center gap-2 text-sm text-[var(--ink-secondary)]">
            <ToggleSwitch
              checked={identifySpeakers}
              onChange={setIdentifySpeakers}
              label="Identify speakers"
            />
            <span>Identify speakers (slower)</span>
          </div>
          <OmniButton variant="secondary" disabled={importBusy} onClick={() => void importMedia()}>
            {importBusy
              ? importProgress !== null
                ? `Importing… ${importProgress.stage} ${importProgress.percent}%`
                : "Importing…"
              : "Import media"}
          </OmniButton>
        </div>
      </header>
      {importMessage !== null && (
        <p className="m-0 mt-[var(--space-2)] text-[var(--grey-600)]" style={{ fontSize: 13 }}>
          {importMessage}
        </p>
      )}
      {upcomingCalendar !== null && (
        <p
          role="status"
          className="m-0 mt-[var(--space-2)] text-[var(--ink-secondary)]"
          style={{ fontSize: 13 }}
        >
          Upcoming ({upcomingCalendar.provider}): {upcomingCalendar.title} —{" "}
          {formatStartsIn(upcomingCalendar.startIso) ?? upcomingCalendar.startIso}
        </p>
      )}

      <div className="relative mt-[var(--space-6)]" style={{ width: 240 }}>
        <Search
          className="absolute text-[var(--ink-secondary)] pointer-events-none"
          style={{
            left: 12,
            top: "50%",
            transform: "translateY(-50%)",
            width: 16,
            height: 16,
          }}
        />
        <input
          type="search"
          aria-label="Search meetings"
          placeholder="Search meetings"
          value={query}
          onChange={(event) => setMeetingsQuery(meetingsStore, event.target.value)}
          className="omni-input w-full"
          style={{
            paddingLeft: 36,
          }}
        />
      </div>

      <div className="mt-[var(--space-8)]">
        {status === "loading" && <SkeletonShimmer lines={4} />}

        {status === "error" && (
          <div className="flex max-w-md flex-col items-start gap-[var(--space-3)]">
            <p className="m-0 text-[var(--ink)]" style={{ fontSize: "var(--text-body-size)" }}>
              Could not load your meetings.
            </p>
            <p className="m-0 text-[var(--grey-600)]" style={{ fontSize: 13 }}>
              {errorMessage}
            </p>
            <OmniButton
              variant="secondary"
              onClick={() => void loadMeetings(meetingsStore, repository)}
            >
              Retry loading
            </OmniButton>
          </div>
        )}

        {status === "ready" && meetings.length === 0 && (
          <div className="flex max-w-md flex-col items-start gap-[var(--space-3)]">
            <div style={{ opacity: 0.15, marginBottom: "var(--space-2)" }}>
              <OmniMark size={48} />
            </div>
            <h2
              className="m-0 font-[family-name:var(--font-display)] font-semibold text-[var(--ink)]"
              style={{ fontSize: "var(--text-section-size)", letterSpacing: "var(--text-section-ls)" }}
            >
              No meetings yet
            </h2>
            <p className="m-0 text-[var(--grey-600)]" style={{ fontSize: "var(--text-body-size)", lineHeight: "var(--text-body-lh)" }}>
              Use Record Meeting in the sidebar (or Home) to start a capture. Meetings appear
              here with labelled transcript streams and your notes — no bot joins the call.
            </p>
          </div>
        )}

        {status === "ready" && meetings.length > 0 && visible.length === 0 && (
          <p className="m-0 text-[var(--grey-600)]" style={{ fontSize: "var(--text-body-size)" }}>
            No meetings match “{query.trim()}”.
          </p>
        )}

        {status === "ready" &&
          groups.map(([dayLabel, rows]) => (
            <section key={dayLabel} aria-label={dayLabel}>
              <div style={{ padding: "var(--space-10) 0 var(--space-4)" }}>
                <SectionLabel>{dayLabel}</SectionLabel>
              </div>
              <ul className="m-0 p-0">
                {rows.map((meeting) => (
                  <MeetingRow key={meeting.id} meeting={meeting} onOpen={openDetail} />
                ))}
              </ul>
            </section>
          ))}
        </div>
      </div>

      {selectedId !== null && (
        <LibraryMeetingDetailPane
          meetingId={selectedId}
          loadDetail={detailLoader}
          finalizeMeeting={finalizer}
          onFinalized={() => void loadMeetings(meetingsStore, repository)}
          onDeleted={() => void loadMeetings(meetingsStore, repository)}
        />
      )}
    </div>
  );
}
