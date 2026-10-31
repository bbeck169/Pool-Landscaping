/**
 * Feb-2026 · TD-revenue-by-category-id-grouping · FE vitest.
 *
 * Covers the three operator-reported bugs on the Revenue by Category
 * tile + drill-down bridge:
 *
 *   • Bug A — drill-down category edit invalidates the tile cache.
 *     The tile mounts the modal with ``onEdited``; firing it bumps
 *     ``refetchNonce`` which retriggers the aggregation GET.
 *   • Bug B — grouping by FK is contract-stable.  The tile keys
 *     each legend row by ``bucket_key`` (not by display name) so
 *     React stability + wire-up for name-colliding buckets stays
 *     correct.
 *   • Bug C — legend click forwards the stable ``bucket_key`` to
 *     the drill-down modal, which forwards it to the BE under the
 *     ``category_key`` query param.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  render, screen, fireEvent, waitFor,
} from "@testing-library/react";


const _getMock = vi.fn();
vi.mock("@/api", () => ({
  api: { get: (...a) => _getMock(...a) },
}));
vi.mock("@/components/dashboard/DashboardDrillDownModal", () => ({
  __esModule: true,
  default: ({ open, params, onEdited }) => (
    open ? (
      <div
        data-testid="drilldown-modal-stub"
        data-category={params?.category || ""}
        data-category-key={params?.category_key || ""}
        data-from={params?.from || ""}
        data-to={params?.to || ""}
      >
        <button
          type="button"
          data-testid="drilldown-stub-fire-edit"
          onClick={() =>
            onEdited?.(
              { invoice_id: "iv1", line_index: 0 },
              "income_category_id",
              "before-id",
              "after-id",
            )
          }
        >
          fire edit
        </button>
      </div>
    ) : null
  ),
}));

import RevenueByCategoryTile from "@/components/dashboard/RevenueByCategoryTile";


const _tilePayload = (overrides = {}) => ({
  items: [
    {
      category: "Landscaping",
      category_name: "Landscaping",
      category_id: "ic-landscape",
      bucket_key: "id:ic-landscape",
      amount: 500,
      count: 2,
      color: "#aabbcc",
      is_orphan: false,
    },
    {
      category: "Hardscaping",
      category_name: "Hardscaping",
      category_id: "ic-hardscape",
      bucket_key: "id:ic-hardscape",
      amount: 300,
      count: 1,
      color: "#ddee11",
      is_orphan: false,
    },
    {
      category: "LegacyNameOnly",
      category_name: "LegacyNameOnly",
      category_id: null,
      bucket_key: "name:legacynameonly",
      amount: 100,
      count: 1,
      color: "#223344",
      is_orphan: false,
    },
  ],
  total: 900,
  currency: "USD",
  range: { start: "2026-06-01", end: "2026-06-30" },
  ...overrides,
});


describe("RevenueByCategoryTile · TD-revenue-by-category-id-grouping", () => {
  beforeEach(() => {
    _getMock.mockReset();
    _getMock.mockResolvedValue(_tilePayload());
  });

  it("fetches aggregation and renders one legend row per bucket", async () => {
    render(<RevenueByCategoryTile
      range={{ start: "2026-06-01", end: "2026-06-30" }} />);
    await waitFor(() => {
      expect(screen.getByTestId("revenue-cat-legend")).toBeInTheDocument();
    });
    expect(screen.getByTestId("revenue-cat-legend-Landscaping"))
      .toBeInTheDocument();
    expect(screen.getByTestId("revenue-cat-legend-Hardscaping"))
      .toBeInTheDocument();
    expect(screen.getByTestId("revenue-cat-legend-LegacyNameOnly"))
      .toBeInTheDocument();
  });

  it("Bug C · legend click forwards the stable bucket_key to the "
      + "drill-down modal, not the display name alone", async () => {
    render(<RevenueByCategoryTile
      range={{ start: "2026-06-01", end: "2026-06-30" }} />);
    await waitFor(() => {
      expect(screen.getByTestId("revenue-cat-legend-Hardscaping"))
        .toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId("revenue-cat-legend-Hardscaping"));
    const modal = screen.getByTestId("drilldown-modal-stub");
    expect(modal.getAttribute("data-category")).toBe("Hardscaping");
    expect(modal.getAttribute("data-category-key"))
      .toBe("id:ic-hardscape");
  });

  it("Bug C · non-FK buckets forward their synthetic key "
      + "(name:<lower>) so the drill-down filters without colliding",
      async () => {
    render(<RevenueByCategoryTile
      range={{ start: "2026-06-01", end: "2026-06-30" }} />);
    await waitFor(() => {
      expect(screen.getByTestId("revenue-cat-legend-LegacyNameOnly"))
        .toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId("revenue-cat-legend-LegacyNameOnly"));
    const modal = screen.getByTestId("drilldown-modal-stub");
    expect(modal.getAttribute("data-category-key"))
      .toBe("name:legacynameonly");
  });

  it("Bug A · drill-down category edit invalidates the tile cache "
      + "and refetches aggregation", async () => {
    render(<RevenueByCategoryTile
      range={{ start: "2026-06-01", end: "2026-06-30" }} />);
    await waitFor(() => {
      expect(_getMock).toHaveBeenCalledTimes(1);
    });
    fireEvent.click(screen.getByTestId("revenue-cat-legend-Hardscaping"));
    expect(screen.getByTestId("drilldown-modal-stub"))
      .toBeInTheDocument();
    // Fire the modal's ``onEdited`` the way the real IncomeRow
    // does on a successful line-item category save.  The tile
    // must refetch — nonce-bump drives a second GET.
    fireEvent.click(screen.getByTestId("drilldown-stub-fire-edit"));
    await waitFor(() => {
      expect(_getMock).toHaveBeenCalledTimes(2);
    });
  });

  it("Bug A · each successive edit triggers a refetch (nonce "
      + "increments monotonically; no stale cache)", async () => {
    render(<RevenueByCategoryTile
      range={{ start: "2026-06-01", end: "2026-06-30" }} />);
    await waitFor(() => { expect(_getMock).toHaveBeenCalledTimes(1); });
    fireEvent.click(screen.getByTestId("revenue-cat-legend-Landscaping"));
    fireEvent.click(screen.getByTestId("drilldown-stub-fire-edit"));
    await waitFor(() => { expect(_getMock).toHaveBeenCalledTimes(2); });
    fireEvent.click(screen.getByTestId("drilldown-stub-fire-edit"));
    await waitFor(() => { expect(_getMock).toHaveBeenCalledTimes(3); });
  });

  it("Bug B · duplicate display names across buckets render as "
      + "distinct rows keyed by bucket_key (React identity)",
      async () => {
    // Simulates the pre-migration state where the FE still receives
    // two buckets with the same display name because the BE grouped
    // by name (ONLY possible if a caller sends a stale payload).
    // The React ``key`` must be ``bucket_key`` so both rows render
    // without a dev-mode duplicate-key warning.
    const warnSpy = vi.spyOn(console, "error")
      .mockImplementation(() => {});
    _getMock.mockReset();
    _getMock.mockResolvedValue({
      items: [
        {
          category: "Landscape", category_name: "Landscape",
          category_id: null, bucket_key: "name:landscape",
          amount: 100, count: 1, color: "#111", is_orphan: false,
        },
        {
          category: "Landscape", category_name: "Landscape",
          category_id: "ic-landscape",
          bucket_key: "id:ic-landscape",
          amount: 200, count: 2, color: "#222", is_orphan: false,
        },
      ],
      total: 300, currency: "USD",
      range: { start: "2026-06-01", end: "2026-06-30" },
    });
    render(<RevenueByCategoryTile
      range={{ start: "2026-06-01", end: "2026-06-30" }} />);
    await waitFor(() => {
      expect(screen.getByTestId("revenue-cat-legend")).toBeInTheDocument();
    });
    // Both rows render; React keyed on bucket_key avoids dev
    // "Encountered two children with the same key" warning that
    // would fire if the key fell back to the display name.
    const landscapeRows = screen.getAllByTestId(
      /^revenue-cat-legend-Landscape$/,
    );
    expect(landscapeRows).toHaveLength(2);
    const dupKeyWarning = warnSpy.mock.calls.find((args) =>
      String(args[0] || "").includes("same key"));
    expect(dupKeyWarning).toBeUndefined();
    warnSpy.mockRestore();
  });
});
