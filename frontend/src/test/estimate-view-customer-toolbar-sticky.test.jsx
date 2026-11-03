/**
 * EstimateView · TD-estimate-toolbar-sticky-footer · Feb-2026
 *
 * Lock the sticky-footer wrapper around the customer Approve /
 * Decline / Request-Changes toolbar.  Defensive UX nudge so the
 * CTAs stay in view regardless of estimate length or scroll
 * position.  Classic-view only — Flipbook has its own sign-page
 * footer and the mobile header-pass-through is unaffected.
 *
 * This file locks:
 *   1. Sticky wrapper is PRESENT on a sent / viewed customer surface.
 *   2. Sticky wrapper is ABSENT when status is off-window (draft).
 *   3. Sticky wrapper is ABSENT when the doc is locked (accepted/
 *      declined).
 *   4. Sticky wrapper is ABSENT on the admin view.
 *   5. All three existing CTA testids are preserved INSIDE the
 *      wrapper (regression guard for selectors).
 *   6. Inline sticky style keys are set correctly.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, waitFor, within } from "@testing-library/react";

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


describe("EstimateView · sticky customer toolbar", () => {
  it("wraps the customer toolbar in a sticky-footer on a sent doc", async () => {
    await renderView();
    const sticky = screen.getByTestId("estimate-customer-toolbar-sticky");
    expect(sticky).toBeTruthy();
    // Inline style keys the sticky-footer promotion depends on.
    expect(sticky.style.position).toBe("sticky");
    expect(sticky.style.bottom).toBe("0px");
    // All three CTA testids survive the wrapper.
    expect(
      within(sticky).getByTestId("estimate-toolbar-customer-approve"),
    ).toBeTruthy();
    expect(
      within(sticky).getByTestId("estimate-toolbar-customer-decline"),
    ).toBeTruthy();
    expect(
      within(sticky).getByTestId("estimate-toolbar-request-changes-btn"),
    ).toBeTruthy();
  });

  it("omits the sticky wrapper when status is off-window (draft)", async () => {
    await renderView({ overrides: { status: "draft" } });
    expect(
      screen.queryByTestId("estimate-customer-toolbar-sticky"),
    ).toBeNull();
  });

  it("omits the sticky wrapper when the doc is locked (accepted)", async () => {
    await renderView({ overrides: {
      status: "accepted",
      decision: "accepted",
      accepted_at: "2026-02-09T10:00:00.000Z",
    }});
    expect(
      screen.queryByTestId("estimate-customer-toolbar-sticky"),
    ).toBeNull();
  });

  it("omits the sticky wrapper on the admin view", async () => {
    await renderView({
      overrides: { as_customer: false },
      props: { isAdmin: true },
    });
    expect(
      screen.queryByTestId("estimate-customer-toolbar-sticky"),
    ).toBeNull();
  });
});
