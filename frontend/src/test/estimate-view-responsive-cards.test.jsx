/**
 * Feb-2026 · Responsive Quote / Estimate — customer-facing
 * ``EstimateView`` stacked-card fallback below Tailwind ``sm``
 * (< 640px).
 *
 * The desktop line-items table stays authoritative at ≥ 640px;
 * this test locks in the parallel stacked-card block that
 * mirrors the same data at < 640px so the Decline button stays
 * reachable at 375px viewports without horizontal scroll.
 *
 * Coverage (JSDOM-only — CSS media queries do not resolve, so
 * we assert on BOTH surfaces being in the DOM with the correct
 * Tailwind gate classes; the classes themselves are the
 * viewport contract):
 *
 *   1. Grouped-lines path renders the desktop ``<table>`` with
 *      ``hidden sm:table`` AND a parallel ``<ul>`` with
 *      ``sm:hidden`` carrying the same groups.
 *   2. Each grouped card renders a mobile Decline button under
 *      the ``estimate-grouped-decline-btn-mobile-<cat>`` testid
 *      that fires the same ``declineGroup`` PATCH as the
 *      desktop button.
 *   3. Itemized fallback path renders both the desktop table
 *      AND the ``estimate-line-items-cards`` list.
 *   4. Totals block subtotal + total-estimated-cost testids
 *      resolve unchanged.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

const { getSpy, patchSpy, postSpy } = vi.hoisted(() => ({
  getSpy: vi.fn(),
  patchSpy: vi.fn(),
  postSpy: vi.fn(),
}));

vi.mock("@/api", () => ({
  TOKEN_KEY: "token",
  api_base: () => "http://localhost/api",
  api: {
    get: (...a) => getSpy(...a),
    post: (...a) => postSpy(...a),
    patch: (...a) => patchSpy(...a),
    del: vi.fn(),
  },
}));

vi.mock("react-router-dom", () => ({
  useNavigate: () => vi.fn(),
  useParams: () => ({ id: "q-1" }),
}));

vi.mock("@/theme", () => ({
  colors: {
    brand: "#0B4A6F",
    muted: "#6B7280",
    onSurface: "#111827",
    border: "#E5E7EB",
    surface: "#FFFFFF",
  },
  money: (n) => `$${Number(n || 0).toFixed(2)}`,
}));

import EstimateView from "@/components/EstimateView";


function _groupedPayload() {
  return {
    status: "sent",
    decision: null,
    company: { name: "AquaTerra" },
    bill_to: { name: "Alice", customer_number: "C-42" },
    property_address: "123 Main St",
    header: {
      estimate_number: "EST-1001",
      estimate_date: "2026-02-14",
      customer_number: "C-42",
    },
    title: "Backyard makeover",
    line_items: [],
    totals: {
      subtotal: 6600, taxes: 528, amount_paid: 0,
      total_estimated_cost: 7128,
      has_declined_lines: false, declined_line_count: 0,
    },
    notes: null,
    as_customer: true,
    customer_view: {
      customer_group_display: true,
      groups: [
        { category_id: "cat-hardscape", group_key: "grp-hardscape",
          label: "Hardscape", description: "Paver patio",
          subtotal: 5400, active_subtotal: 5400,
          declined: false, declined_at: null },
        { category_id: "cat-plants", group_key: "grp-plants",
          label: "Plants", description: "Native beds",
          subtotal: 1200, active_subtotal: 1200,
          declined: false, declined_at: null },
      ],
      subtotal: 6600, tax: 528, discount: 0, total: 7128,
      grouped_subtotal: 6600, grouped_active_subtotal: 6600,
      has_declined_groups: false, currency: "USD",
    },
  };
}


function _itemizedPayload() {
  const g = _groupedPayload();
  return {
    ...g,
    // Grouped-layout LOCK-ON is customer-only; admin/staff view
    // still exercises the itemized fallback so we drop
    // ``as_customer`` + ``customer_view`` to force that path.
    as_customer: false,
    customer_view: null,
    line_items: [
      { description: "Site prep", qty_hr: 8, visits: 1, total: 600,
        customer_status: "pending" },
      { description: "Planting",  qty_hr: 4, visits: 1, total: 400,
        customer_status: "pending" },
    ],
  };
}


function _brandingResp() {
  return {
    tenant_id: "t-1",
    branding: {
      company_display_name: "AquaTerra",
      brand_primary_hex: "#0B4A6F",
    },
  };
}


function _setupRouting(estimatePayload) {
  getSpy.mockImplementation((path) => {
    if (typeof path === "string"
        && path.includes("/portal/tenant/branding")) {
      return Promise.resolve(_brandingResp());
    }
    if (typeof path === "string"
        && path.includes("/tenants/me/business-settings")) {
      return Promise.resolve({
        stored: _brandingResp().branding,
        effective: _brandingResp().branding,
      });
    }
    return Promise.resolve(estimatePayload);
  });
}


beforeEach(() => {
  getSpy.mockReset();
  patchSpy.mockReset();
  postSpy.mockReset();
  // Return the current fixture on PATCH so ``setData(r)`` inside
  // ``declineGroup`` / ``restoreGroup`` doesn't clobber ``data``
  // and crash the reconciler on the next render.
  patchSpy.mockResolvedValue(_groupedPayload());
});


describe("EstimateView · responsive stacked cards (< sm)", () => {
  it("grouped: desktop table has 'hidden sm:table', mobile list has 'sm:hidden'", async () => {
    _setupRouting(_groupedPayload());
    render(<EstimateView estimateId="q-1" token="tok-1" />);
    const table = await screen.findByTestId("estimate-grouped-lines-table");
    expect(table.className).toMatch(/\bhidden\b/);
    expect(table.className).toMatch(/\bsm:table\b/);
    const cards = screen.getByTestId("estimate-grouped-lines-cards");
    expect(cards.className).toMatch(/\bsm:hidden\b/);
  });

  it("grouped: each mobile card exposes a Decline button with a distinct testid", async () => {
    _setupRouting(_groupedPayload());
    render(<EstimateView estimateId="q-1" token="tok-1" />);
    await screen.findByTestId("estimate-grouped-lines-cards");
    const hardBtn = screen.getByTestId(
      "estimate-grouped-decline-btn-mobile-cat-hardscape",
    );
    const plantsBtn = screen.getByTestId(
      "estimate-grouped-decline-btn-mobile-cat-plants",
    );
    expect(hardBtn.textContent).toMatch(/decline/i);
    expect(plantsBtn.textContent).toMatch(/decline/i);
    // Original desktop testids stay resolvable (unchanged contract).
    expect(screen.getByTestId(
      "estimate-grouped-decline-btn-cat-hardscape")).toBeTruthy();
    expect(screen.getByTestId(
      "estimate-grouped-decline-btn-cat-plants")).toBeTruthy();
  });

  it("grouped: clicking the mobile Decline button PATCHes the same group endpoint", async () => {
    _setupRouting(_groupedPayload());
    render(<EstimateView estimateId="q-1" token="tok-1" />);
    const btn = await screen.findByTestId(
      "estimate-grouped-decline-btn-mobile-cat-hardscape",
    );
    fireEvent.click(btn);
    await waitFor(() => expect(patchSpy).toHaveBeenCalled());
    const call = patchSpy.mock.calls[0];
    expect(call[0]).toMatch(/\/groups\/grp-hardscape\/decline/);
  });

  it("itemized fallback: desktop table + mobile card list both in DOM with correct gates", async () => {
    _setupRouting(_itemizedPayload());
    render(<EstimateView estimateId="q-1" token="tok-1" />);
    const table = await screen.findByTestId("estimate-line-items-table");
    expect(table.className).toMatch(/\bhidden\b/);
    expect(table.className).toMatch(/\bsm:table\b/);
    const cards = screen.getByTestId("estimate-line-items-cards");
    expect(cards.className).toMatch(/\bsm:hidden\b/);
    expect(screen.getByTestId("estimate-line-item-card-0")).toBeTruthy();
    expect(screen.getByTestId("estimate-line-item-card-1")).toBeTruthy();
  });

  it("totals block subtotal + total-estimated-cost testids resolve unchanged", async () => {
    _setupRouting(_groupedPayload());
    render(<EstimateView estimateId="q-1" token="tok-1" />);
    expect(await screen.findByTestId("estimate-totals-subtotal")).toBeTruthy();
    expect(screen.getByTestId("estimate-totals-cost")).toBeTruthy();
  });
});
