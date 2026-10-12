/**
 * Feb-2026 · Track 3 — public estimate view line-items table columns.
 *
 * Locks in the Track 3 fix shape:
 *
 *   1. Public (``as_customer: true``) ungrouped table renders the
 *      conventional quote layout:
 *          Description · Qty/Hr · Unit Price · Total
 *      No ``Visits`` column.
 *   2. Admin (``as_customer: false``) ungrouped table is unchanged
 *      — ``Visits`` still present, ``Unit Price`` NOT inserted
 *      (admin keeps its own cost/margin columns to the right).
 *   3. ``Unit Price`` cell renders the formatted ``li.unit_price``.
 *   4. ``Total`` cell applies the FE defense-in-depth fallback
 *      (``li.total ?? qty * unit_price``) when the API omits
 *      ``total``. Backend serializer now computes this fallback
 *      upstream; the FE guard protects against API regression.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";


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


function _branding() {
  return {
    tenant_id: "t-1",
    branding: {
      company_display_name: "AquaTerra",
      brand_primary_hex: "#0B4A6F",
    },
  };
}


function _basePayload(overrides = {}) {
  return {
    status: "sent",
    decision: null,
    company: { name: "AquaTerra" },
    bill_to: { name: "Alice", customer_number: "C-42" },
    property_address: "123 Main St",
    header: {
      estimate_number: "EST-2001",
      estimate_date: "2026-02-14",
      customer_number: "C-42",
    },
    title: "Pool service",
    notes: null,
    customer_view: null,          // force itemized path
    customer_group_display: false,
    totals: {
      subtotal: 275, taxes: 0, amount_paid: 0,
      total_estimated_cost: 275,
      has_declined_lines: false, declined_line_count: 0,
    },
    line_items: [
      // li.total already numeric → cell MUST use li.total (not FE fallback)
      { description: "Skimmer clean", quantity: 1,   unit_price: 100, total: 100,
        customer_status: "pending" },
      // li.total null → FE fallback MUST compute qty * unit_price = 125
      { description: "Chemicals",     quantity: 2.5, unit_price: 50,  total: null,
        customer_status: "pending" },
      // li.total MISSING key entirely → FE fallback MUST compute = 150
      { description: "Bush trim",     quantity: 3,   unit_price: 50,
        customer_status: "pending" },
    ],
    ...overrides,
  };
}


function _setupRouting(payload) {
  getSpy.mockImplementation((path) => {
    if (typeof path === "string"
        && path.includes("/portal/tenant/branding")) {
      return Promise.resolve(_branding());
    }
    if (typeof path === "string"
        && path.includes("/tenants/me/business-settings")) {
      return Promise.resolve({
        stored: _branding().branding,
        effective: _branding().branding,
      });
    }
    return Promise.resolve(payload);
  });
}


beforeEach(() => {
  getSpy.mockReset();
  patchSpy.mockReset();
  postSpy.mockReset();
});


describe("EstimateView · Track 3 — public line-items table columns", () => {
  it("public (as_customer=true) renders Description · Qty/Hr · Unit Price · Total; no Visits header", async () => {
    _setupRouting(_basePayload({ as_customer: true }));
    render(<EstimateView estimateId="q-1" token="tok-1" />);
    const thead = await screen.findByTestId("estimate-line-items-thead");
    const headers = Array.from(thead.querySelectorAll("th"))
      .map(th => th.textContent.trim());
    expect(headers).toContain("Description");
    expect(headers).toContain("Qty/Hr");
    expect(headers).toContain("Unit Price");
    expect(headers).toContain("Total");
    expect(headers).not.toContain("Visits");
    // Admin-only headers must NOT leak
    expect(headers).not.toContain("Cost/Rate");
    expect(headers).not.toContain("Margin %");
  });

  it("admin (as_customer=false) keeps Visits and does NOT inject Unit Price", async () => {
    _setupRouting(_basePayload({ as_customer: false }));
    render(<EstimateView estimateId="q-1" token="tok-1" />);
    const thead = await screen.findByTestId("estimate-line-items-thead");
    const headers = Array.from(thead.querySelectorAll("th"))
      .map(th => th.textContent.trim());
    expect(headers).toContain("Visits");
    expect(headers).not.toContain("Unit Price");
    // Admin cost/margin columns stay
    expect(headers).toContain("Cost/Rate");
    expect(headers).toContain("Margin %");
  });

  it("public unit-price cell renders formatCurrency(li.unit_price) for every row", async () => {
    _setupRouting(_basePayload({ as_customer: true }));
    render(<EstimateView estimateId="q-1" token="tok-1" />);
    await screen.findByTestId("estimate-line-items-thead");
    // Row 0: unit_price=100 → "$100.00"
    expect(screen.getByTestId("estimate-line-item-unit-price-0").textContent)
      .toMatch(/\$100\.00/);
    // Row 1: unit_price=50 → "$50.00"
    expect(screen.getByTestId("estimate-line-item-unit-price-1").textContent)
      .toMatch(/\$50\.00/);
    // Row 2: unit_price=50 → "$50.00"
    expect(screen.getByTestId("estimate-line-item-unit-price-2").textContent)
      .toMatch(/\$50\.00/);
  });

  it("Total cell: uses li.total when present (row 0), falls back to qty * unit_price when null/missing (rows 1, 2)", async () => {
    _setupRouting(_basePayload({ as_customer: true }));
    render(<EstimateView estimateId="q-1" token="tok-1" />);
    await screen.findByTestId("estimate-line-items-thead");
    // Row 0: li.total=100 → "$100.00"
    expect(screen.getByTestId("estimate-line-item-total-0").textContent)
      .toMatch(/\$100\.00/);
    // Row 1: li.total=null → fallback qty 2.5 * 50 = 125 → "$125.00"
    expect(screen.getByTestId("estimate-line-item-total-1").textContent)
      .toMatch(/\$125\.00/);
    // Row 2: li.total missing → fallback qty 3 * 50 = 150 → "$150.00"
    expect(screen.getByTestId("estimate-line-item-total-2").textContent)
      .toMatch(/\$150\.00/);
  });
});
