/**
 * Feb-2026 · Cleanup — Revenue-by-Category tile UUID defense-in-depth.
 *
 * The backend GUARANTEES ``items[*].category`` is a display name
 * (see ``routers/dashboard_revenue.py::revenue_by_category``).  This
 * test locks in the FRONTEND belt-and-suspenders: if a future
 * backend regression accidentally leaks a UUID into the payload,
 * the tile must coerce it to "Uncategorized" before render — never
 * show a raw id string to admins.
 *
 * Guarded surfaces (per ``RevenueByCategoryTile.jsx`` render path):
 *   1. Legend text (visible string).
 *   2. Legend testid (screen-reader / test surface).
 *   3. Pie ``nameKey`` (feeds the tooltip via ``payload.displayLabel``).
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";


vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

const { apiGetMock } = vi.hoisted(() => ({ apiGetMock: vi.fn() }));
vi.mock("@/api", () => ({
  api: { get: apiGetMock, post: vi.fn(), patch: vi.fn(), put: vi.fn(), del: vi.fn() },
  api_base: () => "http://test.example/api",
  TOKEN_KEY: "token",
}));

vi.mock("@/auth", () => ({
  useAuth: () => ({
    user: { id: "u-admin", role: "admin", email: "a@x.co", name: "A" },
  }),
  AuthProvider: ({ children }) => <>{children}</>,
}));


const _RANGE = { start: "2026-02-01", end: "2026-02-28" };
const _ORPHAN_UUID = "2ad6d566-c6d5-467c-b608-8acb6c6fb6c9";


beforeEach(() => { vi.clearAllMocks(); });
afterEach(() => { cleanup(); });


describe("RevenueByCategoryTile · displayCategoryLabel wired into render", () => {
  it("coerces a raw UUID in ``category`` to 'Uncategorized' in the legend", async () => {
    // Simulate a hypothetical backend regression: legend/tooltip
    // ``category`` field carries a raw UUID (bypassing the id→name
    // resolver on the backend).  ``category_name`` also missing.
    apiGetMock.mockResolvedValue({
      items: [
        { category: _ORPHAN_UUID, amount: 100.0, count: 1,
          color: "#94A3B8", is_orphan: true },
        { category: "Pool", amount: 250.0, count: 2,
          color: "#3B82F6", is_orphan: false },
      ],
      total: 350.0, currency: "USD", range: _RANGE, orphan_ids: [_ORPHAN_UUID],
    });
    const { default: Tile } = await import(
      "@/components/dashboard/RevenueByCategoryTile"
    );
    render(<Tile range={_RANGE} />);
    // Legend text — UUID must be coerced to "Uncategorized".
    await waitFor(() => screen.getByTestId("revenue-cat-legend"));
    const legend = screen.getByTestId("revenue-cat-legend");
    expect(legend.textContent).toContain("Uncategorized");
    expect(legend.textContent).not.toContain(_ORPHAN_UUID);
    // Legend testid — must be based on the coerced label, not the
    // raw UUID (a test hitting ``revenue-cat-legend-Uncategorized``
    // is easier to grep than one with a random hex string).
    expect(screen.queryByTestId("revenue-cat-legend-Uncategorized"))
      .toBeInTheDocument();
    expect(screen.queryByTestId(`revenue-cat-legend-${_ORPHAN_UUID}`))
      .toBeNull();
    // Sibling "Pool" row still renders correctly (no over-coercion).
    expect(legend.textContent).toContain("Pool");
  });

  it("prefers ``category_name`` over ``category`` (post-Backlog-#ii response shape)", async () => {
    apiGetMock.mockResolvedValue({
      items: [
        // Backend returns BOTH — ``category_name`` is the truth,
        // ``category`` is the legacy alias.  The tile MUST use
        // ``category_name`` when present.
        { category: "legacy-value",
          category_name: "Pool",
          category_id: "sc-pool", amount: 500.0, count: 3,
          color: "#3B82F6", is_orphan: false },
      ],
      total: 500.0, currency: "USD", range: _RANGE, orphan_ids: [],
    });
    const { default: Tile } = await import(
      "@/components/dashboard/RevenueByCategoryTile"
    );
    render(<Tile range={_RANGE} />);
    await waitFor(() => screen.getByTestId("revenue-cat-legend"));
    const legend = screen.getByTestId("revenue-cat-legend");
    expect(legend.textContent).toContain("Pool");
    // Legacy alias must NOT surface.
    expect(legend.textContent).not.toContain("legacy-value");
  });

  it("coerces empty/blank ``category`` to 'Uncategorized' safely (no crash on legend key)", async () => {
    apiGetMock.mockResolvedValue({
      items: [
        { category: "", amount: 42.0, count: 1,
          color: "#94A3B8", is_orphan: false },
      ],
      total: 42.0, currency: "USD", range: _RANGE, orphan_ids: [],
    });
    const { default: Tile } = await import(
      "@/components/dashboard/RevenueByCategoryTile"
    );
    // If the tile ever tried ``item.category.replace(...)`` on a
    // blank string it would still work — but ``displayCategoryLabel``
    // maps blank → "Uncategorized" so the testid becomes
    // ``revenue-cat-legend-Uncategorized``.
    render(<Tile range={_RANGE} />);
    await waitFor(() => screen.getByTestId("revenue-cat-legend"));
    expect(screen.getByTestId("revenue-cat-legend-Uncategorized"))
      .toBeInTheDocument();
  });
});
