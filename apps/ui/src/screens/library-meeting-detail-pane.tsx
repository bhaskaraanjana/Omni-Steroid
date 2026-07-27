/**
 * Meeting detail pane — opened from a Library row, rendered inside the
 * Library screen as a right-hand panel.
 *
 * Shows the three layers of one captured meeting: Enhanced Notes (engine
 * markdown through the XSS-safe renderer), My Notes (the user's rough notes,
 * verbatim, plain text), and the transcript in a collapsed disclosure. An
 * ended-but-unfinalized meeting gets a working "Enhance now" action that
 * sends meeting.finalize with the notepad buffer (when it belongs to this
 * meeting). States: loading shimmer, error + retry, ready — none faked.
 */
import { useCallback, useEffect, useState } from "react";
import { ApprovalRack } from "../components/approval/approval-rack";
import { MeetingBoardPanel } from "../components/live/meeting-board-panel";
import { MeetingChatPanel } from "../components/library/meeting-chat-panel";
import { MeetingSearchReplacePanel } from "../components/library/meeting-search-replace-panel";
import { OmniButton } from "../components/button";
import { SectionLabel } from "../components/section-label";
import { SkeletonShimmer } from "../components/skeleton-shimmer";
import { formatClockShort, formatDayLabel, formatDurationMin } from "../lib/format-quantities";
import { copyTextToClipboard } from "../lib/copy-to-clipboard";
import { downloadMeetingExport, triggerBrowserDownload } from "../lib/meeting-export";
import { deleteMeeting, retranscribeMeeting } from "../lib/meetings-live-repository";
import type { FinalizeOutcome, MeetingDetail } from "../lib/meetings-live-repository";
import { updateTranscriptSegment } from "../lib/meetings-live-repository";
import { SafeMarkdown } from "../lib/meetings-safe-markdown";
import {
  closeMeetingDetail,
  loadMeetingDetail,
  meetingsDetailStore,
  runMeetingFinalize,
  useMeetingsDetail,
} from "../lib/meetings-detail-store";
import { useNotepad } from "../lib/notepad-store";

export type DetailLoader = (meetingId: string) => Promise<MeetingDetail>;
export type MeetingFinalizer = (
  meetingId: string,
  notepadText: string,
) => Promise<FinalizeOutcome>;

type DetailTab = "summary" | "transcript" | "chat" | "tools";

function DetailTabs({
  tab,
  onTab,
}: {
  readonly tab: DetailTab;
  readonly onTab: (tab: DetailTab) => void;
}) {
  const tabs: Array<{ id: DetailTab; label: string }> = [
    { id: "summary", label: "Summary" },
    { id: "transcript", label: "Transcript" },
    { id: "chat", label: "Chat" },
    // Internal value stays 'tools' to avoid churn; the label is the user-facing
    // "Export" (the tab is copy, search/replace, and file downloads).
    { id: "tools", label: "Export" },
  ];
  return (
    <div
      role="tablist"
      aria-label="Meeting sections"
      className="flex flex-wrap gap-[var(--space-2)] border-b border-[var(--grey-200)] pb-[var(--space-3)]"
    >
      {tabs.map((item) => {
        const selected = tab === item.id;
        return (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={selected}
            className={
              "inline-flex cursor-pointer items-center border font-[family-name:var(--font-body)] outline-none transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--focus-ring)] focus-visible:outline-offset-2 " +
              (selected
                ? "bg-[var(--accent-muted)] border-[var(--accent-border)] text-[var(--accent)]"
                : "bg-[var(--surface)] border-[var(--border-strong)] text-[var(--ink-secondary)] hover:border-[var(--grey-600)] hover:text-[var(--ink)]")
            }
            style={{
              borderRadius: "var(--radius-pill)",
              padding: "6px 12px",
              fontSize: 13,
              lineHeight: 1.4,
            }}
            onClick={() => onTab(item.id)}
          >
            {item.label}
          </button>
        );
      })}
    </div>
  );
}

function PaneSection({ label, children }: { readonly label: string; readonly children: React.ReactNode }) {
  return (
    <section aria-label={label} className="flex flex-col gap-[var(--space-2)]">
      <SectionLabel>{label}</SectionLabel>
      <div className="text-[var(--ink)]" style={{ fontSize: "var(--text-body-size)" }}>
        {children}
      </div>
    </section>
  );
}

