/**
 * P0 Step C · Feb-2026 — RecurringJobs table container must
 * overflow horizontally so the newly-added rightmost "Actions"
 * column stays reachable at narrow viewports.
 *
 * Regression this pins:
 *   The table container previously used ``overflow-hidden``. On a
 *   ≤ 640-px viewport that clipped the rightmost columns entirely
 *   — the 3-dot Actions button + labelled ``<th>Actions</th>``
 *   would be invisible with no horizontal scroll affordance.
 *   The fix flips the class to ``overflow-x-auto`` so:
 *     • Wide viewports render identically (auto == hidden when the
 *       content fits).
 *     • Narrow viewports get a horizontal scrollbar and can reach
 *       the Actions column.
 *
 * Same source-string convention as
 * ``phase-recurring-jobs-inline-edit-render.test.jsx`` — cheap
 * assertion, no full-tree mount required.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const RECURRING_JOBS_SRC = readFileSync(
  resolve(__dirname, "../pages/admin/RecurringJobs.jsx"),
  "utf8",
);

const { getSpy, delSpy, postSpy, patchSpy } = vi.hoisted(() => ({
  getSpy: vi.fn(),
  delSpy: vi.fn(),
  postSpy: vi.fn(),
  patchSpy: vi.fn(),
}));

vi.mock("@/api", () => ({
  api: {
    get: (...a) => getSpy(...a),
    del: (...a) => delSpy(...a),
    post: (...a) => postSpy(...a),
    patch: (...a) => patchSpy(...a),
  },
}));
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(),
             info: vi.fn(), warning: vi.fn() },
}));
vi.mock("@/theme", () => ({
  colors: {
    brand: "#0284C7", onBrand: "#FFFFFF", onSurface: "#111827",
    onSurfaceInverse: "#FFFFFF",
    onBrandTertiary: "#0F172A",
    brandTertiary: "#E0F2FE",
    muted: "#6B7280", border: "#E5E7EB", surface: "#FFFFFF",
    surfaceSecondary: "#F8FAFC",
    searchIcon: "#0284C7",
    error: "#B91C1C",
  },
}));
vi.mock("@/components/customers/CustomerCombobox", () => ({
  default: () => null,
}));
vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({
    role: "admin", effectiveRole: "admin", can: () => true,
    loading: false, matrix: {}, previewRole: null,
    setPreviewRole: () => {}, isPreviewing: false, canPreview: false,
  }),
}));


import RecurringJobs from "@/pages/admin/RecurringJobs";


beforeEach(() => {
  getSpy.mockReset();
  delSpy.mockReset();
  postSpy.mockReset();
  patchSpy.mockReset();
  getSpy.mockImplementation(async (path) => {
    if (path === "/recurring-jobs" || path.startsWith("/recurring-jobs?")) {
      return {
        items: [{
          id: "overflow-row-1",
          customer_id: "cust-1",
          customer_name: "Narrow Viewport Cust",
          service_type: "Weekly Pool",
          frequency: "weekly", day_of_week: 0,
          start_date: "2026-01-01",
          price_cents: 12000,
          active: true, is_active: true,
          upcoming: [],
        }],
      };
    }
    if (path.startsWith("/customers")) return { items: [] };
    if (path === "/technicians") return { items: [] };
    if (path === "/crews") return { items: [] };
    if (path === "/recurring-jobs/orphans") return { count: 0, items: [] };
    return null;
  });
});


describe("P0 Step C · RecurringJobs table container overflow", () => {
  it("source uses overflow-x-auto (not overflow-hidden) on the table container", () => {
    // Lock the exact regression pin — a future refactor that
    // flips back to ``overflow-hidden`` re-introduces the clipped-
    // Actions-column bug.
    expect(RECURRING_JOBS_SRC).toMatch(
      /className="rounded-2xl overflow-x-auto"/,
    );
    expect(RECURRING_JOBS_SRC).not.toMatch(
      /className="rounded-2xl overflow-hidden"/,
    );
  });

  it("renders the Actions <th> at a 640-px narrow viewport", async () => {
    // Simulate a phone-sized viewport so we prove the header cell
    // is present in the DOM (i.e. not display:none / conditionally
    // removed at narrow widths).  Whether it's currently visible
    // vs off-screen right depends on the table's intrinsic width;
    // the invariant this test defends is DOM presence + not
    // ``overflow: clip`` on the container.
    Object.defineProperty(window, "innerWidth",
      { writable: true, configurable: true, value: 640 });
    Object.defineProperty(window, "innerHeight",
      { writable: true, configurable: true, value: 800 });
    window.dispatchEvent(new Event("resize"));

    render(<MemoryRouter><RecurringJobs /></MemoryRouter>);

    // Actions header cell renders.
    const th = await screen.findByTestId("recurring-th-actions");
    expect(th).toBeTruthy();
    expect(th.textContent.trim()).toBe("Actions");

    // Container is the *parent* .rounded-2xl div wrapping the
    // <table>. Walk up from the header to that container.
    const table = th.closest("table");
    expect(table).not.toBeNull();
    const container = table.parentElement;
    expect(container).not.toBeNull();
    expect(container.className).toMatch(/overflow-x-auto/);
    expect(container.className).not.toMatch(/overflow-hidden/);

    // Also assert the actions button on the row is present so we
    // know the whole rightmost column is DOM-present under the
    // narrow viewport render.
    await waitFor(() => {
      expect(
        screen.getByTestId("recurring-row-actions-btn-overflow-row-1"),
      ).toBeTruthy();
    });
  });
});
