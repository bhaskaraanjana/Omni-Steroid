/**
 * Library detail pane — Meetily parity tabs: Chat, Tools (copy, search/replace, md export).
 */
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { FinalizeOutcome, MeetingDetail } from "../lib/meetings-live-repository";
import {
  INITIAL_MEETINGS_DETAIL_STATE,
  meetingsDetailStore,
  openMeetingDetail,
} from "../lib/meetings-detail-store";
import { installJsdomMatchMediaShim } from "../test-support/install-jsdom-match-media-shim";
import { LibraryMeetingDetailPane } from "./library-meeting-detail-pane";

vi.mock("../lib/copy-to-clipboard", () => ({
  copyTextToClipboard: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("../lib/meeting-export", () => ({
  downloadMeetingExport: vi.fn().mockResolvedValue({
    content: "# Full meeting",
    encoding: "text",
    mime: "text/markdown",
    filename: "Vendor sync.md",
  }),
  triggerBrowserDownload: vi.fn(),
}));

vi.mock("../lib/meeting-text-replace-repository", () => ({
  replaceMeetingText: vi.fn().mockResolvedValue({ transcriptSegments: 1, enhancedNotes: 0 }),
}));

vi.mock("../lib/meeting-chat-repository", () => ({
  askAboutMeeting: vi.fn().mockResolvedValue({
    headline: "Answer",
    prose: [{ text: "Friday." }],
    citations: [],
    latency: { retrievalMs: 0, synthesisMs: 1, totalMs: 1 },
  }),
}));

vi.mock("../lib/meetings-live-repository", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/meetings-live-repository")>();
  return {
    ...actual,
    retranscribeMeeting: vi.fn(),
    deleteMeeting: vi.fn().mockResolvedValue(undefined),
    updateTranscriptSegment: vi.fn().mockResolvedValue(undefined),
  };
});

import { copyTextToClipboard } from "../lib/copy-to-clipboard";
import { replaceMeetingText } from "../lib/meeting-text-replace-repository";
import { askAboutMeeting } from "../lib/meeting-chat-repository";
import { downloadMeetingExport } from "../lib/meeting-export";
import { deleteMeeting, retranscribeMeeting } from "../lib/meetings-live-repository";

beforeAll(installJsdomMatchMediaShim);

beforeEach(() => {
  meetingsDetailStore.setState(INITIAL_MEETINGS_DETAIL_STATE, true);
  vi.clearAllMocks();
});

afterEach(cleanup);

const DETAIL: MeetingDetail = {
  id: "m-1",
  title: "Vendor sync",
  startIso: "2026-07-06T10:00:00+00:00",
  endedIso: "2026-07-06T10:30:00+00:00",
  durationMin: 30,
  finalized: true,
  notePath: "Meetings/2026-07-06 Vendor sync.md",
  notesText: "notes",
  enhancedNotesMd: "## Summary\nRenewal agreed.",
  extraction: null,
  hasKeptAudio: true,
  transcript: [
    { segmentId: "s1", stream: "them", speakerLabel: "Speaker 1", text: "hello", tStart: 0, tEnd: 1 },
  ],
};

const OUTCOME: FinalizeOutcome = {
  notePath: "Meetings/x.md",
  enhanceOk: true,
  extractionOk: true,
  warnings: [],
};

function renderReady() {
  openMeetingDetail(meetingsDetailStore, "m-1");
  return render(
    <LibraryMeetingDetailPane
      meetingId="m-1"
      loadDetail={() => Promise.resolve(DETAIL)}
      finalizeMeeting={() => Promise.resolve(OUTCOME)}
      onFinalized={() => undefined}
    />,
  );
}

describe("library detail Meetily parity tabs", () => {
  it("shows Summary, Transcript, Chat, and Export tabs", async () => {
    await act(async () => {
      renderReady();
    });
    expect(screen.getByRole("tab", { name: "Summary" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Transcript" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Chat" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Export" })).toBeTruthy();
  });

  it("Chat tab asks about this meeting", async () => {
    await act(async () => {
      renderReady();
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("tab", { name: "Chat" }));
    });
    const input = screen.getByLabelText("Ask about this meeting");
    fireEvent.change(input, { target: { value: "What was agreed?" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Ask" }));
    });
    expect(askAboutMeeting).toHaveBeenCalledWith("m-1", "What was agreed?");
    expect(await screen.findByText("Friday.")).toBeTruthy();
  });

  it("Export tab copies transcript and runs search/replace", async () => {
    await act(async () => {
      renderReady();
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("tab", { name: "Export" }));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Copy transcript" }));
    });
    expect(copyTextToClipboard).toHaveBeenCalledWith("Speaker 1: hello");

    fireEvent.change(screen.getByLabelText("Find"), { target: { value: "hello" } });
    fireEvent.change(screen.getByLabelText("Replace with"), { target: { value: "hi" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Replace all" }));
    });
    expect(replaceMeetingText).toHaveBeenCalledWith("m-1", "hello", "hi", "both");
  });

  it("Export tab offers MD download", async () => {
    await act(async () => {
      renderReady();
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("tab", { name: "Export" }));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Download MD" }));
    });
    expect(downloadMeetingExport).toHaveBeenCalledWith("m-1", "md", "Vendor sync");
  });

  it("hides Retranscribe when the meeting has no kept audio", async () => {
    const noAudio: MeetingDetail = { ...DETAIL, hasKeptAudio: false };
    openMeetingDetail(meetingsDetailStore, "m-1");
    await act(async () => {
      render(
        <LibraryMeetingDetailPane
          meetingId="m-1"
          loadDetail={() => Promise.resolve(noAudio)}
          finalizeMeeting={() => Promise.resolve(OUTCOME)}
          onFinalized={() => undefined}
        />,
      );
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("tab", { name: "Export" }));
    });
    expect(screen.queryByRole("button", { name: "Retranscribe" })).toBeNull();
  });

  it("surfaces download and retranscribe failures honestly", async () => {
    vi.mocked(downloadMeetingExport).mockRejectedValueOnce(new Error("export offline"));
    vi.mocked(retranscribeMeeting).mockRejectedValueOnce(new Error("no kept audio"));

    await act(async () => {
      renderReady();
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("tab", { name: "Export" }));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Download SRT" }));
    });
    expect(await screen.findByText("export offline")).toBeTruthy();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Retranscribe" }));
    });
    expect(await screen.findByText("no kept audio")).toBeTruthy();
  });

  it("Delete meeting confirms then closes and notifies parent", async () => {
    const onDeleted = vi.fn();
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    openMeetingDetail(meetingsDetailStore, "m-1");
    await act(async () => {
      render(
        <LibraryMeetingDetailPane
          meetingId="m-1"
          loadDetail={() => Promise.resolve(DETAIL)}
          finalizeMeeting={() => Promise.resolve(OUTCOME)}
          onFinalized={() => undefined}
          onDeleted={onDeleted}
        />,
      );
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("tab", { name: "Export" }));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Delete meeting" }));
    });
    expect(confirmSpy).toHaveBeenCalled();
    await act(async () => {
      await Promise.resolve();
    });
    expect(deleteMeeting).toHaveBeenCalledWith("m-1");
    expect(onDeleted).toHaveBeenCalled();
    expect(meetingsDetailStore.getState().selectedId).toBeNull();
    confirmSpy.mockRestore();
  });
});
