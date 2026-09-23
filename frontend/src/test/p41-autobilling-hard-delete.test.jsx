/**
 * Phase P41 · Feb-2026 — Autobilling Runs · HARD DELETE UI contract.
 *
 * Distinct from the existing soft-delete surface (which sets
 * ``deleted_at`` + still lets Restore recover the row). Hard delete
 * physically removes the row via
 *     DELETE /api/autobilling-runs/{run_id}
 *     POST   /api/autobilling-runs/hard-delete-bulk
 * and is IRREVERSIBLE — the confirmation modal is mandatory.
 *
 * Coverage per spec:
 *   1. Row menu shows a "Delete Permanently" affordance.
 *   2. Confirming row delete → DELETE fires + row disappears + toast.
 *   3. Cancelling row delete → row stays + no API call fires.
 *   4. Bulk button disabled/hidden when no rows selected.
 *   5. Bulk confirm → POST with selected ids + selection cleared.
 *   6. API error → toast + row NOT removed.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, act, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

// ── Mocks ─────────────────────────────────────────────────────────
const getMock  = vi.fn();
const postMock = vi.fn();
const delMock  = vi.fn();
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

const toastCalls = { success: [], error: [], info: [] };
vi.mock("sonner", () => ({
  toast: Object.assign(
    (msg) => msg,
    {
      success: (msg) => { toastCalls.success.push(msg); },
      error:   (msg) => { toastCalls.error.push(msg); },
      info:    (msg) => { toastCalls.info.push(msg); },
    },
  ),
}));

vi.mock("@/components/ui-kit", () => ({
  PageHeader: ({ title, subtitle }) => (
    <div><h1>{title}</h1><p>{subtitle}</p></div>
  ),
}));

import AutobillingRuns from "@/pages/finance/AutobillingRuns";


const R1 = {
  id: "run-alpha-1", tenant_id: "t1", ts: "2026-02-10T10:00:00",
  plan_id: "p1", plan_name: "Plan Alpha", status: "fired",
  message: "ok", run_schedule: "first_friday",
  anchor_date: "2026-02-01",
};
const R2 = { ...R1, id: "run-beta-2",  plan_name: "Plan Beta"  };
const R3 = { ...R1, id: "run-gamma-3", plan_name: "Plan Gamma" };


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

beforeEach(() => {
  getMock.mockReset();
  postMock.mockReset();
  delMock.mockReset();
  toastCalls.success.length = 0;
  toastCalls.error.length   = 0;
  toastCalls.info.length    = 0;
  seedRows([R1, R2, R3]);
});


// ─────────────────────────────────────────────────────────────────
// Tests
// ─────────────────────────────────────────────────────────────────
describe("Phase P41 · Autobilling Runs · Hard Delete UI", () => {

  it("test_row_menu_shows_delete_permanently_option", async () => {
    renderPage();
    // Wait for the load() to resolve and the row to render.
    await waitFor(() =>
      expect(screen.getByTestId(`autobilling-runs-row-${R1.id}`)).toBeTruthy()
    );
    // Per-row hard-delete icon is present alongside the existing
    // soft-delete trash. Both point to different confirm modals.
    expect(
      screen.getByTestId(`autobilling-runs-row-delete-${R1.id}`)
    ).toBeTruthy();
    expect(
      screen.getByTestId(`autobilling-runs-row-hard-delete-${R1.id}`)
    ).toBeTruthy();
    expect(
      screen.getByTestId(`autobilling-runs-row-hard-delete-${R1.id}`)
        .getAttribute("aria-label"),
    ).toContain("Permanently delete");
  });

  it("test_confirming_row_delete_calls_api_and_removes_row",
      async () => {
        delMock.mockResolvedValue({ deleted: true, id: R2.id });
        renderPage();
        await waitFor(() =>
          expect(screen.getByTestId(`autobilling-runs-row-${R2.id}`)).toBeTruthy()
        );
        // Open the hard-delete confirm modal for R2.
        await act(async () => {
          fireEvent.click(
            screen.getByTestId(`autobilling-runs-row-hard-delete-${R2.id}`)
          );
        });
        expect(
          screen.getByTestId("autobilling-runs-hard-delete-confirm")
        ).toBeTruthy();
        // Title uses the singular copy per spec.
        expect(
          screen.getByTestId("autobilling-runs-hard-delete-confirm-title")
            .textContent,
        ).toContain("Permanently delete this billing run?");
        // Body includes the short-prefix id.
        expect(
          screen.getByTestId("autobilling-runs-hard-delete-confirm-body")
            .textContent,
        ).toContain(R2.id.slice(0, 8));
        // Confirm.
        await act(async () => {
          fireEvent.click(
            screen.getByTestId("autobilling-runs-hard-delete-confirm-btn")
          );
        });
        // DELETE fired with the P41 hyphenated path.
        expect(delMock).toHaveBeenCalledTimes(1);
        expect(delMock).toHaveBeenCalledWith(
          `/autobilling-runs/${R2.id}`,
        );
        // Row optimistically removed.
        await waitFor(() =>
          expect(screen.queryByTestId(`autobilling-runs-row-${R2.id}`))
            .toBeNull()
        );
        // Success toast copy matches the spec.
        expect(toastCalls.success[0]).toBe(
          "Billing run permanently deleted."
        );
      });

  it("test_cancelling_row_delete_leaves_row_intact", async () => {
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId(`autobilling-runs-row-${R3.id}`)).toBeTruthy()
    );
    await act(async () => {
      fireEvent.click(
        screen.getByTestId(`autobilling-runs-row-hard-delete-${R3.id}`)
      );
    });
    // Click Cancel — no API call fires.
    await act(async () => {
      fireEvent.click(
        screen.getByTestId("autobilling-runs-hard-delete-cancel-btn")
      );
    });
    expect(delMock).not.toHaveBeenCalled();
    expect(postMock).not.toHaveBeenCalled();
    // Row still in the DOM.
    expect(
      screen.getByTestId(`autobilling-runs-row-${R3.id}`)
    ).toBeTruthy();
  });

  it("test_bulk_delete_disabled_when_no_rows_selected", async () => {
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId(`autobilling-runs-row-${R1.id}`)).toBeTruthy()
    );
    // With no selection, the bulk hard-delete button MUST NOT render.
    expect(
      screen.queryByTestId("autobilling-runs-bulk-hard-delete-button")
    ).toBeNull();
    // Sanity: check the row-select checkboxes exist so the test isn't
    // asserting on a nonexistent selection primitive.
    expect(
      screen.getByTestId(`autobilling-runs-row-select-${R1.id}`)
    ).toBeTruthy();
  });

  it("test_bulk_delete_confirm_calls_api_with_selected_ids_and_clears_selection",
      async () => {
        postMock.mockResolvedValue({
          deleted_count: 2, requested_count: 2, not_found: [],
        });
        renderPage();
        await waitFor(() =>
          expect(screen.getByTestId(`autobilling-runs-row-${R1.id}`)).toBeTruthy()
        );
        // Select 2 rows.
        await act(async () => {
          fireEvent.click(
            screen.getByTestId(`autobilling-runs-row-select-${R1.id}`)
          );
          fireEvent.click(
            screen.getByTestId(`autobilling-runs-row-select-${R2.id}`)
          );
        });
        // Bulk hard-delete button now visible.
        const bulkBtn = screen.getByTestId(
          "autobilling-runs-bulk-hard-delete-button"
        );
        expect(bulkBtn.textContent).toContain("Delete Permanently (2)");
        await act(async () => { fireEvent.click(bulkBtn); });
        // Bulk copy uses the plural + count.
        expect(
          screen.getByTestId("autobilling-runs-hard-delete-confirm-title")
            .textContent,
        ).toContain("Permanently delete 2 billing runs?");
        // Confirm.
        await act(async () => {
          fireEvent.click(
            screen.getByTestId("autobilling-runs-hard-delete-confirm-btn")
          );
        });
        expect(postMock).toHaveBeenCalledTimes(1);
        expect(postMock).toHaveBeenCalledWith(
          "/autobilling-runs/hard-delete-bulk",
          { ids: [R1.id, R2.id] },
        );
        // Selection cleared: bulk button gone.
        await waitFor(() =>
          expect(
            screen.queryByTestId("autobilling-runs-bulk-hard-delete-button")
          ).toBeNull()
        );
        // Both rows removed optimistically.
        expect(
          screen.queryByTestId(`autobilling-runs-row-${R1.id}`)
        ).toBeNull();
        expect(
          screen.queryByTestId(`autobilling-runs-row-${R2.id}`)
        ).toBeNull();
        // R3 stays.
        expect(
          screen.getByTestId(`autobilling-runs-row-${R3.id}`)
        ).toBeTruthy();
        expect(toastCalls.success[0]).toBe(
          "Permanently deleted 2 billing runs."
        );
      });

  it("test_api_error_shows_toast_and_leaves_row_intact", async () => {
    delMock.mockRejectedValue(new Error("Forbidden — expired session"));
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId(`autobilling-runs-row-${R1.id}`)).toBeTruthy()
    );
    await act(async () => {
      fireEvent.click(
        screen.getByTestId(`autobilling-runs-row-hard-delete-${R1.id}`)
      );
    });
    await act(async () => {
      fireEvent.click(
        screen.getByTestId("autobilling-runs-hard-delete-confirm-btn")
      );
    });
    // DELETE was fired.
    expect(delMock).toHaveBeenCalledTimes(1);
    // Error toast surfaced.
    expect(toastCalls.error[0]).toContain("Forbidden");
    // Row NOT removed — optimistic remove only happens on success.
    expect(
      screen.getByTestId(`autobilling-runs-row-${R1.id}`)
    ).toBeTruthy();
  });

  it("test_partial_success_message_shows_deleted_vs_requested", async () => {
    postMock.mockResolvedValue({
      deleted_count: 1, requested_count: 2, not_found: [R2.id],
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId(`autobilling-runs-row-${R1.id}`)).toBeTruthy()
    );
    await act(async () => {
      fireEvent.click(
        screen.getByTestId(`autobilling-runs-row-select-${R1.id}`)
      );
      fireEvent.click(
        screen.getByTestId(`autobilling-runs-row-select-${R2.id}`)
      );
    });
    await act(async () => {
      fireEvent.click(
        screen.getByTestId("autobilling-runs-bulk-hard-delete-button")
      );
    });
    await act(async () => {
      fireEvent.click(
        screen.getByTestId("autobilling-runs-hard-delete-confirm-btn")
      );
    });
    // Partial success uses the "N of M" phrasing on toast.info.
    expect(toastCalls.info[0]).toBe(
      "Permanently deleted 1 of 2 billing runs."
    );
    // R2 stayed in the DOM (server said not_found).
    expect(
      screen.getByTestId(`autobilling-runs-row-${R2.id}`)
    ).toBeTruthy();
    // R1 was removed (server counted it as deleted).
    expect(
      screen.queryByTestId(`autobilling-runs-row-${R1.id}`)
    ).toBeNull();
  });

});
