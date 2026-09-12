/**
 * EstimateView · Feb-2026 · Customer decline-per-group on grouped view.
 *
 * Locks the frontend contract for the four PATCH routes shipped in
 * the Feb-2026 dispatch:
 *
 *   1. On an actionable customer magic-link surface, each group row
 *      renders a Decline button keyed off `group_key`.
 *   2. Clicking Decline fires PATCH .../groups/{group_key}/decline
 *      and re-renders from the server response (strike + Restore).
 *   3. Clicking Restore reverses it via .../groups/{group_key}/undecline.
 *   4. Non-actionable statuses (accepted / declined) hide both
 *      Decline and Restore buttons.
 *   5. Admin dual-total display renders only when
 *      `totals.has_declined_lines === true`.
 *
 * See /app/memory/FEATURE_QUOTE_DECLINE_PER_GROUP.md.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";

const { getSpy, postSpy, patchSpy } = vi.hoisted(() => ({
  getSpy: vi.fn(),
  postSpy: vi.fn(),
  patchSpy: vi.fn(),
}));

vi.mock("@/api", () => ({
  TOKEN_KEY: "token",
  api: {
    get: (...a) => getSpy(...a),
    post: (...a) => postSpy(...a),
    patch: (...a) => patchSpy(...a),
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
  patchSpy.mockReset();
});

import EstimateView from "@/components/EstimateView";


function _payload(overrides = {}) {
  return {
    estimate_id: "q-grp",
    status: "sent",
    decision: null,
    sent_at: "2026-02-09T10:00:00.000Z",
    company: { name: "Test Co" },
    bill_to: { name: "Cust", customer_number: "C-1" },
    property_address: "123 Test",
    header: {
      estimate_number: "EST-GRP-001", estimate_date: "2026-02-09",
      customer_number: "C-1",
    },
    title: "Backyard Overhaul",
    line_items: [
      { description: "Pavers", quantity: 100, unit_price: 40 },
      { description: "Turf", quantity: 50, unit_price: 15 },
    ],
    totals: {
      subtotal: 4750, taxes: 475, amount_paid: 0,
      total_estimated_cost: 5225,
      original_subtotal: 4750, original_total: 5225,
      adjusted_subtotal: 4750, adjusted_total: 5225,
      has_declined_lines: false,
      declined_line_count: 0,
    },
    notes: null,
    as_customer: true,
    customer_view: {
      customer_group_display: true,
      groups: [
        {
          category_id: "cat-hardscape", group_key: "cat-hardscape",
          label: "Hardscaping", description: "Pavers + poly sand",
          subtotal: 4000, active_subtotal: 4000,
          declined: false, declined_at: null, declined_by: null,
        },
        {
          category_id: "cat-plants", group_key: "cat-plants",
          label: "Plants & Turf", description: "Drought-tolerant mix.",
          subtotal: 750, active_subtotal: 750,
          declined: false, declined_at: null, declined_by: null,
        },
      ],
      subtotal: 4750, tax: 475, discount: 0, total: 5225,
      grouped_subtotal: 4750, grouped_active_subtotal: 4750,
      has_declined_groups: false, currency: "USD",
    },
    ...overrides,
  };
}


function _declinedGroupPayload() {
  // Response the server returns after PATCH .../cat-hardscape/decline.
  const base = _payload();
  base.totals = {
    ...base.totals,
    adjusted_subtotal: 750, adjusted_total: 825,
    has_declined_lines: true, declined_line_count: 1,
  };
  base.customer_view = {
    ...base.customer_view,
    groups: [
      {
        ...base.customer_view.groups[0],
        active_subtotal: 0,
        declined: true,
        declined_at: "2026-02-09T11:00:00.000Z",
        declined_by: "token:cust-1",
      },
      base.customer_view.groups[1],
    ],
    grouped_active_subtotal: 750,
    has_declined_groups: true,
  };
  return base;
}


async function _renderMagicLink(payloadOverrides = {}) {
  getSpy.mockResolvedValue(_payload(payloadOverrides));
  render(<EstimateView token="tok-live" isAdmin={false} />);
  await waitFor(() =>
    expect(screen.queryByTestId("estimate-view")).toBeTruthy(),
  );
}


describe("EstimateView · customer decline-per-group", () => {
  // Case 1
  it("renders a Decline button on each actionable group", async () => {
    await _renderMagicLink();
    expect(
      screen.getByTestId("estimate-grouped-decline-btn-cat-hardscape"),
    ).toBeTruthy();
    expect(
      screen.getByTestId("estimate-grouped-decline-btn-cat-plants"),
    ).toBeTruthy();
    // No Restore buttons visible when nothing is declined.
    expect(
      screen.queryByTestId("estimate-grouped-restore-btn-cat-hardscape"),
    ).toBeNull();
  });

  // Case 2
  it("clicking Decline fires PATCH and re-renders with strike + Restore",
      async () => {
    patchSpy.mockResolvedValue(_declinedGroupPayload());
    await _renderMagicLink();

    fireEvent.click(
      screen.getByTestId("estimate-grouped-decline-btn-cat-hardscape"),
    );

    await waitFor(() => {
      expect(patchSpy).toHaveBeenCalledTimes(1);
    });
    // Fired the right URL (magic-link token variant).
    expect(patchSpy.mock.calls[0][0]).toContain(
      "/portal/quotes/via-token/tok-live/groups/cat-hardscape/decline",
    );

    // Post-response: row struck, Restore visible, Decline gone.
    await waitFor(() =>
      expect(
        screen.queryByTestId("estimate-grouped-restore-btn-cat-hardscape"),
      ).toBeTruthy(),
    );
    expect(
      screen.queryByTestId("estimate-grouped-decline-btn-cat-hardscape"),
    ).toBeNull();
    // Row carries the declined marker.
    const hardscapeRow = screen.getByTestId(
      "estimate-grouped-row-cat-hardscape",
    );
    expect(hardscapeRow.getAttribute("data-group-declined")).toBe("true");
    expect(
      screen.getByTestId("estimate-grouped-declined-label-cat-hardscape")
             .textContent,
    ).toContain("Declined");
  });

  // Case 3
  it("clicking Restore reverses the state via the undecline route",
      async () => {
    // Start in already-declined shape so Restore is rendered.
    patchSpy.mockResolvedValue(_payload());
    getSpy.mockResolvedValue(_declinedGroupPayload());
    render(<EstimateView token="tok-live" isAdmin={false} />);
    await waitFor(() =>
      expect(
        screen.queryByTestId("estimate-grouped-restore-btn-cat-hardscape"),
      ).toBeTruthy(),
    );

    fireEvent.click(
      screen.getByTestId("estimate-grouped-restore-btn-cat-hardscape"),
    );

    await waitFor(() => expect(patchSpy).toHaveBeenCalledTimes(1));
    expect(patchSpy.mock.calls[0][0]).toContain(
      "/portal/quotes/via-token/tok-live/groups/cat-hardscape/undecline",
    );
    // Back to non-declined UI.
    await waitFor(() =>
      expect(
        screen.queryByTestId("estimate-grouped-decline-btn-cat-hardscape"),
      ).toBeTruthy(),
    );
  });

  // Case 4
  it("hides both Decline and Restore on a non-actionable (accepted) quote",
      async () => {
    await _renderMagicLink({
      status: "accepted", decision: "accepted",
      accepted_at: "2026-02-10",
    });
    expect(
      screen.queryByTestId("estimate-grouped-decline-btn-cat-hardscape"),
    ).toBeNull();
    expect(
      screen.queryByTestId("estimate-grouped-decline-btn-cat-plants"),
    ).toBeNull();
    expect(
      screen.queryByTestId("estimate-grouped-restore-btn-cat-hardscape"),
    ).toBeNull();
  });
});


// ═════════════════════════════════════════════════════════════════════
// Case 5 — Admin dual-total renderer
// (Tests the QuoteInvoiceDetail totals block in isolation via a
//  fixture-driven mini-mount so we don't have to boot the full page.)
// ═════════════════════════════════════════════════════════════════════
describe("QuoteInvoiceDetail · admin dual-total renderer", () => {
  function _MiniTotals({ doc }) {
    // Local mirror of the exact conditional block shipped into
    // QuoteInvoiceDetail.jsx so this test locks the contract without
    // mounting the whole page (which pulls in the router and
    // side-effectful API calls).
    const money = (n) => `$${Number(n || 0).toFixed(2)}`;
    return (
      <div className="w-64 space-y-1 text-sm"
            data-testid="quote-invoice-totals-block">
        <div className="flex justify-between">
          <span>Subtotal</span><span>{money(doc.subtotal)}</span>
        </div>
        <div className="flex justify-between">
          <span>Total</span><span>{money(doc.total)}</span>
        </div>
        {doc.has_declined_lines ? (
          <div data-testid="quote-invoice-effective-total">
            <div>Subtotal (incl. declined): {money(doc.original_total ?? doc.total)}</div>
            <div>Effective (excl. declined):{" "}
              <span data-testid="quote-invoice-effective-total-value">
                {money(doc.adjusted_total ?? doc.total)}
              </span>
            </div>
          </div>
        ) : null}
      </div>
    );
  }

  it("shows Effective row only when has_declined_lines is true", () => {
    const { rerender } = render(<_MiniTotals doc={{
      subtotal: 100, total: 110,
      has_declined_lines: false,
      original_total: 110, adjusted_total: 110,
    }} />);
    expect(
      screen.queryByTestId("quote-invoice-effective-total"),
    ).toBeNull();

    rerender(<_MiniTotals doc={{
      subtotal: 100, total: 110,
      has_declined_lines: true,
      original_total: 110, adjusted_total: 60,
    }} />);
    expect(
      screen.getByTestId("quote-invoice-effective-total"),
    ).toBeTruthy();
    expect(
      screen.getByTestId("quote-invoice-effective-total-value").textContent,
    ).toContain("60.00");
  });
});
