/**
 * TIMECARD-EDIT-UI atomic - Feb-2026.
 * Vitest coverage for TimecardEditModal + AuditHistoryPopover.
 */
import React from "react";
import {
  describe, it, expect, vi, beforeEach, afterEach,
} from "vitest";
import {
  render, screen, fireEvent, waitFor, cleanup, act,
} from "@testing-library/react";

const patchMock = vi.fn();
const toastSuccess = vi.fn();
const toastError = vi.fn();

vi.mock("@/api", () => ({
  api: {
    patch: (...args) => patchMock(...args),
  },
}));
vi.mock("sonner", () => ({
  toast: {
    success: (m) => toastSuccess(m),
    error: (m) => toastError(m),
  },
}));

import {
  TimecardEditModal, AuditHistoryPopover, canEditTimecards,
} from "@/pages/admin/TimecardEditModal";

const BASE_ROW = {
  id: "te_abc123",
  user_name: "Mike Tech",
  job_title: "Weekly Pool",
  clock_in_at: "2026-02-15T08:00:00+00:00",
  clock_out_at: "2026-02-15T16:00:00+00:00",
  duration_minutes: 480,
  edits: [],
};

beforeEach(() => {
  patchMock.mockReset();
  toastSuccess.mockReset();
  toastError.mockReset();
});
afterEach(() => cleanup());

describe("canEditTimecards", () => {
  it("accepts the 4 admin-tier roles only", () => {
    for (const r of ["admin", "super_admin", "manager", "owner"]) {
      expect(canEditTimecards({ role: r })).toBe(true);
    }
    for (const r of ["technician", "customer", "dispatcher", null, undefined]) {
      expect(canEditTimecards({ role: r })).toBe(false);
    }
    expect(canEditTimecards(null)).toBe(false);
    expect(canEditTimecards(undefined)).toBe(false);
  });
});

describe("TimecardEditModal pre-fill and dirty-state", () => {
  it("renders pre-filled with the row current values", () => {
    render(<TimecardEditModal row={BASE_ROW} open onClose={() => {}} />);
    expect(screen.getByTestId("timecard-edit-clock-in").value)
      .toBe("2026-02-15T08:00");
    expect(screen.getByTestId("timecard-edit-clock-out").value)
      .toBe("2026-02-15T16:00");
    expect(screen.getByTestId("timecard-edit-date").value)
      .toBe("2026-02-15");
    expect(screen.getByTestId("timecard-edit-reason").value).toBe("");
  });

  it("Save button is disabled while nothing has changed, enabled when a field is dirty", () => {
    render(<TimecardEditModal row={BASE_ROW} open onClose={() => {}} />);
    const save = screen.getByTestId("timecard-edit-save");
    expect(save).toBeDisabled();
    fireEvent.change(screen.getByTestId("timecard-edit-clock-in"), {
      target: { value: "2026-02-15T09:00" },
    });
    expect(save).not.toBeDisabled();
  });

  it("Cancel does NOT fire PATCH", () => {
    const onClose = vi.fn();
    render(<TimecardEditModal row={BASE_ROW} open onClose={onClose} />);
    fireEvent.click(screen.getByTestId("timecard-edit-cancel"));
    expect(onClose).toHaveBeenCalled();
    expect(patchMock).not.toHaveBeenCalled();
  });
});

describe("TimecardEditModal reason length cap", () => {
  it("truncates reason input at 500 characters and shows live counter", () => {
    render(<TimecardEditModal row={BASE_ROW} open onClose={() => {}} />);
    const ta = screen.getByTestId("timecard-edit-reason");
    fireEvent.change(ta, { target: { value: "x".repeat(600) } });
    expect(ta.value.length).toBe(500);
    expect(screen.getByTestId("timecard-edit-reason-counter").textContent)
      .toBe("500/500");
  });
});

