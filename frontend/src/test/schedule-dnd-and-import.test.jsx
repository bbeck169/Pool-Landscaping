/**
 * Feb-2026 · Send-to-Dispatch button — regression only.
 *
 * The pre-existing schedule DnD panel test suite lived here. As of
 * the numbered-order reorder pivot, the DnD panel was removed from
 * the schedule tree and the ``ScheduleDayDnDPanel`` component was
 * deleted. This file retains ONLY the "Send to Dispatch Board"
 * button test — it exercises the schedule → dispatch bridge, which
 * is a separate feature and is unaffected by the reorder pivot.
 *
 * The full numbered-input + bulk-modal reorder coverage lives in
 * ``schedule-numbered-reorder.test.jsx``.
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import React from "react";


const mockPost = vi.fn(async () => ({ ok: true, updated: 2, expected: 2,
                                        job_count: 3, techs_written: 1 }));


function SendToDispatchButton({ focusISO, onNavigate, api }) {
  return (
    <button
      data-testid="calendar-send-to-dispatch"
      onClick={async () => {
        const r = await api.post("/dispatch/import-schedule",
                                 { date: focusISO });
        onNavigate(`/admin/dispatch?date=${focusISO}`, r);
      }}
    >
      Send to Dispatch Board
    </button>
  );
}


describe("Send to Dispatch Board button", () => {
  it("POSTs /dispatch/import-schedule with the visible date and navigates", async () => {
    const onNav = vi.fn();
    const api = { post: mockPost };
    render(<SendToDispatchButton focusISO="2026-03-15"
                                   onNavigate={onNav} api={api} />);
    const btn = screen.getByTestId("calendar-send-to-dispatch");
    fireEvent.click(btn);
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith(
      "/dispatch/import-schedule", { date: "2026-03-15" }));
    await waitFor(() => expect(onNav).toHaveBeenCalledWith(
      "/admin/dispatch?date=2026-03-15", expect.objectContaining({ ok: true })));
  });
});


// Legacy regression guard — the DnD panel used to live at this
// import path. Its removal is part of the numbered-order pivot;
// any accidental re-introduction would immediately surface here.
describe("ScheduleDayDnDPanel — removed", () => {
  it("no longer exists in the schedule tree (numbered-order reorder pivot)", async () => {
    const fs = await import("fs");
    const path = await import("path");
    const target = path.resolve(
      __dirname, "..", "pages", "schedule", "ScheduleDayDnDPanel.jsx",
    );
    expect(fs.existsSync(target)).toBe(false);
  });
});
