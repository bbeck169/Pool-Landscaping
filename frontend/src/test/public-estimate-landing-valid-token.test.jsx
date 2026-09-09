/**
 * Feb-2026 · Batch #4 · Item 1 regression — a valid magic-link
 * token must render ``<EstimateView>`` with BOTH the customer-facing
 * approve button AND per-line decline buttons visible. The earlier
 * regression collapsed the itemized table into the grouped rollup
 * (``customer_group_display=true``), which stripped decline buttons
 * on the actionable magic-link surface.
 *
 * We stub ``@/api`` so the ``via-token`` GET returns the exact shape
 * the backend emits for a sent, actionable estimate. If EstimateView
 * misclassifies the response we'd see the error banner instead of
 * the toolbar + line-item rows — this test guards against that.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

// Stub the api layer BEFORE importing EstimateView.
vi.mock("@/api", () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
  },
  TOKEN_KEY: "token",
}));

import { api } from "@/api";
import EstimateView from "@/components/EstimateView";


const VIA_TOKEN_PAYLOAD = {
  estimate_id: "1d5aeec2-9c0c-4385-93fc-b971624cbdda",
  status: "sent",
  decision: null,
  accepted_at: null,
  declined_at: null,
  decline_reason: null,
  sent_at: "2026-09-09T20:00:00+00:00",
  sent_via: "email",
  expires_at: null,
  company: { name: "Pool & Landscaping of Vistancia" },
  bill_to: { name: "Drift Datetime", address: "13333 W Jesse Red Dr" },
  property_address: null,
  header: {
    customer_number: "drift-dt",
    estimate_number: "1D5AEEC2",
    estimate_date: "2026-09-09",
  },
  title: "Phase A UI Test Quote",
  line_items: [
    { description: "Pool Cleaning", quantity: 1, total: 150,
      customer_status: "pending", retail_price_snapshot: 150 },
    { description: "Chemical Treatment", quantity: 2, total: 100,
      customer_status: "pending", retail_price_snapshot: 50 },
  ],
  totals: {
    subtotal: 250, taxes: 0, amount_paid: 0,
    total_estimated_cost: 250,
  },
  notes: null,
  as_customer: true,
  // K79 · Grouped-view flag ON — the fix must force itemized
  // rendering on the magic-link surface so decline buttons show.
  customer_view: {
    customer_group_display: true,
    groups: [
      { category_id: null, label: "Other",
        subtotal: 250, description: null },
    ],
  },
};


describe("Batch #4 · Item 1 · magic-link EstimateView", () => {
  beforeEach(() => {
    api.get.mockReset();
    api.post.mockReset();
    api.get.mockResolvedValue(VIA_TOKEN_PAYLOAD);
  });

  it("renders approve + per-line decline for a valid actionable token", async () => {
    render(
      <MemoryRouter>
        <EstimateView token="tok-abc" isAdmin={false} />
      </MemoryRouter>,
    );

    // Load completes and the customer toolbar is on-screen.
    await waitFor(() => {
      expect(screen.getByTestId("estimate-toolbar-customer-approve"))
        .toBeTruthy();
    });
    expect(screen.getByTestId("estimate-toolbar-customer-decline"))
      .toBeTruthy();

    // Per-line decline buttons render for BOTH line items even
    // though ``customer_group_display`` is on — the magic-link
    // surface must fall back to the itemized table so the
    // decline actions are reachable.
    expect(screen.getByTestId("estimate-line-item-decline-0")).toBeTruthy();
    expect(screen.getByTestId("estimate-line-item-decline-1")).toBeTruthy();

    // Regression: no "Invalid estimate link" banner.
    expect(screen.queryByText(/Invalid estimate link/i)).toBeNull();

    // The API was called with the query-token endpoint, not the
    // auth'd ``/full`` path.
    expect(api.get).toHaveBeenCalledWith(
      expect.stringContaining("/portal/quotes/via-token?token=tok-abc"),
    );
  });
});
