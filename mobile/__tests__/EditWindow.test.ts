/**
 * Feb-2026 · Slice 6 — Mobile 24h edit-window helpers.
 *
 * Pure-function unit tests for
 * ``mobile/src/lib/editWindow.ts``. Same contract as the frontend
 * ``pages/jobs/JobEditPanel.jsx`` client-mirror and the backend
 * ``services/edit_window.py``.
 */
import { isWithinEditWindow, hoursSinceCompletion, EDIT_WINDOW_HOURS } from "@/src/lib/editWindow";


function _hours_ago(h: number): string {
  return new Date(Date.now() - h * 3_600_000).toISOString();
}


describe("mobile edit-window helpers", () => {
  it("EDIT_WINDOW_HOURS matches backend constant (24)", () => {
    expect(EDIT_WINDOW_HOURS).toBe(24);
  });

  it("returns true for completed job 1h old", () => {
    expect(isWithinEditWindow({
      status: "completed", completed_at: _hours_ago(1),
    })).toBe(true);
  });

  it("returns true at 23.9h (inside window)", () => {
    expect(isWithinEditWindow({
      status: "completed", completed_at: _hours_ago(23.9),
    })).toBe(true);
  });

  it("returns false at 25h (outside window)", () => {
    expect(isWithinEditWindow({
      status: "completed", completed_at: _hours_ago(25),
    })).toBe(false);
  });

  it("returns false for non-completed jobs", () => {
    for (const s of ["scheduled", "active", "cancelled", "requested"]) {
      expect(isWithinEditWindow({
        status: s, completed_at: _hours_ago(1),
      })).toBe(false);
    }
  });

  it("returns false for null / missing / garbage input", () => {
    expect(isWithinEditWindow(null)).toBe(false);
    expect(isWithinEditWindow(undefined)).toBe(false);
    expect(isWithinEditWindow({})).toBe(false);
    expect(isWithinEditWindow({ status: "completed" })).toBe(false);
    expect(isWithinEditWindow({
      status: "completed", completed_at: "not-a-date",
    })).toBe(false);
  });

  it("hoursSinceCompletion returns a positive float", () => {
    const h = hoursSinceCompletion({ completed_at: _hours_ago(3) });
    expect(h).not.toBeNull();
    expect(h as number).toBeGreaterThan(2.9);
    expect(h as number).toBeLessThan(3.1);
  });

  it("hoursSinceCompletion returns null for missing timestamp", () => {
    expect(hoursSinceCompletion(null)).toBeNull();
    expect(hoursSinceCompletion({})).toBeNull();
    expect(hoursSinceCompletion({ completed_at: "garbage" })).toBeNull();
  });
});
