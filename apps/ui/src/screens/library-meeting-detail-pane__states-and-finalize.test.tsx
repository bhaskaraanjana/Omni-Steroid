/**
 * Detail pane states + the working "Enhance now" action: loading shimmer,
 * error with a real retry, ready with all three sections (enhanced notes,
 * verbatim My Notes, collapsed transcript), finalize wiring that sends THIS
 * meeting's notepad buffer only, and the honest partial-success message.
 */
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { FinalizeOutcome, MeetingDetail } from "../lib/meetings-live-repository";
import {
  INITIAL_MEETINGS_DETAIL_STATE,
  meetingsDetailStore,
  openMeetingDetail,
} from "../lib/meetings-detail-store";
import { INITIAL_NOTEPAD_STATE, notepadStore } from "../lib/notepad-store";
import { installJsdomMatchMediaShim } from "../test-support/install-jsdom-match-media-shim";
import { LibraryMeetingDetailPane } from "./library-meeting-detail-pane";

beforeAll(installJsdomMatchMediaShim);

beforeEach(() => {
  meetingsDetailStore.setState(INITIAL_MEETINGS_DETAIL_STATE, true);
  notepadStore.setState(INITIAL_NOTEPAD_STATE, true);
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
  notesText: "my raw notes\n  with exact   spacing",
  enhancedNotesMd: "## Summary\nRenewal agreed.",
  extraction: null,
  hasKeptAudio: true,
  transcript: [
      { segmentId: "s1", stream: "them", speakerLabel: "Speaker 1", text: "hello there", tStart: 0, tEnd: 1 },
      { segmentId: "s2", stream: "me", speakerLabel: "Alex", text: "hi", tStart: 1, tEnd: 2 },
  ],
};

const OUTCOME: FinalizeOutcome = {
  notePath: "Meetings/2026-07-06 Vendor sync.md",
  enhanceOk: true,
  extractionOk: true,
  warnings: [],
};

function renderPane(overrides?: {
  loadDetail?: (id: string) => Promise<MeetingDetail>;
  finalizeMeeting?: (id: string, notepad: string) => Promise<FinalizeOutcome>;
  onFinalized?: () => void;
}) {
  openMeetingDetail(meetingsDetailStore, "m-1");
  return render(
    <LibraryMeetingDetailPane
      meetingId="m-1"
      loadDetail={overrides?.loadDetail ?? (() => Promise.resolve(DETAIL))}
      finalizeMeeting={overrides?.finalizeMeeting ?? (() => Promise.resolve(OUTCOME))}
      onFinalized={overrides?.onFinalized ?? (() => undefined)}
    />,
  );
}

describe("states", () => {
  it("LOADING: shows the shimmer while the detail is in flight", () => {
    renderPane({ loadDetail: () => new Promise(() => undefined) });
    expect(screen.getByRole("status", { name: "Loading" })).toBeTruthy();
  });

  it("ERROR: shows the honest message and retry actually reloads", async () => {
    let attempts = 0;
    const loadDetail = vi.fn().mockImplementation(() => {
      attempts += 1;
      return attempts === 1
        ? Promise.reject(new Error("engine did not answer meeting.get in time"))
        : Promise.resolve(DETAIL);
    });
    await act(async () => {
      renderPane({ loadDetail });
    });
    expect(screen.getByText("Could not load this meeting.")).toBeTruthy();
    expect(screen.getByText(/did not answer meeting.get/)).toBeTruthy();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Retry loading" }));
    });
    expect(loadDetail).toHaveBeenCalledTimes(2);
    expect(screen.getByText("Vendor sync")).toBeTruthy();
  });

  it("READY: renders enhanced notes (markdown), verbatim My Notes, expanded transcript", async () => {
    let container: HTMLElement;
    await act(async () => {
      container = renderPane().container;
    });
    // Enhanced notes went through the markdown renderer (heading element).
    expect(screen.getByRole("heading", { name: "Summary" })).toBeTruthy();
    expect(screen.getByText("Renewal agreed.")).toBeTruthy();
    // My Notes: verbatim, whitespace preserved via <pre>.
    const pre = container!.querySelector("pre");
    expect(pre!.textContent).toBe("my raw notes\n  with exact   spacing");
    // Summary surfaces a transcript preview with a jump control.
    expect(screen.getByText(/2 segments captured/i)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Open transcript" })).toBeTruthy();
    // Transcript tab shows lines expanded (no collapsed disclosure).
    await act(async () => {
      fireEvent.click(screen.getByRole("tab", { name: "Transcript" }));
    });
    expect(container!.querySelector("details")).toBeNull();
    expect(screen.getByText("hello there")).toBeTruthy();
    // Finalized meeting: no Enhance-now button.
    expect(screen.queryByRole("button", { name: "Enhance now" })).toBeNull();
  });

  it("READY (unfinalized): honest 'not enhanced yet' plus a working action", async () => {
    const unfinalized = { ...DETAIL, finalized: false, enhancedNotesMd: "", notesText: "" };
    await act(async () => {
      renderPane({ loadDetail: () => Promise.resolve(unfinalized) });
    });
    expect(screen.getByText("Not enhanced yet.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Enhance now" })).toBeTruthy();
  });
});

