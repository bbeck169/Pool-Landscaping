/**
 * Ticket X · Feb-2026 — "Mark as Open" action on MISSED jobs
 * across the three Schedule surfaces.
 *
 * Component-level vitest for ``MarkOpenAction`` + presence checks
 * on each surface the action was wired into (MonthCustomGrid,
 * RBC Agenda custom event row, GridPanel route-planner row).
 *
 * ``@/api`` is mocked at the module level so the hook's optimistic
 * flow, success + undo path, and 409 rollback can all be exercised
 * without a backend round-trip.
 */
import React from "react";
import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import {
  render, screen, cleanup, fireEvent, within, waitFor,
} from "@testing-library/react";

vi.mock("@/api", () => ({
  api: {
    get:  vi.fn(),
    post: vi.fn(),
    put:  vi.fn(),
    patch: vi.fn(),
    del:  vi.fn(),
  },
}));

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
  },
}));

import MarkOpenAction from "@/components/schedule/MarkOpenAction";
import MonthCustomGrid from "@/components/schedule/MonthCustomGrid";
import { api } from "@/api";
import { toast } from "sonner";


const STATUS_COLORS = {
  scheduled: "#0EA5E9", active: "#059669", completed: "#ff4542",
  pending: "#F59E0B", requested: "#8B5CF6", reopened: "#DC2626",
  cancelled: "#9CA3AF", missed: "#B91C1C",
};


function _missedJob(overrides = {}) {
  return {
    id: "j-missed-1",
    status: "missed",
    service_type: "Weekly Pool",
    customer_name: "Alice",
    missed_at: "2026-02-01T12:00:00Z",
    ...overrides,
  };
}


function _event(job, dateStr = "2026-11-10") {
  const start = new Date(`${dateStr}T00:00:00`);
  const end = new Date(start.getTime() + 86400000 - 1);
  return {
    id: job.id,
    title: `${job.service_type || ""} · ${job.customer_name || ""}`,
    start, end, allDay: true,
    resource: {
      job,
      status: job.status,
      colour: STATUS_COLORS[job.status] || "#64748B",
    },
  };
}


afterEach(() => { cleanup(); vi.clearAllMocks(); });


