/**
 * Phase K79-TOGGLE · Feb-2026 — EstimateView grouped-vs-itemized
 * customer branch. Locks the un-lock:
 *
 *   * ``customer_group_display=true``  + ``as_customer``  → grouped
 *                                                          table
 *   * ``customer_group_display=false`` + ``as_customer``  → itemized
 *                                                          customer
 *                                                          table
 *   * field absent / null              + ``as_customer``  → grouped
 *                                                          (legacy)
 *
 * Admin (``as_customer: false``) always renders the full itemized
 * table regardless of the toggle — regression guard.
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

// Keep the tenant-branding hooks quiet so the surface renders
// without hitting the network.
vi.mock("@/hooks/useTenantBranding", () => ({
  useTenantBranding: () => ({ branding: null }),
  useBusinessSettings: () => ({ branding: null }),
}));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  getSpy.mockReset();
  postSpy.mockReset();
});


import EstimateView from "@/components/EstimateView";


function _payload({ customerGroupDisplay, asCustomer = true } = {}) {
  const base = {
    estimate_id: "q-tog",
    status: "sent",
    decision: null,
    sent_at: "2026-02-15T10:00:00.000Z",
    company: { name: "Test Co" },
    bill_to: { name: "Robert Blake", customer_number: "C-1" },
    property_address: "123 Test Ave",
    header: {
      estimate_number: "EST-TOG-001",
      estimate_date: "2026-02-15",
      customer_number: "C-1",
    },
    title: "Pool + Grout job",
    line_items: [
      { description: "Pool cleaning", quantity: 4, unit_price: 40,
        total: 160 },
      { description: "Grout resealing", quantity: 1, unit_price: 200,
        total: 200 },
    ],
    totals: {
      subtotal: 360, taxes: 30, amount_paid: 0,
      total_estimated_cost: 390,
    },
    notes: null,
    as_customer: asCustomer,
    customer_view: {
      customer_group_display: customerGroupDisplay,
      groups: [
        { category_id: "cat-pool", label: "Pool Service",
          description: "Weekly service.", subtotal: 160 },
        { category_id: "cat-tile", label: "Tile & Grout",
          description: "One-time job.", subtotal: 200 },
      ],
      subtotal: 360, tax: 30, discount: 0, total: 390,
      currency: "USD",
    },
  };
  // Only attach the field when explicitly asked — omitted means
  // legacy record (undefined at the top level).
  if (customerGroupDisplay !== undefined) {
    base.customer_group_display = customerGroupDisplay;
  }
  return base;
}


beforeEach(() => {
  vi.spyOn(window, "confirm").mockReturnValue(true);
});


async function _renderMagicLink(overrides = {}) {
  getSpy.mockResolvedValue(_payload(overrides));
  render(<EstimateView token="tok-live" isAdmin={false} />);
  await waitFor(() =>
    expect(screen.queryByTestId("estimate-view")).toBeTruthy(),
  );
}


describe("EstimateView · K79-TOGGLE grouped/itemized switch", () => {
  it("customer + toggle=true → grouped table renders", async () => {
    await _renderMagicLink({ customerGroupDisplay: true });
    expect(screen.getByTestId("estimate-grouped-lines-table")).toBeTruthy();
    expect(screen.getByTestId("estimate-grouped-row-cat-pool")).toBeTruthy();
    expect(screen.getByTestId("estimate-grouped-row-cat-tile")).toBeTruthy();
    // Itemized customer table is NOT rendered.
    expect(screen.queryByTestId("estimate-line-items-table")).toBeNull();
  });

  it("customer + toggle=false → itemized customer table renders",
    async () => {
    await _renderMagicLink({ customerGroupDisplay: false });
    // Itemized table present.
    expect(screen.getByTestId("estimate-line-items-table")).toBeTruthy();
    // Raw line-item rows appear.
    expect(screen.getByTestId("estimate-line-item-row-0")).toBeTruthy();
    expect(screen.getByTestId("estimate-line-item-row-1")).toBeTruthy();
    // Grouped table is NOT rendered.
    expect(screen.queryByTestId("estimate-grouped-lines-table")).toBeNull();
  });

  it("customer + field undefined → grouped table (legacy default)",
    async () => {
    // customerGroupDisplay is intentionally omitted here so the
    // top-level ``customer_group_display`` is undefined on the doc.
    await _renderMagicLink({ customerGroupDisplay: undefined });
    expect(screen.getByTestId("estimate-grouped-lines-table")).toBeTruthy();
    expect(screen.queryByTestId("estimate-line-items-table")).toBeNull();
  });

  it("customer + field=null → grouped table (legacy default)", async () => {
    await _renderMagicLink({ customerGroupDisplay: null });
    expect(screen.getByTestId("estimate-grouped-lines-table")).toBeTruthy();
    expect(screen.queryByTestId("estimate-line-items-table")).toBeNull();
  });

  it("admin (as_customer=false) always renders itemized table "
     + "regardless of toggle", async () => {
    // Even with customer_group_display=true, admin surface must
    // render the itemized 4+column table.
    await _renderMagicLink({
      customerGroupDisplay: true, asCustomer: false,
    });
    expect(screen.getByTestId("estimate-line-items-table")).toBeTruthy();
    expect(screen.queryByTestId("estimate-grouped-lines-table")).toBeNull();
  });

  // BUG REGRESSION · Feb-2026 — The real backend ``_build_payload``
  // shape has ``customer_group_display`` at BOTH the top level AND
  // nested under ``customer_view``. Pre-fix, it was ONLY nested,
  // so the frontend read ``data?.customer_group_display`` as
  // ``undefined`` and defaulted to grouped on every magic-link
  // customer page. This case locks that both toggle positions
  // produce the correct table against the real payload shape.
  it.each([
    { label: "false (admin toggled OFF)", cgd: false,
      want: "estimate-line-items-table",
      forbidden: "estimate-grouped-lines-table" },
    { label: "true  (admin toggled ON)",  cgd: true,
      want: "estimate-grouped-lines-table",
      forbidden: "estimate-line-items-table" },
  ])(
    "real _build_payload shape (top-level + nested present) · $label "
    + "renders the correct table",
    async ({ cgd, want, forbidden }) => {
      // Assert the fixture produces the real shape: top-level + nested
      // both populated with the same value (what _build_payload emits
      // post-fix).
      const p = _payload({ customerGroupDisplay: cgd });
      expect(p).toHaveProperty("customer_group_display", cgd);
      expect(p.customer_view).toHaveProperty("customer_group_display", cgd);
      // Mount and verify the expected table renders.
      getSpy.mockResolvedValue(p);
      render(<EstimateView token="tok-realshape" isAdmin={false} />);
      await waitFor(() =>
        expect(screen.queryByTestId("estimate-view")).toBeTruthy(),
      );
      expect(screen.getByTestId(want)).toBeTruthy();
      expect(screen.queryByTestId(forbidden)).toBeNull();
    },
  );
});