describe("finalize wiring", () => {
  it("sends THIS meeting's notepad buffer verbatim and refreshes on success", async () => {
    notepadStore.setState({ meetingId: "m-1", text: "typed during the call\nline 2" });
    const unfinalized = { ...DETAIL, finalized: false, enhancedNotesMd: "" };
    const finalizeMeeting = vi.fn().mockResolvedValue(OUTCOME);
    const onFinalized = vi.fn();
    const loadDetail = vi
      .fn()
      .mockResolvedValueOnce(unfinalized) // initial open
      .mockResolvedValue(DETAIL); // reload after finalize
    await act(async () => {
      renderPane({ loadDetail, finalizeMeeting, onFinalized });
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Enhance now" }));
    });
    expect(finalizeMeeting).toHaveBeenCalledWith("m-1", "typed during the call\nline 2");
    expect(onFinalized).toHaveBeenCalledTimes(1); // the list refresh hook fired
    expect(loadDetail).toHaveBeenCalledTimes(2); // the pane re-fetched fresh regions
    expect(screen.getByText(/Enhanced notes saved to/)).toBeTruthy();
  });

  it("never sends ANOTHER meeting's notepad buffer", async () => {
    notepadStore.setState({ meetingId: "some-other-meeting", text: "private notes" });
    const unfinalized = { ...DETAIL, finalized: false, enhancedNotesMd: "" };
    const finalizeMeeting = vi.fn().mockResolvedValue(OUTCOME);
    await act(async () => {
      renderPane({ loadDetail: () => Promise.resolve(unfinalized), finalizeMeeting });
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Enhance now" }));
    });
    expect(finalizeMeeting).toHaveBeenCalledWith("m-1", ""); // information boundary
  });

  it("a refused finalize shows the engine's plain-voice reason, nothing fake", async () => {
    const unfinalized = { ...DETAIL, finalized: false, enhancedNotesMd: "" };
    const finalizeMeeting = vi
      .fn()
      .mockRejectedValue(new Error("meeting is already finalized"));
    await act(async () => {
      renderPane({ loadDetail: () => Promise.resolve(unfinalized), finalizeMeeting });
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Enhance now" }));
    });
    expect(screen.getByText("meeting is already finalized")).toBeTruthy();
  });

  it("partial success (enhance failed) is reported honestly", async () => {
    const unfinalized = { ...DETAIL, finalized: false, enhancedNotesMd: "" };
    const finalizeMeeting = vi.fn().mockResolvedValue({ ...OUTCOME, enhanceOk: false });
    await act(async () => {
      renderPane({ loadDetail: () => Promise.resolve(unfinalized), finalizeMeeting });
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Enhance now" }));
    });
    expect(screen.getByText(/enhancement was unavailable — your raw notes are safe/)).toBeTruthy();
  });
});
