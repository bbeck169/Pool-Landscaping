/**
 * Phase C · Feb-2026 — Drag-and-drop Reorder Route modal (vitest).
 *
 * Covers the deterministic UX pieces:
 *   1. Renders each row with a read-only 1..N badge in initial order.
 *   2. Empty state text + disabled Save when there are 0 jobs.
 *   3. Up/down arrow buttons reorder + boundaries are disabled.
 *   4. Save button POSTs the current ordered_job_ids array.
 *
 * DnD keyboard flow is exercised by @dnd-kit's own suite; we don't
 * re-test that here — we test our reorder + save contract.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, act, waitFor } from "@testing-library/react";

const _h = vi.hoisted(() => ({
  post: vi.fn(),
}));
vi.mock("@/api", () => ({
  api: { post: _h.post },
}));
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { ReorderRouteModal } from "@/pages/schedule/ReorderRouteModal";

const JOBS = [
  { id: "j1", customer_name: "Alice", route_index: 0 },
  { id: "j2", customer_name: "Bob",   route_index: 1 },
  { id: "j3", customer_name: "Carla", route_index: 2 },
];

beforeEach(() => {
  _h.post.mockReset();
  _h.post.mockResolvedValue({ ok: true, updated: 3, expected: 3 });
});


describe("ReorderRouteModal (Phase C)", () => {
  it("renders rows with contiguous 1..N badges in initial order", () => {
    render(
      <ReorderRouteModal
        jobs={JOBS} techUserId="t1" date="2026-02-05"
        onClose={vi.fn()} onSaved={vi.fn()}
      />,
    );
    expect(screen.getByTestId("reorder-route-modal")).toBeTruthy();
    expect(screen.getByTestId("reorder-route-badge-j1").textContent).toBe("1");
    expect(screen.getByTestId("reorder-route-badge-j2").textContent).toBe("2");
    expect(screen.getByTestId("reorder-route-badge-j3").textContent).toBe("3");
  });

  it("shows empty state and disables Save when there are 0 jobs", () => {
    render(
      <ReorderRouteModal
        jobs={[]} techUserId="t1" date="2026-02-05"
        onClose={vi.fn()} onSaved={vi.fn()}
      />,
    );
    expect(screen.getByTestId("reorder-route-empty")).toBeTruthy();
    expect(screen.getByTestId("reorder-route-save").disabled).toBe(true);
  });

  it("up arrow is disabled on first row, down is disabled on last row", () => {
    render(
      <ReorderRouteModal
        jobs={JOBS} techUserId="t1" date="2026-02-05"
        onClose={vi.fn()} onSaved={vi.fn()}
      />,
    );
    expect(screen.getByTestId("reorder-route-up-j1").disabled).toBe(true);
    expect(screen.getByTestId("reorder-route-down-j1").disabled).toBe(false);
    expect(screen.getByTestId("reorder-route-down-j3").disabled).toBe(true);
    expect(screen.getByTestId("reorder-route-up-j3").disabled).toBe(false);
  });

  it("clicking down arrow reorders and re-numbers badges 1..N", () => {
    render(
      <ReorderRouteModal
        jobs={JOBS} techUserId="t1" date="2026-02-05"
        onClose={vi.fn()} onSaved={vi.fn()}
      />,
    );
    act(() => {
      fireEvent.click(screen.getByTestId("reorder-route-down-j1"));
    });
    // j1 is now position 2, j2 becomes position 1
    expect(screen.getByTestId("reorder-route-badge-j2").textContent).toBe("1");
    expect(screen.getByTestId("reorder-route-badge-j1").textContent).toBe("2");
    expect(screen.getByTestId("reorder-route-badge-j3").textContent).toBe("3");
  });

  it("Save posts current ordered_job_ids as an array (1..N via array order)", async () => {
    const onSaved = vi.fn();
    const onClose = vi.fn();
    render(
      <ReorderRouteModal
        jobs={JOBS} techUserId="tech-42" date="2026-02-05"
        onClose={onClose} onSaved={onSaved}
      />,
    );
    // Move j3 up twice → order becomes [j3, j1, j2]
    act(() => {
      fireEvent.click(screen.getByTestId("reorder-route-up-j3"));
    });
    act(() => {
      fireEvent.click(screen.getByTestId("reorder-route-up-j3"));
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("reorder-route-save"));
    });
    await waitFor(() => expect(_h.post).toHaveBeenCalledTimes(1));
    const [path, body] = _h.post.mock.calls[0];
    expect(path).toBe("/jobs/reorder");
    expect(body.tech_user_id).toBe("tech-42");
    expect(body.date).toBe("2026-02-05");
    expect(body.ordered_job_ids).toEqual(["j3", "j1", "j2"]);
    expect(onSaved).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("announces moves via aria-live region", () => {
    render(
      <ReorderRouteModal
        jobs={JOBS} techUserId="t1" date="2026-02-05"
        onClose={vi.fn()} onSaved={vi.fn()}
      />,
    );
    act(() => {
      fireEvent.click(screen.getByTestId("reorder-route-down-j1"));
    });
    const live = screen.getByTestId("reorder-route-live-region");
    expect(live.textContent).toMatch(/Moved Alice from position 1 to position 2/);
    expect(live.textContent).toMatch(/New order: 1 to 3/);
  });
});
