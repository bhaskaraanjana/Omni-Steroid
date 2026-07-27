/**
 * State-coverage tests for the live meeting screen: idle with an offline
 * engine (fail-closed start), live layout with correctly-sided Me/Them
 * lines, the empty listening state, the exact lag readout, device notices,
 * notepad typing into the store, and the stopped/error end states.
 */
import { afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { LiveMeetingScreen } from "./live-meeting-screen";
import { engineStatusStore, INITIAL_ENGINE_STATUS } from "../lib/engine-status-store";
import {
  applyAnswersHit,
  INITIAL_LIVE_ANSWERS_STATE,
  liveAnswersStore,
} from "../lib/live-answers-store";
import { INITIAL_NOTEPAD_STATE, notepadStore } from "../lib/notepad-store";
import {
  applyCaptureDeviceChanged,
  applyTranscriptFinal,
  INITIAL_TRANSCRIPT_STATE,
  transcriptStore,
} from "../lib/transcript-store";
import { installJsdomMatchMediaShim } from "../test-support/install-jsdom-match-media-shim";

beforeAll(installJsdomMatchMediaShim);

beforeEach(() => {
  transcriptStore.setState(INITIAL_TRANSCRIPT_STATE, true);
  engineStatusStore.setState(INITIAL_ENGINE_STATUS, true);
  notepadStore.setState(INITIAL_NOTEPAD_STATE, true);
  liveAnswersStore.setState(INITIAL_LIVE_ANSWERS_STATE, true);
});

afterEach(cleanup);

function goLive() {
  transcriptStore.setState({
    captureStatus: "live",
    meetingId: "m1",
    captureStartedAtMs: Date.now(),
  });
}

describe("idle (pre-capture) state", () => {
  it("FAIL CLOSED: engine offline -> Start capture disabled with honest copy", () => {
    render(<LiveMeetingScreen />);
    const start = screen.getByRole("button", { name: "Start capture" });
    expect((start as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/The engine is offline/)).toBeTruthy();
  });

  it("engine connected -> Start capture is enabled", () => {
    engineStatusStore.setState({ status: "connected", sttReady: true });
    render(<LiveMeetingScreen />);
    const start = screen.getByRole("button", { name: "Start capture" });
    expect((start as HTMLButtonElement).disabled).toBe(false);
  });

  it("engine connected but STT not ready -> Start disabled with loading copy", () => {
    engineStatusStore.setState({ status: "connected", sttReady: false });
    render(<LiveMeetingScreen />);
    const start = screen.getByRole("button", { name: "Loading speech models…" });
    expect((start as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/Speech models are still loading/)).toBeTruthy();
  });
});

describe("live state", () => {
  it("EMPTY transcript: shows the listening line, no bubbles", () => {
    goLive();
    render(<LiveMeetingScreen />);
    expect(screen.getByText("Listening. Words appear here as they are spoken.")).toBeTruthy();
    expect(screen.getByText("lag — ms")).toBeTruthy(); // no lag until a final
  });

  it("POPULATED: Them lines are bubbled left, Me lines right, in spoken order", () => {
    goLive();
    act(() => {
      applyTranscriptFinal(transcriptStore, {
        stream: "me", text: "We can do July.", t_start: 8, t_end: 9.5, seq: 0,
        segment_id: "me-0", lag_ms: 180,
      });
      applyTranscriptFinal(transcriptStore, {
        stream: "them", text: "When can you start?", t_start: 4, t_end: 6, seq: 0,
        segment_id: "them-0", lag_ms: 240,
      });
    });
    render(<LiveMeetingScreen />);
    const them = screen.getByText("When can you start?");
    const me = screen.getByText("We can do July.");
    expect(them.closest("[data-stream]")?.getAttribute("data-stream")).toBe("them");
    expect(me.closest("[data-stream]")?.getAttribute("data-stream")).toBe("me");
    // Spoken order regardless of arrival order: them (4s) precedes me (8s).
    const lines = [...document.querySelectorAll("[data-stream]")];
    expect(lines.map((l) => l.getAttribute("data-stream"))).toEqual(["them", "me"]);
    // Lag readout is the NEWEST final's exact value (them-0 arrived last).
    expect(screen.getByText("lag 240 ms")).toBeTruthy();
  });

  it("device-change notice renders honestly with the measured recovery time", () => {
    goLive();
    act(() => {
      applyCaptureDeviceChanged(transcriptStore, { device_name: "Headset", recovered_ms: 84.6 });
    });
    render(<LiveMeetingScreen />);
    expect(screen.getByText("audio moved to Headset · recovered in 85 ms")).toBeTruthy();
  });

  it("notepad typing lands in the store buffer verbatim", () => {
    goLive();
    render(<LiveMeetingScreen />);
    fireEvent.change(screen.getByRole("textbox", { name: "Notepad" }), {
      target: { value: "- ask about pricing\n- July start" },
    });
    expect(notepadStore.getState().text).toBe("- ask about pricing\n- July start");
  });

  it("the notes drawer is a REAL toggle: it folds away the notepad and unfolds it", async () => {
    goLive();
    render(<LiveMeetingScreen />);
    // Notes default OPEN (primary writing surface): the textbox is present.
    const toggle = screen.getByRole("button", { name: /Live meeting/ });
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByRole("textbox", { name: "Notepad" })).toBeTruthy();
    // Collapse actually removes the notepad — not a decorative chevron.
    await act(async () => {
      fireEvent.click(toggle);
    });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    await waitFor(() =>
      expect(screen.queryByRole("textbox", { name: "Notepad" })).toBeNull(),
    );
    // Expand restores it, verbatim buffer intact behind the store.
    await act(async () => {
      fireEvent.click(toggle);
    });
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByRole("textbox", { name: "Notepad" })).toBeTruthy();
  });

  it("Stop capture over a dead socket fails closed with the offline message", () => {
    goLive();
    render(<LiveMeetingScreen />);
    act(() => {
      fireEvent.click(screen.getByRole("button", { name: "Stop capture" }));
    });
    // No open socket in jsdom -> the command layer refuses and says so.
    expect(transcriptStore.getState().errorMessage).not.toBeNull();
    expect(transcriptStore.getState().captureStatus).toBe("live"); // no phantom stop
  });

  it("answers panel appears only after an answers.hit event lands in the store", () => {
    goLive();
    render(<LiveMeetingScreen />);
    expect(screen.queryByLabelText("Live answer")).toBeNull(); // honest idle
    act(() => {
      // Real event shape (engine answers.hit payload — M3 live tier).
      applyAnswersHit(liveAnswersStore, {
        question: "What did we quote them last year?",
        asked_by: "them",
        spotted_to_hit_ms: 740,
        hits: [
          {
            note_path: "clients/northwind.md",
            line_start: 42,
            line_end: 58,
            heading_path: "Renewal",
            snippet: "Quoted $71,500 multi-tenant last year.",
            score: 0.031,
          },
        ],
      });
    });
    expect(screen.getByLabelText("Live answer")).toBeTruthy();
    expect(screen.getByText("“What did we quote them last year?”")).toBeTruthy();
    expect(screen.getByText("Quoted $71,500 multi-tenant last year.")).toBeTruthy();
    // Exact citation target + the measured spotted->hit span, verbatim.
    expect(
      screen.getByText(/clients\/northwind\.md · L42–58 · 740 ms/),
    ).toBeTruthy();
    // Collapse is real: panel becomes the pill, expand restores it.
    fireEvent.click(screen.getByRole("button", { name: "Collapse" }));
    expect(screen.queryByLabelText("Live answer")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /1 answer · expand/ }));
    expect(screen.getByLabelText("Live answer")).toBeTruthy();
  });
});

describe("end states", () => {
  it("STOPPED: honest saved-on-device copy and a fresh start button", () => {
    transcriptStore.setState({ captureStatus: "stopped", meetingId: "m1" });
    render(<LiveMeetingScreen />);
    expect(screen.getByText("Capture stopped")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Start capture" })).toBeTruthy();
  });

  it("ERROR: names the failure and keeps the honest error message visible", () => {
    transcriptStore.setState({
      captureStatus: "error",
      meetingId: "m1",
      errorMessage: "Capture stopped because of an engine error.",
    });
    render(<LiveMeetingScreen />);
    expect(screen.getByText("Capture ended with an error")).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toBe(
      "Capture stopped because of an engine error.",
    );
  });
});
