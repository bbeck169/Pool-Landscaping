/**
 * Aug-2026 · Autobilling Runs — soft-delete UI contract.
 *
 * Guards:
 *   • admin/super_admin see the trash icon per row + "Delete Selected"
 *     bulk button + "Show deleted" toggle.
 *   • non-admin roles (manager, technician, customer) see none of the
 *     above.
 *   • click trash → confirmation modal → confirm → DELETE fires →
 *     row disappears from list.
 *   • bulk delete with 3 selected → "Delete Selected (3)" appears →
 *     confirm → 3 rows disappear.
 *   • Show deleted toggle → deleted rows re-appear with muted styling
 *     and a Restore icon.
 *   • Restore → confirmation → POST /restore → row un-mutes.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, act, fireEvent, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const getMock = vi.fn();
const postMock = vi.fn();
const delMock = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get: (...a) => getMock(...a),
    post: (...a) => postMock(...a),
    del: (...a) => delMock(...a),
  },
  TOKEN_KEY: "token",
}));

const authState = { user: { id: "u1", email: "admin@x", role: "admin" } };
vi.mock("@/auth", () => ({
  useAuth: () => authState,
  AuthProvider: ({ children }) => children,
}));

vi.mock("sonner", () => ({
  toast: Object.assign(
    (msg) => msg,
    { success: vi.fn(), error: vi.fn(), info: vi.fn() },
  ),
}));

vi.mock("@/components/ui-kit", () => ({
  PageHeader: ({ title, subtitle }) => (
    <div>
      <h1>{title}</h1><p>{subtitle}</p>
    </div>
  ),
}));

import AutobillingRuns from "@/pages/finance/AutobillingRuns";


function renderPage() {
  return render(
    <MemoryRouter>
      <AutobillingRuns />
    </MemoryRouter>,
  );
}


function seedRows(rows) {
  getMock.mockImplementation(async () => rows);
}


const R1 = {
  id: "r1", tenant_id: "t1", ts: "2026-08-10T10:00:00",
  plan_id: "p1", plan_name: "Plan Alpha", status: "fired",
  message: "ok", run_schedule: "first_friday", anchor_date: "2026-08-01",
};
const R2 = { ...R1, id: "r2", plan_name: "Plan Beta", status: "scheduled" };
const R3 = { ...R1, id: "r3", plan_name: "Plan Gamma", status: "error" };


describe("AutobillingRuns · soft-delete UI · admin", () => {
  beforeEach(() => {
    authState.user = { id: "u1", email: "admin@x", role: "admin" };
    getMock.mockReset(); postMock.mockReset(); delMock.mockReset();
  });
  afterEach(() => {
    getMock.mockReset(); postMock.mockReset(); delMock.mockReset();
  });

  it("renders the trash icon per row for admin", async () => {
    seedRows([R1, R2, R3]);
    await act(async () => renderPage());
    await waitFor(() => screen.getByTestId("autobilling-runs-row-r1"));

    expect(screen.getByTestId("autobilling-runs-row-delete-r1")).toBeInTheDocument();
    expect(screen.getByTestId("autobilling-runs-row-delete-r2")).toBeInTheDocument();
    expect(screen.getByTestId("autobilling-runs-row-delete-r3")).toBeInTheDocument();
    expect(screen.getByTestId("autobilling-runs-show-deleted-toggle")).toBeInTheDocument();
  });

  it("clicking trash → confirmation modal → confirm → DELETE fires → row drops", async () => {
    seedRows([R1, R2, R3]);
    delMock.mockResolvedValueOnce({ ok: true, id: "r1" });
    await act(async () => renderPage());
    await waitFor(() => screen.getByTestId("autobilling-runs-row-r1"));

    await act(async () => {
      fireEvent.click(screen.getByTestId("autobilling-runs-row-delete-r1"));
    });
    // Confirmation modal appears with single-row copy.
    const modal = await screen.findByTestId("autobilling-runs-delete-confirm");
    expect(within(modal).getByTestId("autobilling-runs-delete-confirm-title").textContent)
      .toMatch(/Delete this autobill run\?/);

    await act(async () => {
      fireEvent.click(screen.getByTestId("autobilling-runs-delete-confirm-btn"));
    });
    await waitFor(() =>
      expect(delMock).toHaveBeenCalledWith("/autobilling/runs/r1"),
    );
    // Row optimistically disappears from the default view.
    await waitFor(() =>
      expect(screen.queryByTestId("autobilling-runs-row-r1")).not.toBeInTheDocument(),
    );
  });

  it("select 3 rows → 'Delete Selected (3)' button appears → confirm → bulk-delete fires", async () => {
    seedRows([R1, R2, R3]);
    postMock.mockResolvedValueOnce({
      deleted: 3, skipped: 0,
      results: [
        { id: "r1", status: "deleted" },
        { id: "r2", status: "deleted" },
        { id: "r3", status: "deleted" },
      ],
    });
    await act(async () => renderPage());
    await waitFor(() => screen.getByTestId("autobilling-runs-row-r1"));

    await act(async () => {
      fireEvent.click(screen.getByTestId("autobilling-runs-row-select-r1"));
      fireEvent.click(screen.getByTestId("autobilling-runs-row-select-r2"));
      fireEvent.click(screen.getByTestId("autobilling-runs-row-select-r3"));
    });
    const btn = await screen.findByTestId("autobilling-runs-bulk-delete-button");
    expect(btn.textContent).toMatch(/Delete Selected \(3\)/);

    await act(async () => { fireEvent.click(btn); });
    const modal = await screen.findByTestId("autobilling-runs-delete-confirm");
    expect(within(modal).getByTestId("autobilling-runs-delete-confirm-title").textContent)
      .toMatch(/Delete 3 autobill runs\?/);

    await act(async () => {
      fireEvent.click(screen.getByTestId("autobilling-runs-delete-confirm-btn"));
    });
    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith(
        "/autobilling/runs/bulk-delete", { ids: ["r1", "r2", "r3"] },
      ),
    );
    // All three optimistically drop.
    await waitFor(() => {
      expect(screen.queryByTestId("autobilling-runs-row-r1")).not.toBeInTheDocument();
      expect(screen.queryByTestId("autobilling-runs-row-r2")).not.toBeInTheDocument();
      expect(screen.queryByTestId("autobilling-runs-row-r3")).not.toBeInTheDocument();
    });
  });

  it("toggling 'Show deleted' → deleted rows re-appear with restore icon", async () => {
    // First fetch → default view (no deleted). Second fetch (after
    // toggle) → include deleted.
    getMock
      .mockResolvedValueOnce([R1])
      .mockResolvedValueOnce([R1, { ...R2, deleted_at: "2026-08-09T00:00:00" }]);
    await act(async () => renderPage());
    await waitFor(() => screen.getByTestId("autobilling-runs-row-r1"));
    expect(screen.queryByTestId("autobilling-runs-row-r2")).not.toBeInTheDocument();

    await act(async () => {
      fireEvent.click(screen.getByTestId("autobilling-runs-show-deleted-toggle"));
    });
    await waitFor(() =>
      expect(screen.getByTestId("autobilling-runs-row-r2")).toBeInTheDocument(),
    );
    // Deleted row shows the DELETED pill + Restore icon (not trash).
    expect(screen.getByTestId("autobilling-runs-row-deleted-pill-r2")).toBeInTheDocument();
    expect(screen.getByTestId("autobilling-runs-row-restore-r2")).toBeInTheDocument();
    expect(screen.queryByTestId("autobilling-runs-row-delete-r2")).not.toBeInTheDocument();
    // Second GET included the ?include_deleted=true flag.
    const secondCallUrl = getMock.mock.calls[1][0];
    expect(secondCallUrl).toContain("include_deleted=true");
  });

  it("click Restore → confirmation → POST /restore fires → row un-mutes", async () => {
    getMock.mockResolvedValueOnce([
      { ...R2, deleted_at: "2026-08-09T00:00:00" },
    ]);
    postMock.mockResolvedValueOnce({ ok: true, id: "r2", restored: true });
    // Seed showDeleted=true via the fact that the row already ships
    // with deleted_at — the UI treats deleted_at as truthy and renders
    // the Restore icon regardless of the toggle for rows already in
    // ``rows`` state.
    await act(async () => renderPage());
    await waitFor(() => screen.getByTestId("autobilling-runs-row-r2"));

    await act(async () => {
      fireEvent.click(screen.getByTestId("autobilling-runs-row-restore-r2"));
    });
    const modal = await screen.findByTestId("autobilling-runs-restore-confirm");
    expect(within(modal).getByRole("heading").textContent).toMatch(/Restore this autobill run/i);

    await act(async () => {
      fireEvent.click(screen.getByTestId("autobilling-runs-restore-confirm-btn"));
    });
    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith(
        "/autobilling/runs/r2/restore", {},
      ),
    );
    // Row un-mutes — restore icon disappears, trash icon returns.
    await waitFor(() => {
      expect(screen.queryByTestId("autobilling-runs-row-restore-r2")).not.toBeInTheDocument();
    });
    expect(screen.getByTestId("autobilling-runs-row-delete-r2")).toBeInTheDocument();
  });
});


describe("AutobillingRuns · soft-delete UI · non-admin roles", () => {
  beforeEach(() => {
    getMock.mockReset(); postMock.mockReset(); delMock.mockReset();
  });

  it.each([
    ["manager"],
    ["technician"],
    ["customer"],
  ])("does NOT render trash / Show-deleted / bulk-delete for role=%s", async (role) => {
    authState.user = { id: "u1", email: "x@x", role };
    seedRows([R1, R2, R3]);
    await act(async () => renderPage());
    await waitFor(() => screen.getByTestId("autobilling-runs-row-r1"));

    expect(screen.queryByTestId("autobilling-runs-row-delete-r1")).not.toBeInTheDocument();
    expect(screen.queryByTestId("autobilling-runs-row-delete-r2")).not.toBeInTheDocument();
    expect(screen.queryByTestId("autobilling-runs-row-delete-r3")).not.toBeInTheDocument();
    expect(screen.queryByTestId("autobilling-runs-show-deleted-toggle")).not.toBeInTheDocument();
    // Bulk-delete button is only rendered when both role AND selection are met;
    // guard against a stray render regardless of selection state.
    expect(screen.queryByTestId("autobilling-runs-bulk-delete-button")).not.toBeInTheDocument();
  });
});
