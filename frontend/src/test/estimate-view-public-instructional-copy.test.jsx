/**
 * EstimateView · TD-estimate-public-instructional-copy · Feb-2026
 *
 * The customer surface renders a helper line directly above the
 * line items table nudging the customer to Decline individual
 * lines before approving. Gating is identical to the per-line
 * Decline buttons + the toolbar Approve+Decline:
 *   ``as_customer && actionable && !locked``.
 *
 * This file locks:
 *   1. Copy is present on a sent / viewed customer-surface doc.
 *   2. Copy is absent when ``status`` is off-window (draft).
 *   3. Copy is absent when the doc is already finalized (locked).
 *   4. Copy is absent on admin and printable views.
 *   5. Exact wording matches the operator-approved sentence.
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


const EXPECTED_COPY =
  "You can customize your estimate by clicking Decline on any "
  + "line item before approving the final estimate.";


function samplePayload(overrides = {}) {
  return {
    estimate_id: "q-1",
    status: "sent",
    decision: null,
    accepted_at: null,
    declined_at: null,
    sent_at: "2026-02-09T10:00:00.000Z",
    sent_via: "email",
    company: { name: "Test Co" },
    bill_to: { name: "Cust", customer_number: "C-1" },
    property_address: "123 Test",
    header: {
      estimate_number: "EST-001", estimate_date: "2026-02-09",
      customer_number: "C-1",
    },
    title: "Test Estimate",
    line_items: [
      { description: "Pool clean", total: 100, quantity: 1, unit_price: 100,
        customer_status: "pending" },
    ],
    totals: {
      subtotal: 100, taxes: 10, amount_paid: 0, total_estimated_cost: 110,
      original_subtotal: 100, original_tax: 10, original_total: 110,
      original_discount_value: 0,
      adjusted_subtotal: 100, adjusted_tax: 10, adjusted_total: 110,
      adjusted_discount_value: 0,
      has_declined_lines: false, declined_line_count: 0,
    },
    notes: null,
    as_customer: true,
    ...overrides,
  };
}


async function renderView({ overrides = {}, props = {} } = {}) {
  getSpy.mockResolvedValue(samplePayload(overrides));
  render(<EstimateView token="tok-abc" isAdmin={false} {...props} />);
  await waitFor(() =>
    expect(screen.queryByTestId("estimate-view")).toBeTruthy(),
  );
}


describe("EstimateView · instructional copy above line items", () => {
  it("renders the exact copy on a sent customer-surface doc", async () => {
    await renderView();
    const node = screen.getByTestId("estimate-line-items-instructional-copy");
    expect(node).toBeTruthy();
    // Collapse any whitespace artifacts introduced by JSX line-wrapping
    // before comparing to the operator-approved sentence.
    const normalised = node.textContent.replace(/\s+/g, " ").trim();
    expect(normalised).toBe(EXPECTED_COPY);
  });

  it("renders on a viewed customer-surface doc too", async () => {
    await renderView({ overrides: { status: "viewed" } });
    expect(
      screen.getByTestId("estimate-line-items-instructional-copy"),
    ).toBeTruthy();
  });

  it("hides when status is off-window (draft)", async () => {
    await renderView({ overrides: { status: "draft" } });
    expect(
      screen.queryByTestId("estimate-line-items-instructional-copy"),
    ).toBeNull();
  });

  it("hides when the doc is already accepted (locked)", async () => {
    await renderView({ overrides: {
      status: "accepted",
      decision: "accepted",
      accepted_at: "2026-02-09T10:00:00.000Z",
    }});
    expect(
      screen.queryByTestId("estimate-line-items-instructional-copy"),
    ).toBeNull();
  });

  it("hides when the doc is already declined (locked)", async () => {
    await renderView({ overrides: {
      status: "declined",
      decision: "declined",
      declined_at: "2026-02-09T10:00:00.000Z",
    }});
    expect(
      screen.queryByTestId("estimate-line-items-instructional-copy"),
    ).toBeNull();
  });

  it("hides on the admin view", async () => {
    await renderView({
      overrides: { as_customer: false },
      props: { isAdmin: true },
    });
    expect(
      screen.queryByTestId("estimate-line-items-instructional-copy"),
    ).toBeNull();
  });

  it("hides when the server marks the payload as non-customer", async () => {
    // Printable PDF renders go through the server with
    // ``as_customer: false`` — exercise that invariant directly
    // rather than relying on the ``printable`` prop (which doesn't
    // flip ``as_customer`` on its own; the server does).
    await renderView({ overrides: { as_customer: false } });
    expect(
      screen.queryByTestId("estimate-line-items-instructional-copy"),
    ).toBeNull();
  });
});