describe("MarkOpenAction · Ticket X", () => {
  // ─── 1. Visible ONLY on MISSED ─────────────────────────
  it("renders nothing when status !== 'missed'", () => {
    for (const status of ["scheduled", "active", "completed",
                            "cancelled", "pending"]) {
      const { container, unmount } = render(
        <MarkOpenAction
          job={{ id: `j-${status}`, status }}
          onPatch={vi.fn()}
          testIdSuffix={`t-${status}`}
        />,
      );
      expect(container.firstChild).toBeNull();
      unmount();
    }
  });

  it("renders a button when status === 'missed' (case-insensitive)",
     () => {
    render(
      <MarkOpenAction
        job={_missedJob()}
        onPatch={vi.fn()}
        testIdSuffix="t1"
      />,
    );
    expect(screen.getByTestId("mark-open-btn-t1")).toBeInTheDocument();
    cleanup();
    render(
      <MarkOpenAction
        job={_missedJob({ status: "MISSED" })}
        onPatch={vi.fn()}
        testIdSuffix="t2"
      />,
    );
    expect(screen.getByTestId("mark-open-btn-t2")).toBeInTheDocument();
  });

  // ─── 2. Click → API + optimistic patch + toast ──────────
  it("click → optimistic patch, POST /jobs/{id}/mark-open, "
     + "success toast with Undo", async () => {
    const onPatch = vi.fn();
    api.post.mockResolvedValueOnce({
      id: "j-missed-1", status: "scheduled",
      reopened_from_missed_at: "2026-02-02T00:00:00Z",
    });
    render(
      <MarkOpenAction
        job={_missedJob()}
        onPatch={onPatch}
        testIdSuffix="t"
      />,
    );
    fireEvent.click(screen.getByTestId("mark-open-btn-t"));
    // Optimistic patch fires BEFORE the api round-trip.
    expect(onPatch).toHaveBeenCalledWith(expect.objectContaining({
      id: "j-missed-1", status: "scheduled",
    }));
    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        "/jobs/j-missed-1/mark-open", {},
      );
    });
    await waitFor(() => {
      expect(toast.success).toHaveBeenCalled();
    });
    const call = toast.success.mock.calls[0];
    expect(call[0]).toMatch(/Marked as Open/i);
    expect(call[1].action.label).toBe("Undo");
    expect(typeof call[1].action.onClick).toBe("function");
    expect(call[1].duration).toBe(5000);
  });

  // ─── 3. Undo click → PUT back to missed ─────────────────
  it("Undo click → PUT /jobs/{id} back to missed with "
     + "saved missed_at", async () => {
    const onPatch = vi.fn();
    api.post.mockResolvedValueOnce({
      id: "j-missed-1", status: "scheduled",
    });
    api.put.mockResolvedValueOnce({});
    const job = _missedJob();
    render(
      <MarkOpenAction job={job} onPatch={onPatch} testIdSuffix="t" />,
    );
    fireEvent.click(screen.getByTestId("mark-open-btn-t"));
    await waitFor(() => expect(toast.success).toHaveBeenCalled());
    const undoCb = toast.success.mock.calls[0][1].action.onClick;
    await undoCb();
    expect(api.put).toHaveBeenCalledWith(
      "/jobs/j-missed-1",
      { status: "missed",
         missed_at: "2026-02-01T12:00:00Z" },
    );
    // onPatch is called with the restored original job for the
    // undo (status=missed + missed_at preserved).
    expect(onPatch).toHaveBeenCalledWith(expect.objectContaining({
      id: "j-missed-1", status: "missed",
      missed_at: "2026-02-01T12:00:00Z",
    }));
  });

  // ─── 4. BE 409 → rollback optimistic + error toast ──────
  it("BE 409 → rollback optimistic patch + error toast", async () => {
    const onPatch = vi.fn();
    const err = Object.assign(new Error("conflict"), {
      status: 409,
      data: { detail: { detail: "invalid_status_transition" } },
    });
    api.post.mockRejectedValueOnce(err);
    const job = _missedJob();
    render(
      <MarkOpenAction job={job} onPatch={onPatch} testIdSuffix="t" />,
    );
    fireEvent.click(screen.getByTestId("mark-open-btn-t"));
    // First call = optimistic ``scheduled``.
    await waitFor(() => expect(api.post).toHaveBeenCalled());
    // Rollback call restores original job (status=missed).
    await waitFor(() => {
      const calls = onPatch.mock.calls;
      // 1st call = optimistic scheduled; 2nd call = rollback
      // original missed job.
      expect(calls[0][0].status).toBe("scheduled");
      expect(calls[calls.length - 1][0].status).toBe("missed");
    });
    expect(toast.error).toHaveBeenCalled();
  });

  // ─── 5. BE network error → rollback + error toast ───────
  it("network error → rollback optimistic + error toast", async () => {
    const onPatch = vi.fn();
    api.post.mockRejectedValueOnce(new Error("network boom"));
    render(
      <MarkOpenAction
        job={_missedJob()}
        onPatch={onPatch}
        testIdSuffix="t"
      />,
    );
    fireEvent.click(screen.getByTestId("mark-open-btn-t"));
    await waitFor(() => {
      expect(toast.error).toHaveBeenCalled();
    });
    const calls = onPatch.mock.calls;
    expect(calls[calls.length - 1][0].status).toBe("missed");
  });
});


