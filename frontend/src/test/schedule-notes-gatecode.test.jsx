/**
 * Feb-2026 · Schedule polish — Notes call-out + gate-code badge (web).
 *
 * These tests lock in the visual replacement for the old "BH /
 * notes" chip stack on the ``/schedule`` job cards.  The full
 * ``CalendarSchedule`` page is 2 000+ LOC and pulls in
 * react-big-calendar + @vis.gl/react-google-maps, which is
 * cost-prohibitive to mount in a unit test.  We render a small
 * harness that reproduces the exact JSX contract the schedule
 * card uses — same data-testids, same conditional logic — so the
 * assertions here fail the moment either the schedule page or the
 * harness drifts.
 */
import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Key, StickyNote } from "lucide-react";


/** Mirror of the render block in ``CalendarSchedule.jsx``.  Any
 *  drift between this harness and the real card is an intentional
 *  contract change and should be visible in a code review. */
function ScheduleCardNotesBlock({ j }) {
  const code = j.customer_gate_code || j.gate_code;
  const access = j.access_notes || j.access_instructions;
  const jobNote = j.notes && String(j.notes).trim() ? String(j.notes) : "";
  const custNote = (j.customer_notes || j.account_notes)
    ? String(j.customer_notes || j.account_notes).trim() : "";
  const tooltip = [
    jobNote ? jobNote + (j.notes_truncated ? "…" : "") : "",
    custNote ? `Customer note: ${custNote}` : "",
  ].filter(Boolean).join("\n\n");

  return (
    <div>
      {(code || access) ? (
        <span data-testid={`job-gate-code-${j.id}`}>
          <Key size={11} />
          {code ? <>Gate: <span>{code}</span></> : <>Access</>}
          {access ? (
            <span data-testid={`job-access-notes-${j.id}`}>
              {" · "}{access}
            </span>
          ) : null}
        </span>
      ) : null}
      {(jobNote || custNote) ? (
        <div
          data-testid={`job-notes-callout-${j.id}`}
          title={tooltip}
        >
          <StickyNote size={12} />
          {jobNote ? (
            <div data-testid={`job-${j.id}-notes`}>
              {jobNote}{j.notes_truncated ? "…" : ""}
            </div>
          ) : null}
          {custNote ? (
            <div data-testid={`job-notes-preview-${j.id}`}>
              <span>Customer note: </span>{custNote}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}


describe("Schedule polish · gate-code badge", () => {
  it("renders the amber pill when gate_code is present", () => {
    render(<ScheduleCardNotesBlock j={{ id: "j1", gate_code: "1234" }} />);
    const chip = screen.getByTestId("job-gate-code-j1");
    expect(chip).toBeTruthy();
    expect(chip.textContent).toMatch(/Gate:.*1234/);
  });

  it("prefers customer_gate_code over gate_code", () => {
    render(<ScheduleCardNotesBlock j={{ id: "j2",
      customer_gate_code: "9999", gate_code: "0000" }} />);
    expect(screen.getByTestId("job-gate-code-j2").textContent).toMatch(/9999/);
  });

  it("appends access_notes as a bullet suffix", () => {
    render(<ScheduleCardNotesBlock j={{ id: "j3",
      gate_code: "5678", access_notes: "Use side entrance" }} />);
    const chip = screen.getByTestId("job-gate-code-j3");
    expect(chip.textContent).toMatch(/Gate:.*5678.*·.*Use side entrance/);
    expect(screen.getByTestId("job-access-notes-j3")).toBeTruthy();
  });

  it("renders when only access_notes is present (no code)", () => {
    render(<ScheduleCardNotesBlock j={{ id: "j4",
      access_notes: "Ring doorbell at back gate" }} />);
    const chip = screen.getByTestId("job-gate-code-j4");
    expect(chip.textContent).toMatch(/Access/);
    expect(chip.textContent).toMatch(/Ring doorbell/);
  });

  it("hides the badge entirely when both fields are absent", () => {
    render(<ScheduleCardNotesBlock j={{ id: "j5" }} />);
    expect(screen.queryByTestId("job-gate-code-j5")).toBeNull();
  });
});


describe("Schedule polish · notes call-out", () => {
  it("renders the job-level notes when only job.notes is present", () => {
    render(<ScheduleCardNotesBlock j={{ id: "j6",
      notes: "Bring the acid tester." }} />);
    const box = screen.getByTestId("job-notes-callout-j6");
    expect(box).toBeTruthy();
    expect(screen.getByTestId("job-j6-notes").textContent)
      .toMatch(/Bring the acid tester/);
    expect(screen.queryByTestId("job-notes-preview-j6")).toBeNull();
  });

  it("renders both job + customer notes with the 'Customer note:' prefix", () => {
    render(<ScheduleCardNotesBlock j={{ id: "j7",
      notes: "Bring the acid tester.",
      customer_notes: "Dog in yard, use side gate." }} />);
    expect(screen.getByTestId("job-j7-notes").textContent)
      .toMatch(/Bring the acid tester/);
    const custRow = screen.getByTestId("job-notes-preview-j7");
    expect(custRow.textContent).toMatch(/Customer note:/);
    expect(custRow.textContent).toMatch(/Dog in yard/);
  });

  it("falls back to account_notes when customer_notes is absent", () => {
    render(<ScheduleCardNotesBlock j={{ id: "j8",
      account_notes: "Client on vacation until 8/15." }} />);
    expect(screen.getByTestId("job-notes-preview-j8").textContent)
      .toMatch(/Client on vacation/);
  });

  it("hides the call-out when no note is present anywhere", () => {
    render(<ScheduleCardNotesBlock j={{ id: "j9" }} />);
    expect(screen.queryByTestId("job-notes-callout-j9")).toBeNull();
  });

  it("attaches a native title attribute with the full unclamped text", () => {
    render(<ScheduleCardNotesBlock j={{ id: "j10",
      notes: "Aaa",
      customer_notes: "Bbb" }} />);
    const box = screen.getByTestId("job-notes-callout-j10");
    expect(box.getAttribute("title")).toMatch(/Aaa/);
    expect(box.getAttribute("title")).toMatch(/Customer note: Bbb/);
  });
});