describe("TimecardEditModal PATCH submission", () => {
  it("sends only dirty fields with ISO strings reconstructed from the row tz", async () => {
    patchMock.mockResolvedValueOnce({ ...BASE_ROW,
      clock_in_at: "2026-02-15T09:00:00+00:00",
      edits: [{ edit_id: "e1", edited_by: "u", edited_by_name: "Admin",
        edited_by_role: "admin", edited_at: "2026-02-15T20:00:00+00:00",
        changes: { clock_in_at: {
          from: "2026-02-15T08:00:00+00:00",
          to: "2026-02-15T09:00:00+00:00",
        } } }],
    });
    const onUpdated = vi.fn();
    const onClose = vi.fn();
    render(
      <TimecardEditModal row={BASE_ROW} open
        onClose={onClose} onUpdated={onUpdated} />,
    );
    fireEvent.change(screen.getByTestId("timecard-edit-clock-in"), {
      target: { value: "2026-02-15T09:00" },
    });
    fireEvent.change(screen.getByTestId("timecard-edit-reason"), {
      target: { value: "fat-finger fix" },
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("timecard-edit-save"));
    });
    expect(patchMock).toHaveBeenCalledTimes(1);
    const [path, body] = patchMock.mock.calls[0];
    expect(path).toBe("/workforce/timesheets/te_abc123");
    // Only dirty fields are sent - no clock_out_at, no date.
    expect(body).toEqual({
      clock_in_at: "2026-02-15T09:00:00+00:00",
      reason: "fat-finger fix",
    });
    await waitFor(() => expect(toastSuccess).toHaveBeenCalled());
    expect(onUpdated).toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });

  it("surfaces backend error detail verbatim via sonner toast", async () => {
    const err = new Error("shift_duration_unreasonable: 22.5h exceeds 20h cap; verify start/end times");
    err.status = 400;
    err.data = { detail: "shift_duration_unreasonable: 22.5h exceeds 20h cap; verify start/end times" };
    patchMock.mockRejectedValueOnce(err);
    render(<TimecardEditModal row={BASE_ROW} open onClose={() => {}} />);
    fireEvent.change(screen.getByTestId("timecard-edit-clock-in"), {
      target: { value: "2026-02-15T02:00" },
    });
    fireEvent.change(screen.getByTestId("timecard-edit-clock-out"), {
      target: { value: "2026-02-15T00:30" },
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("timecard-edit-save"));
    });
    await waitFor(() => expect(toastError).toHaveBeenCalled());
    expect(toastError.mock.calls[0][0]).toMatch(/shift_duration_unreasonable/);
    expect(toastError.mock.calls[0][0]).toMatch(/20h cap/);
  });
});

describe("TimecardEditModal open-shift handling", () => {
  it("disables clock_out_at and omits it from the body", async () => {
    const open_row = { ...BASE_ROW, clock_out_at: null, duration_minutes: 0 };
    patchMock.mockResolvedValueOnce({ ...open_row,
      clock_in_at: "2026-02-15T07:30:00+00:00",
      edits: [{ edit_id: "e2", edited_by_name: "Admin",
        edited_by_role: "admin", edited_at: "2026-02-15T20:00:00+00:00",
        changes: { clock_in_at: { from: "2026-02-15T08:00:00+00:00",
          to: "2026-02-15T07:30:00+00:00" } } }],
    });
    render(<TimecardEditModal row={open_row} open onClose={() => {}} />);
    const coInput = screen.getByTestId("timecard-edit-clock-out");
    expect(coInput).toBeDisabled();
    fireEvent.change(screen.getByTestId("timecard-edit-clock-in"), {
      target: { value: "2026-02-15T07:30" },
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("timecard-edit-save"));
    });
    const [, body] = patchMock.mock.calls[0];
    expect(body).toEqual({ clock_in_at: "2026-02-15T07:30:00+00:00" });
    expect(body.clock_out_at).toBeUndefined();
  });
});

describe("AuditHistoryPopover", () => {
  it("renders nothing when edits is empty", () => {
    const { container } = render(<AuditHistoryPopover edits={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders a trigger button with edit count when edits is populated", () => {
    const edits = [
      { edit_id: "e1", edited_by_name: "Admin User",
        edited_by_role: "admin", edited_at: "2026-02-15T20:00:00+00:00",
        changes: { clock_in_at: { from: "2026-02-15T08:00:00+00:00",
          to: "2026-02-15T09:00:00+00:00" } }, reason: "fat-finger" },
      { edit_id: "e2", edited_by_name: "Manager",
        edited_by_role: "manager", edited_at: "2026-02-16T10:00:00+00:00",
        changes: { date: { from: "2026-02-15", to: "2026-02-16" } } },
    ];
    render(<AuditHistoryPopover edits={edits} testid="audit-x" />);
    const trigger = screen.getByTestId("audit-x");
    expect(trigger.textContent).toContain("Edited");
    expect(trigger.textContent).toContain("2");
  });
});
