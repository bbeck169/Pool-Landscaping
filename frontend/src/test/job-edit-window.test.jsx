/**
 * Feb-2026 · Slice 6 — 24h Post-Completion Edit Window (frontend).
 *
 * Vitest coverage for :file:`src/pages/jobs/JobEditPanel.jsx`.
 *
 * Covers:
 *   1. ``isWithinEditWindow`` client helper matches the backend
 *      contract for completed / in-window / out-of-window / not-
 *      completed / missing-completed_at.
 *   2. Edit button renders when the job is inside the window.
 *   3. Edit History section fetches and renders the diff rows.
 *   4. Save inside window PATCHes ``/jobs/{id}`` and calls
 *      ``onEdited`` with the fresh job.
 *   5. 403 ``edit_window_expired`` surfaces the inline error banner.
 *   6. Edit button is HIDDEN when the job is outside the window
 *      (or non-completed).
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, waitFor, fireEvent } from "@testing-library/react";

const getMock = vi.fn();
const patchMock = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get: (...a) => getMock(...a),
    patch: (...a) => patchMock(...a),
  },
}));

vi.mock("@/theme", () => ({
  colors: {
    onSurface: "#0F172A", muted: "#64748B", border: "#E2E8F0",
    surface: "#FFFFFF", surfaceSubtle: "#F8FAFC",
  },
}));

vi.mock("@/components/ui-kit", () => ({
  Button: ({ children, onClick, disabled, testid, ...p }) => (
    <button
      data-testid={testid}
      onClick={onClick}
      disabled={disabled}
      {...p}
    >
      {children}
    </button>
  ),
  Modal: ({ isOpen, title, children, testid }) =>
    isOpen ? (
      <div data-testid={testid} role="dialog" aria-label={title}>
        <h2>{title}</h2>
        {children}
      </div>
    ) : null,
  Toast: ({ message, tone }) => (
    <div data-testid={`toast-${tone}`}>{message}</div>
  ),
}));

// Import AFTER mocks so the module picks them up.
import JobEditPanel, { isWithinEditWindow, hoursSinceCompletion } from
  "@/pages/jobs/JobEditPanel";


function _iso_hours_ago(h) {
  return new Date(Date.now() - h * 3_600_000).toISOString();
}


describe("isWithinEditWindow client-mirror helper", () => {
  it("returns true for a completed job 1h old", () => {
    expect(isWithinEditWindow({
      status: "completed", completed_at: _iso_hours_ago(1),
    })).toBe(true);
  });

  it("returns true for a completed job 23.9h old (boundary)", () => {
    expect(isWithinEditWindow({
      status: "completed", completed_at: _iso_hours_ago(23.9),
    })).toBe(true);
  });

  it("returns false for a completed job 25h old (outside window)", () => {
    expect(isWithinEditWindow({
      status: "completed", completed_at: _iso_hours_ago(25),
    })).toBe(false);
  });

  it("returns false for a non-completed job", () => {
    expect(isWithinEditWindow({
      status: "scheduled", completed_at: _iso_hours_ago(1),
    })).toBe(false);
  });

  it("returns false when completed_at is missing", () => {
    expect(isWithinEditWindow({ status: "completed" })).toBe(false);
  });

  it("returns false on garbage / null input", () => {
    expect(isWithinEditWindow(null)).toBe(false);
    expect(isWithinEditWindow({})).toBe(false);
    expect(isWithinEditWindow({
      status: "completed", completed_at: "not-a-date",
    })).toBe(false);
  });
});


describe("<JobEditPanel>", () => {
  beforeEach(() => {
    getMock.mockReset();
    patchMock.mockReset();
  });
  afterEach(() => cleanup());

  const _inWindowJob = {
    id: "job-abc",
    status: "completed",
    completed_at: _iso_hours_ago(2),
    notes: "Original notes.",
  };
  const _outOfWindowJob = {
    id: "job-xyz",
    status: "completed",
    completed_at: _iso_hours_ago(48),
    notes: "Original notes.",
  };

  it("renders the Edit button and window banner when job is in-window", () => {
    getMock.mockResolvedValue({ count: 0, edits: [] });
    render(<JobEditPanel job={_inWindowJob} />);
    expect(screen.getByTestId("job-edit-window-banner")).toBeTruthy();
    expect(screen.getByTestId("job-edit-open")).toBeTruthy();
    // "N.Nh" hours-left text renders.
    expect(screen.getByTestId("job-edit-window-hours-left")).toBeTruthy();
  });

  it("HIDES the Edit button when the job is outside the window", () => {
    getMock.mockResolvedValue({ count: 0, edits: [] });
    render(<JobEditPanel job={_outOfWindowJob} />);
    expect(screen.queryByTestId("job-edit-window-banner")).toBeNull();
    expect(screen.queryByTestId("job-edit-open")).toBeNull();
    // Edit History toggle still available so admin can review.
    expect(screen.getByTestId("job-edit-history-toggle")).toBeTruthy();
  });

  it("HIDES the Edit button when the job is not completed", () => {
    getMock.mockResolvedValue({ count: 0, edits: [] });
    render(<JobEditPanel job={{ ..._inWindowJob, status: "scheduled" }} />);
    expect(screen.queryByTestId("job-edit-open")).toBeNull();
  });

  it("opens the modal, saves, and calls onEdited with the fresh job", async () => {
    const fresh = { ..._inWindowJob, notes: "Updated notes." };
    patchMock.mockResolvedValue(fresh);
    getMock.mockResolvedValue({ count: 0, edits: [] });
    const onEdited = vi.fn();
    render(<JobEditPanel job={_inWindowJob} onEdited={onEdited} />);
    fireEvent.click(screen.getByTestId("job-edit-open"));
    expect(screen.getByTestId("job-edit-modal")).toBeTruthy();
    const ta = screen.getByTestId("job-edit-notes-input");
    fireEvent.change(ta, { target: { value: "Updated notes." } });
    fireEvent.click(screen.getByTestId("job-edit-save"));
    await waitFor(() => expect(patchMock).toHaveBeenCalled());
    expect(patchMock.mock.calls[0][0]).toBe("/jobs/job-abc");
    expect(patchMock.mock.calls[0][1]).toMatchObject({
      notes: "Updated notes.",
      edit_source: "web",
    });
    await waitFor(() => expect(onEdited).toHaveBeenCalledWith(fresh));
  });

  it("surfaces an inline error banner on 403 edit_window_expired", async () => {
    // Simulate the api wrapper's error shape — ``detail`` on the
    // rejection is a dict per FastAPI's HTTPException(detail=...).
    patchMock.mockRejectedValue({
      status: 403,
      detail: {
        detail: "edit_window_expired",
        edit_window_hours: 24,
        hours_since_completion: 30.5,
      },
    });
    getMock.mockResolvedValue({ count: 0, edits: [] });
    render(<JobEditPanel job={_inWindowJob} />);
    fireEvent.click(screen.getByTestId("job-edit-open"));
    fireEvent.click(screen.getByTestId("job-edit-save"));
    await waitFor(() =>
      expect(screen.getByTestId("job-edit-error")).toBeTruthy()
    );
    const err = screen.getByTestId("job-edit-error").textContent;
    expect(err).toMatch(/window closed/i);
    expect(err).toMatch(/30\.5h ago/);
  });

  it("Edit History fetches /jobs/{id}/edits and renders diff rows", async () => {
    const _edit_row = {
      id: "e1",
      edited_by_name: "Mike Rivera",
      edited_by_role: "technician",
      edited_at: new Date().toISOString(),
      source: "web",
      reason: "Corrected Free Cl reading",
      changes: { notes: { before: "old", after: "new" } },
    };
    getMock.mockResolvedValue({ count: 1, edits: [_edit_row] });
    render(<JobEditPanel job={_inWindowJob} />);
    fireEvent.click(screen.getByTestId("job-edit-history-toggle"));
    await waitFor(() =>
      expect(getMock).toHaveBeenCalledWith("/jobs/job-abc/edits")
    );
    await waitFor(() =>
      expect(screen.getByTestId("job-edit-history-row-0")).toBeTruthy()
    );
    // Diff row shows before → after inline.
    const diff = screen.getByTestId("job-edit-history-diff-0-notes").textContent;
    expect(diff).toMatch(/old/);
    expect(diff).toMatch(/new/);
    // Reason surfaced.
    expect(screen.getByTestId("job-edit-history-reason-0")).toBeTruthy();
    // Count badge on the toggle.
    expect(screen.getByTestId("job-edit-history-count").textContent).toBe("1");
  });
});
