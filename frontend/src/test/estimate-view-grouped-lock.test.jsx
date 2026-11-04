/**
 * EstimateView · Feb-2026 · Grouped-layout LOCK-ON ship.
 *
 * Locks the three-bug fix documented in
 * ``/app/memory/FEATURE_QUOTE_CUSTOMER_VIEW_GROUPED.md``:
 *
 *   1. Grouped layout is always ON for customer-facing surfaces
 *      (magic-link, portal, PDF). The ``customer_group_display``
 *      toggle is a no-op for rendering, and the "force itemized on
 *      actionable magic-link" carve-out is retired.
 *   2. Prices in grouped rows come from server-computed subtotals
 *      (never $0.00 when the underlying line items have prices).
 *   3. Per-line Decline buttons are removed from the customer view.
 *      A single "Decline Quote" button renders at the bottom of the
 *      view (in addition to the existing top-toolbar Decline button).
 *
 * Admin surface (``as_customer: false``) is untouched — this test
 * only exercises the customer path.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";

const { getSpy, postSpy } = vi.hoisted(() => ({
  getSpy: vi.fn(),
  postSpy: vi.fn(),
}));

vi.mock("@/api", () => ({
  TOKEN_KEY: "token",
  api: {
    get: (...a) => getSpy(...a),
    post: (...a) => postSpy(...a),
  },
}));

vi.mock("react-router-dom", () => ({
  useNavigate: () => vi.fn(),
}));

beforeEach(() => {
  vi.spyOn(window, "confirm").mockReturnValue(true);
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  getSpy.mockReset();
  postSpy.mockReset();
});

import EstimateView from "@/components/EstimateView";


function _payload(overrides = {}) {
  return {
    estimate_id: "q-lock",
    status: "sent",
    decision: null,
    sent_at: "2026-02-09T10:00:00.000Z",
    company: { name: "Test Co" },
    bill_to: { name: "Cust", customer_number: "C-1" },
    property_address: "123 Test",
    header: {
      estimate_number: "EST-LOCK-001", estimate_date: "2026-02-09",
      customer_number: "C-1",
    },
    title: "Backyard Overhaul",
    line_items: [
      // Real line items with a total field the itemized fallback
      // would zero out (matches the reported bug's data shape).
      { description: "Pavers", quantity: 100, unit_price: 40, total: 0 },
      { description: "Poly Sand", quantity: 8, unit_price: 25, total: 0 },
      { description: "Turf", quantity: 50, unit_price: 15, total: 0 },
    ],
    totals: {
      subtotal: 4950, taxes: 495, amount_paid: 0,
      total_estimated_cost: 5445,
    },
    notes: null,
    as_customer: true,
    // Feb-2026 · grouped-lock: the customer_view block is what the
    // backend embeds via _build_payload → build_customer_view_payload.
    // customer_group_display=FALSE here on purpose — proves the
    // frontend no longer honors the toggle.
    customer_view: {
      customer_group_display: false,
      groups: [
        { category_id: "cat-hardscape", label: "Hardscaping",
          description: "Pavers + poly sand", subtotal: 4200 },
        { category_id: "cat-plants", label: "Plants & Turf",
          description: "Drought-tolerant mix.", subtotal: 750 },
      ],
      subtotal: 4950, tax: 495, discount: 0, total: 5445,
      currency: "USD",
    },
    ...overrides,
  };
}


async function _renderMagicLink(overrides = {}) {
  getSpy.mockResolvedValue(_payload(overrides));
  render(<EstimateView token="tok-live" isAdmin={false} />);
  await waitFor(() =>
    expect(screen.queryByTestId("estimate-view")).toBeTruthy(),
  );
}


describe("EstimateView · grouped-layout LOCK-ON", () => {
  it("renders the grouped table on customer magic-link even when "
        + "customer_group_display is FALSE", async () => {
    await _renderMagicLink();
    // Grouped rows present (data-testid pattern from EstimateView).
    expect(screen.getByTestId("estimate-grouped-row-cat-hardscape"))
      .toBeTruthy();
    expect(screen.getByTestId("estimate-grouped-row-cat-plants"))
      .toBeTruthy();
    // Itemized fallback table is NOT rendered.
    expect(screen.queryByTestId("estimate-line-items-table")).toBeNull();
    // Group descriptions surface.
    expect(screen.getByTestId("estimate-grouped-desc-cat-hardscape")
                   .textContent).toContain("Pavers + poly sand");
  });

  it("group subtotals show real prices (not $0.00)", async () => {
    await _renderMagicLink();
    const hardscape = screen.getByTestId("estimate-grouped-row-cat-hardscape");
    const plants = screen.getByTestId("estimate-grouped-row-cat-plants");
    // Subtotals: 4200 and 750 — must appear formatted, must NOT be 0.00.
    // Feb-2026 · currency standardization — the canonical
    // formatCurrency helper emits ``$4,200.00`` / ``$750.00`` (comma-
    // grouped 2-decimal). Match on the comma-grouped fragment so
    // this passes without over-fitting to the exact $ prefix.
    expect(hardscape.textContent).toContain("4,200.00");
    expect(plants.textContent).toContain("750.00");
    // No standalone "$0.00" subtotal cell (the reported bug's symptom).
    // ``$4,200.00`` legitimately contains ``0.00`` as a substring so
    // we scope the negative assertion to the row's numeric cell,
    // and match on the new comma-grouped shape.
    const hardscapeNumCell = hardscape.querySelector("td.iv-num");
    expect(hardscapeNumCell.textContent.trim()).not.toBe("$0.00");
    const plantsNumCell = plants.querySelector("td.iv-num");
    expect(plantsNumCell.textContent.trim()).not.toBe("$0.00");
    // Doc-level total — 5445 renders as ``$5,445.00``.
    expect(screen.getByTestId("estimate-totals-cost").textContent)
      .toContain("5,445");
  });

  it("does NOT render per-line Decline buttons on the customer view",
    async () => {
    await _renderMagicLink();
    // None of the per-line decline testids should be present.
    expect(screen.queryByTestId("estimate-line-item-decline-0")).toBeNull();
    expect(screen.queryByTestId("estimate-line-item-decline-1")).toBeNull();
    expect(screen.queryByTestId("estimate-line-item-decline-2")).toBeNull();
  });

  it("renders NO whole-estimate Decline button on the customer view "
        + "(TD-decline-whole-remove)", async () => {
    // TD-estimate-public-decline-whole-remove-plus-reason-optional ·
    // Feb-2026 — every whole-estimate Decline CTA was removed from
    // the customer surface.  The grouped-layout per-group decline
    // buttons at ``:856+`` remain as the customer's only decline
    // path on this surface.
    await _renderMagicLink();
    expect(screen.queryByTestId("estimate-bottom-decline-quote-btn"))
      .toBeNull();
    expect(screen.queryByTestId("estimate-toolbar-customer-decline"))
      .toBeNull();
    expect(screen.queryByTestId("estimate-mobile-decline-btn"))
      .toBeNull();
  });

  it("hides the bottom Decline button once the doc is locked "
        + "(accepted/declined)", async () => {
    await _renderMagicLink({
      status: "accepted", decision: "accepted",
      accepted_at: "2026-02-10",
    });
    expect(screen.queryByTestId("estimate-bottom-decline-quote-btn"))
      .toBeNull();
  });

  it("hides the bottom Decline button on non-actionable statuses "
        + "(e.g. draft)", async () => {
    await _renderMagicLink({ status: "draft" });
    expect(screen.queryByTestId("estimate-bottom-decline-quote-btn"))
      .toBeNull();
  });
});