describe("MarkOpenAction wired into Schedule surfaces · Ticket X", () => {
  // ─── 6. MonthCustomGrid shows the action on MISSED card ──
  it("MonthCustomGrid renders Mark-as-Open button on a MISSED "
     + "card (surface 1 of 3)", () => {
    const missed = _missedJob({ id: "j-m-1" });
    const ok = _missedJob({ id: "j-ok-1", status: "scheduled" });
    render(
      <MonthCustomGrid
        date={new Date("2026-11-10T00:00:00")}
        events={[_event(missed), _event(ok)]}
        onNavigate={vi.fn()}
        onSelectEvent={vi.fn()}
        onViewChange={vi.fn()}
        statusColors={STATUS_COLORS}
        onPatchJob={vi.fn()}
      />,
    );
    // Missed card has the inline mark-open button.
    expect(screen.getByTestId("mark-open-btn-month-j-m-1"))
      .toBeInTheDocument();
    // Scheduled card does NOT.
    expect(screen.queryByTestId("mark-open-btn-month-j-ok-1"))
      .toBeNull();
  });

  // ─── 6a. Click inside Month cell does NOT trigger the
  //         card-click handler (event-prop-stop lock).
  it("Mark-open click inside Month cell does NOT fire the "
     + "card-click onSelectEvent handler", async () => {
    const onSelectEvent = vi.fn();
    const onPatchJob = vi.fn();
    api.post.mockResolvedValueOnce({
      id: "j-m-stop", status: "scheduled",
    });
    render(
      <MonthCustomGrid
        date={new Date("2026-11-10T00:00:00")}
        events={[_event(_missedJob({ id: "j-m-stop" }))]}
        onNavigate={vi.fn()}
        onSelectEvent={onSelectEvent}
        onViewChange={vi.fn()}
        statusColors={STATUS_COLORS}
        onPatchJob={onPatchJob}
      />,
    );
    fireEvent.click(
      screen.getByTestId("mark-open-btn-month-j-m-stop"),
    );
    // Give the microtask queue a tick to flush any bubbled call.
    await waitFor(() => expect(api.post).toHaveBeenCalled());
    expect(onSelectEvent).not.toHaveBeenCalled();
  });

  // ─── 6b. REGRESSION LOCK — month cells + their inline
  //         Mark-open buttons stay drag-less (Ticket W lock).
  it("Ticket W drag-less regression lock remains intact "
     + "with Mark-open button inside the cell", () => {
    render(
      <MonthCustomGrid
        date={new Date("2026-11-10T00:00:00")}
        events={[_event(_missedJob({ id: "j-m-drag" }))]}
        onNavigate={vi.fn()}
        onSelectEvent={vi.fn()}
        onViewChange={vi.fn()}
        statusColors={STATUS_COLORS}
        onPatchJob={vi.fn()}
      />,
    );
    const cell = screen.getByTestId("month-cell-2026-11-10");
    const btn = screen.getByTestId("mark-open-btn-month-j-m-drag");
    for (const el of [cell, btn]) {
      expect(el.getAttribute("draggable")).toBeNull();
      expect(el.hasAttribute("data-rbc-event-draggable")).toBe(false);
      expect(el.ondragstart).toBeNull();
    }
  });
});


describe("MarkOpenAction standalone presence on GridPanel + Agenda "
         + "surfaces · Ticket X", () => {
  // GridPanel + the RBC Agenda custom event renderer both inline
  // ``<MarkOpenAction job={j} onPatch={onPatchJob} ... />``.
  // Rendering the full GridPanel / RBC Agenda tree in isolation
  // would require ~800 lines of fixture scaffolding (localizer,
  // withDragAndDrop, auth provider, order controller, etc.) — out
  // of scope for a single-concern ticket. The MarkOpenAction
  // component contract tests above lock the behaviour; the two
  // tests here lock the "renders when status=missed" surface
  // contract directly on the component.

  it("surface contract — MISSED job renders a button regardless "
     + "of outer surface (route-planner row / Agenda event)", () => {
    const missed = _missedJob({ id: "j-x-surface" });
    render(
      <MarkOpenAction
        job={missed}
        onPatch={vi.fn()}
        testIdSuffix={`grid-${missed.id}`}
      />,
    );
    expect(screen.getByTestId("mark-open-btn-grid-j-x-surface"))
      .toBeInTheDocument();
    cleanup();
    render(
      <MarkOpenAction
        job={missed}
        onPatch={vi.fn()}
        testIdSuffix={`agenda-${missed.id}`}
      />,
    );
    expect(screen.getByTestId("mark-open-btn-agenda-j-x-surface"))
      .toBeInTheDocument();
  });

  it("surface contract — non-MISSED job renders NOTHING on either "
     + "surface (negative lock)", () => {
    for (const status of ["scheduled", "active", "completed"]) {
      for (const surface of ["grid", "agenda", "month"]) {
        const { container, unmount } = render(
          <MarkOpenAction
            job={{ id: `j-${surface}-${status}`, status }}
            onPatch={vi.fn()}
            testIdSuffix={`${surface}-nope`}
          />,
        );
        expect(container.firstChild).toBeNull();
        unmount();
      }
    }
  });
});