export function LibraryMeetingDetailPane({
  meetingId,
  loadDetail,
  finalizeMeeting,
  onFinalized,
  onDeleted,
}: {
  readonly meetingId: string;
  readonly loadDetail: DetailLoader;
  readonly finalizeMeeting: MeetingFinalizer;
  /** Called after a successful finalize so the list can refresh. */
  readonly onFinalized: () => void;
  /** Called after a successful delete so the list can refresh. */
  readonly onDeleted?: () => void;
}) {
  const status = useMeetingsDetail((s) => s.status);
  const detail = useMeetingsDetail((s) => s.detail);
  const errorMessage = useMeetingsDetail((s) => s.errorMessage);
  const finalizing = useMeetingsDetail((s) => s.finalizing);
  const finalizeMessage = useMeetingsDetail((s) => s.finalizeMessage);
  const notepadMeetingId = useNotepad((s) => s.meetingId);
  const notepadText = useNotepad((s) => s.text);
  const [editingSegmentId, setEditingSegmentId] = useState<string | null>(null);
  const [editText, setEditText] = useState("");
  const [tab, setTab] = useState<DetailTab>("summary");
  const [copyMessage, setCopyMessage] = useState<string | null>(null);

  const load = useCallback(
    () => void loadMeetingDetail(meetingsDetailStore, loadDetail, meetingId),
    [loadDetail, meetingId],
  );
  useEffect(load, [load]);

  const canFinalize =
    detail !== null && !detail.finalized && detail.endedIso !== null && !finalizing;
  // The notepad buffer only belongs to this meeting if the ids match —
  // never send another meeting's notes (fidelity + information boundary).
  const notepadForThisMeeting = notepadMeetingId === meetingId ? notepadText : "";

  return (
    <aside
      aria-label="Meeting detail"
      className="flex h-full flex-col gap-[var(--space-5)] overflow-y-auto border-l border-[var(--grey-200)]"
      style={{ width: 420, flexShrink: 0, padding: "48px 32px" }}
    >
      <header className="flex items-start justify-between gap-[var(--space-3)]">
        <div className="flex min-w-0 flex-col gap-[var(--space-1)]">
          <h2
            className="m-0 font-[family-name:var(--font-display)] font-semibold text-[var(--ink)]"
            style={{ fontSize: "var(--text-section-size)", letterSpacing: "var(--text-section-ls)" }}
          >
            {detail?.title ?? "Meeting"}
          </h2>
          {detail !== null && (
            <span
              className="font-[family-name:var(--font-mono)] text-[var(--ink-secondary)]"
              style={{ fontSize: "var(--text-meta-size)" }}
            >
              {formatDayLabel(detail.startIso)} · {formatClockShort(detail.startIso)}
              {detail.endedIso !== null && ` · ${formatDurationMin(detail.durationMin)}`}
            </span>
          )}
        </div>
        <OmniButton
          variant="secondary"
          small
          aria-label="Close meeting detail"
          onClick={() => closeMeetingDetail(meetingsDetailStore)}
        >
          Close
        </OmniButton>
      </header>

      {status === "loading" && <SkeletonShimmer lines={6} />}

      {status === "error" && (
        <div className="flex flex-col items-start gap-[var(--space-3)]">
          <p className="m-0 text-[var(--ink)]" style={{ fontSize: "var(--text-body-size)" }}>
            Could not load this meeting.
          </p>
          <p className="m-0 text-[var(--grey-600)]" style={{ fontSize: 13 }}>
            {errorMessage}
          </p>
          <OmniButton variant="secondary" onClick={load}>
            Retry loading
          </OmniButton>
        </div>
      )}

      {status === "ready" && detail !== null && (
        <>
          <DetailTabs tab={tab} onTab={setTab} />
          {copyMessage !== null && (
            <p role="status" className="m-0 text-[var(--grey-600)]" style={{ fontSize: 12 }}>
              {copyMessage}
            </p>
          )}

          {tab === "summary" && (
            <>
          <PaneSection label="Enhanced Notes">
            {detail.enhancedNotesMd.length > 0 ? (
              <SafeMarkdown markdown={detail.enhancedNotesMd} />
            ) : (
              <p className="m-0 text-[var(--grey-600)]">
                {detail.finalized
                  ? "Enhancement was unavailable for this meeting — your notes and transcript below are intact."
                  : "Not enhanced yet."}
              </p>
            )}
            {canFinalize && (
              <div className="mt-[var(--space-3)]">
                <OmniButton
                  variant="primary"
                  small
                  onClick={() =>
                    void runMeetingFinalize(
                      meetingsDetailStore,
                      finalizeMeeting,
                      loadDetail,
                      meetingId,
                      notepadForThisMeeting,
                      onFinalized,
                    )
                  }
                >
                  Enhance now
                </OmniButton>
              </div>
            )}
            {finalizing && (
              <p className="m-0 mt-[var(--space-2)] text-[var(--grey-600)]" style={{ fontSize: 13 }}>
                Enhancing — fusing your notes with the transcript…
              </p>
            )}
            {finalizeMessage !== null && (
              <p role="status" className="m-0 mt-[var(--space-2)] text-[var(--grey-600)]" style={{ fontSize: 13 }}>
                {finalizeMessage}
              </p>
            )}
          </PaneSection>

          <PaneSection label="Suggested Actions">
            {/* The M4 approval rack, scoped to this meeting's extraction
                cards. All states are the rack's own honest ones (loading /
                empty / engine offline / the cards themselves). */}
            <ApprovalRack meetingId={meetingId} />
          </PaneSection>

          {detail.extraction !== null && (
            <MeetingBoardPanel
              extraction={{
                actions: detail.extraction.actions.map((a) => ({
                  title: a.title,
                  ...(a.owner !== undefined ? { owner: a.owner } : {}),
                })),
                commitments: detail.extraction.commitments,
                openQuestions: detail.extraction.openQuestions,
                contacts: [],
              }}
            />
          )}

          <PaneSection label="My Notes">
            {detail.notesText.length > 0 || notepadForThisMeeting.length > 0 ? (
              <pre
                className="m-0 whitespace-pre-wrap font-[family-name:var(--font-body,inherit)]"
                style={{ fontSize: "var(--text-body-size)", lineHeight: "var(--text-body-lh)" }}
              >
                {detail.notesText.length > 0 ? detail.notesText : notepadForThisMeeting}
              </pre>
            ) : (
              <p className="m-0 text-[var(--grey-600)]">No notes were typed for this meeting.</p>
            )}
          </PaneSection>

          <PaneSection label="Transcript">
            {detail.transcript.length === 0 ? (
              <div className="flex flex-col items-start gap-[var(--space-2)]">
                <p className="m-0 text-[var(--grey-600)]">No transcript was captured.</p>
                <p className="m-0 text-[var(--grey-600)]" style={{ fontSize: 13 }}>
                  Common causes: silence auto-stop fired before anyone spoke, your mic was
                  muted, or system audio was on headphones (loopback hears speakers, not
                  headset audio).
                </p>
              </div>
            ) : (
              <div className="flex flex-col items-start gap-[var(--space-2)]">
                <p className="m-0 text-[var(--ink)]">
                  {detail.transcript.length} segment{detail.transcript.length === 1 ? "" : "s"}{" "}
                  captured.
                </p>
                <OmniButton variant="secondary" small onClick={() => setTab("transcript")}>
                  Open transcript
                </OmniButton>
              </div>
            )}
          </PaneSection>
            </>
          )}

          {tab === "transcript" && (
          <PaneSection label="Transcript">
            {detail.transcript.length === 0 ? (
              <div className="flex flex-col gap-[var(--space-2)]">
                <p className="m-0 text-[var(--grey-600)]">No transcript was captured.</p>
                <p className="m-0 text-[var(--grey-600)]" style={{ fontSize: 13 }}>
                  If the meeting ended on its own, check Settings → Automation → Silence
                  auto-stop (set to Off while testing). Headphones also hide “them” audio from
                  loopback capture.
                </p>
              </div>
            ) : (
              <ul className="m-0 flex list-none flex-col gap-[var(--space-2)] p-0">
                  {detail.transcript.map((line) => (
                    <li key={line.segmentId} style={{ fontSize: 13, lineHeight: "1.5" }}>
                      <span className="font-[family-name:var(--font-mono)] text-[var(--ink-secondary)]">
                        {line.speakerLabel}:
                      </span>{" "}
                      {editingSegmentId === line.segmentId ? (
                        <form
                          className="inline"
                          onSubmit={(e) => {
                            e.preventDefault();
                            void updateTranscriptSegment(meetingId, line.segmentId, editText).then(
                              () => {
                                setEditingSegmentId(null);
                                setCopyMessage(null);
                                load();
                              },
                              (err: unknown) =>
                                setCopyMessage(
                                  err instanceof Error
                                    ? err.message
                                    : "Could not save transcript segment.",
                                ),
                            );
                          }}
                        >
                          <input
                            aria-label="Edit transcript segment"
                            value={editText}
                            onChange={(e) => setEditText(e.target.value)}
                            className="w-full border border-[var(--grey-200)] px-2 py-1"
                            style={{ fontSize: 13 }}
                          />
                          <OmniButton variant="secondary" small type="submit">
                            Save
                          </OmniButton>
                        </form>
                      ) : (
                        <>
                          <span className="text-[var(--ink)]">{line.text}</span>
                          <button
                            type="button"
                            className="ml-2 cursor-pointer border-none bg-transparent text-[var(--grey-600)]"
                            style={{ fontSize: 11 }}
                            onClick={() => {
                              setEditingSegmentId(line.segmentId);
                              setEditText(line.text);
                            }}
                          >
                            Edit
                          </button>
                        </>
                      )}
                    </li>
                  ))}
              </ul>
            )}
          </PaneSection>
          )}

          {tab === "chat" && <MeetingChatPanel meetingId={meetingId} />}

          {tab === "tools" && (
            <>
              <PaneSection label="Copy">
                <div className="flex flex-wrap gap-2">
                  <OmniButton
                    variant="secondary"
                    small
                    onClick={() =>
                      void copyTextToClipboard(detail.enhancedNotesMd || "").then(
                        () => setCopyMessage("Enhanced notes copied."),
                        () => setCopyMessage("Could not copy."),
                      )
                    }
                  >
                    Copy summary
                  </OmniButton>
                  <OmniButton
                    variant="secondary"
                    small
                    onClick={() =>
                      void copyTextToClipboard(
                        detail.transcript.map((l) => `${l.speakerLabel}: ${l.text}`).join("\n"),
                      ).then(
                        () => setCopyMessage("Transcript copied."),
                        () => setCopyMessage("Could not copy."),
                      )
                    }
                  >
                    Copy transcript
                  </OmniButton>
                  <OmniButton
                    variant="secondary"
                    small
                    onClick={() =>
                      void downloadMeetingExport(meetingId, "md", detail.title).then(
                        (result) =>
                          void copyTextToClipboard(result.content).then(
                            () => setCopyMessage("Full meeting markdown copied."),
                            () => setCopyMessage("Could not copy."),
                          ),
                        (err: unknown) =>
                          setCopyMessage(
                            err instanceof Error ? err.message : "Could not export markdown.",
                          ),
                      )
                    }
                  >
                    Copy markdown
                  </OmniButton>
                </div>
              </PaneSection>
              <PaneSection label="Search & replace">
                <MeetingSearchReplacePanel meetingId={meetingId} onReplaced={load} />
              </PaneSection>
              <PaneSection label="Download files">
                <div className="flex flex-wrap gap-2">
                  {(["srt", "vtt", "txt", "md", "pdf", "docx"] as const).map((format) => (
                    <OmniButton
                      key={format}
                      variant="secondary"
                      small
                      onClick={() =>
                        void downloadMeetingExport(meetingId, format, detail.title).then(
                          (result) => {
                            triggerBrowserDownload(result);
                            setCopyMessage(`Downloaded ${format.toUpperCase()}.`);
                          },
                          (err: unknown) =>
                            setCopyMessage(
                              err instanceof Error
                                ? err.message
                                : `Could not download ${format.toUpperCase()}.`,
                            ),
                        )
                      }
                    >
                      Download {format.toUpperCase()}
                    </OmniButton>
                  ))}
                  {detail.hasKeptAudio ? (
                    <OmniButton
                      variant="secondary"
                      small
                      onClick={() =>
                        void retranscribeMeeting(meetingId).then(
                          () => {
                            setCopyMessage("Retranscription finished.");
                            load();
                          },
                          (err: unknown) =>
                            setCopyMessage(
                              err instanceof Error ? err.message : "Retranscribe failed.",
                            ),
                        )
                      }
                    >
                      Retranscribe
                    </OmniButton>
                  ) : null}
                </div>
              </PaneSection>
              <PaneSection label="Delete">
                <p
                  className="m-0 text-[var(--ink-secondary)]"
                  style={{ fontSize: "var(--text-meta-size)", marginBottom: 8 }}
                >
                  Removes this meeting from Library and deletes kept audio. Your vault note
                  is left in place.
                </p>
                <OmniButton
                  variant="secondary"
                  small
                  onClick={() => {
                    const ok = window.confirm(
                      "Delete this meeting from Library and wipe kept audio? Your vault note will be kept.",
                    );
                    if (!ok) return;
                    void deleteMeeting(meetingId).then(
                      () => {
                        closeMeetingDetail(meetingsDetailStore);
                        onDeleted?.();
                      },
                      (err: unknown) =>
                        setCopyMessage(
                          err instanceof Error ? err.message : "Delete failed.",
                        ),
                    );
                  }}
                >
                  Delete meeting
                </OmniButton>
              </PaneSection>
            </>
          )}
        </>
      )}
    </aside>
  );
}
