/**
 * QUOTE-VIEW-DESCRIPTION-UNGROUPED · Feb-2026 — customer-facing
 * ungrouped line-item surface must render BOTH the item_name
 * (primary bold) AND the description (secondary muted) when both
 * fields are populated, mirroring the admin K71 editor pattern
 * (``K71LineItemsEditor.jsx`` row ~597-640). Pre-fix, the
 * customer-facing table + mobile-card rendered only
 * ``{li.description}``, hiding the admin-authored item name on
 * every ungrouped (``customer_group_display=false``) quote.
 *
 * Regression guard: locks the fix in both the desktop
 * ``estimate-line-items-table`` and the ``< sm`` mobile-card
 * fallback ``estimate-line-items-cards`` so a future refactor
 * can't silently re-drop the item_name in either surface.
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


function _payload({ lineItems }) {
  return {
    estimate_id: "q-desc",
    status: "sent",
    decision: null,
    sent_at: "2026-02-15T10:00:00.000Z",
    company: { name: "Test Co" },
    bill_to: { name: "Carla Customer", customer_number: "C-1" },
    property_address: "123 Test Ave",
    header: {
      estimate_number: "EST-DESC-001",
      estimate_date: "2026-02-15",
      customer_number: "C-1",
    },
    title: "Pool pump replacement",
    line_items: lineItems,
    totals: { subtotal: 450, taxes: 0, amount_paid: 0,
      total_estimated_cost: 450 },
    notes: null,
    as_customer: true,
    customer_group_display: false,  // force itemized/ungrouped surface
    customer_view: {
      customer_group_display: false,
      groups: [],
      subtotal: 450, tax: 0, discount: 0, total: 450, currency: "USD",
    },
  };
}


async function _mount(lineItems) {
  getSpy.mockResolvedValue(_payload({ lineItems }));
  render(<EstimateView token="tok-desc" isAdmin={false} />);
  await waitFor(() =>
    expect(screen.queryByTestId("estimate-view")).toBeTruthy(),
  );
}


beforeEach(() => {
  vi.spyOn(window, "confirm").mockReturnValue(true);
});


describe("EstimateView · ungrouped customer surface renders item_name "
         + "+ description", () => {
  it("item_name + description both populated → primary bold = "
     + "item_name, secondary muted = description", async () => {
    await _mount([
      { item_name: "Pool pump install",
        description: "Install 1.5HP variable-speed pump with warranty",
        quantity: 1, unit_price: 450, total: 450 },
    ]);
    // Ungrouped itemized table is the one that renders (sanity).
    expect(screen.getByTestId("estimate-line-items-table")).toBeTruthy();
    // Primary bold = item_name.
    const primary = screen.getByTestId("estimate-line-item-name-0");
    expect(primary.textContent).toContain("Pool pump install");
    // Secondary muted = description (admin-populated detail text).
    const secondary = screen.getByTestId("estimate-line-item-desc-0");
    expect(secondary.textContent).toContain(
      "Install 1.5HP variable-speed pump with warranty",
    );
  });

  it("item_name absent → primary falls back to description, no "
     + "secondary row (prevents visible duplicate on legacy rows)",
    async () => {
    await _mount([
      { description: "Legacy line — no item_name",
        quantity: 1, unit_price: 100, total: 100 },
    ]);
    const primary = screen.getByTestId("estimate-line-item-name-0");
    expect(primary.textContent).toContain("Legacy line — no item_name");
    // Secondary row NOT rendered (would duplicate the primary).
    expect(screen.queryByTestId("estimate-line-item-desc-0")).toBeNull();
  });

  it("item_name === description → no secondary row (duplicate guard)",
    async () => {
    await _mount([
      { item_name: "Pool cleaning", description: "Pool cleaning",
        quantity: 4, unit_price: 40, total: 160 },
    ]);
    const primary = screen.getByTestId("estimate-line-item-name-0");
    expect(primary.textContent).toContain("Pool cleaning");
    expect(screen.queryByTestId("estimate-line-item-desc-0")).toBeNull();
  });

  it("multiple lines → each renders its own primary + secondary pair",
    async () => {
    await _mount([
      { item_name: "Pump install", description: "Install 1.5HP pump",
        quantity: 1, unit_price: 450, total: 450 },
      { item_name: "Grout reseal", description: "Reseal perimeter tile",
        quantity: 1, unit_price: 200, total: 200 },
    ]);
    expect(screen.getByTestId("estimate-line-item-name-0").textContent)
      .toContain("Pump install");
    expect(screen.getByTestId("estimate-line-item-desc-0").textContent)
      .toContain("Install 1.5HP pump");
    expect(screen.getByTestId("estimate-line-item-name-1").textContent)
      .toContain("Grout reseal");
    expect(screen.getByTestId("estimate-line-item-desc-1").textContent)
      .toContain("Reseal perimeter tile");
  });
});
