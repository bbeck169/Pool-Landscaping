/**
 * PORTAL-QUOTE-DECLINE-REQUIRE-REASON · Feb-2026 — Vitest coverage.
 *
 * Three cases for the required-reason decline modal mounted inside
 * ``<EstimateView>``:
 *   (i)   Modal renders dropdown + textarea + char-count after the
 *         customer clicks the top-level "Decline" button; submit
 *         button starts DISABLED on an empty form.
 *   (ii)  Submit enables only when the reason-category dropdown AND
 *         the free-text ≥ 10 chars are both populated.
 *   (iii) Clicking submit POSTs ``decline_reason_category`` +
 *         ``decline_reason_text`` (NOT the legacy ``reason`` field)
 *         to the Phase A path-based portal endpoint.
 *
 * Scaffolding borrows from
 * ``frontend/src/test/estimate-view-phase-a-decline.test.jsx`` so
 * the fixture ``samplePayload`` + ``renderView`` helpers stay in
 * lock-step with the pre-existing suite.
 */
import React from "react";
import {
  describe, it, expect, vi, beforeEach, afterEach,
} from "vitest";
import {
  render, screen, cleanup, fireEvent, waitFor,
} from "@testing-library/react";


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
    estimate_id: "q-decline",
    status: "sent",
    decision: null,
    accepted_at: null,
    declined_at: null,
    sent_at: "2026-02-09T10:00:00.000Z",
    sent_via: "email",
    company: { name: "Test Co" },
    bill_to: { name: "Cust", customer_number: "C-1" },
    property_address: "123 Test",
    header: { estimate_number: "EST-001", estimate_date: "2026-02-09",
               customer_number: "C-1" },
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


async function renderView(overrides = {}) {
  getSpy.mockResolvedValue(samplePayload(overrides));
  render(<EstimateView token="tok-decline" isAdmin={false} />);
  await waitFor(() =>
    expect(screen.queryByTestId("estimate-view")).toBeTruthy(),
  );
}


describe("EstimateDeclineModal · PORTAL-QUOTE-DECLINE-REQUIRE-REASON", () => {
  it("case (i) · modal renders dropdown + textarea + submit disabled on empty form", async () => {
    await renderView();
    // Open the modal via the top-level customer-decline toolbar
    // button (testid defined on the Phase A toolbar).
    fireEvent.click(
      screen.getByTestId("estimate-toolbar-customer-decline"),
    );
    expect(
      await screen.findByTestId("estimate-decline-modal"),
    ).toBeTruthy();
    // Dropdown + textarea + char-count all present.
    expect(
      screen.getByTestId("estimate-decline-category-select"),
    ).toBeTruthy();
    expect(screen.getByTestId("estimate-decline-text")).toBeTruthy();
    expect(
      screen.getByTestId("estimate-decline-char-count"),
    ).toBeTruthy();
    // Submit disabled while both fields are empty.
    expect(
      screen.getByTestId("estimate-decline-submit").disabled,
    ).toBe(true);
  });

  it("case (ii) · submit enables only when category + text ≥ 10 chars", async () => {
    await renderView();
    fireEvent.click(
      screen.getByTestId("estimate-toolbar-customer-decline"),
    );
    await screen.findByTestId("estimate-decline-modal");

    const submit = screen.getByTestId("estimate-decline-submit");
    const category = screen.getByTestId(
      "estimate-decline-category-select",
    );
    const text = screen.getByTestId("estimate-decline-text");

    // Category alone — still disabled.
    fireEvent.change(category, { target: { value: "too_expensive" } });
    expect(submit.disabled).toBe(true);

    // Text 9 chars — still disabled.
    fireEvent.change(text, { target: { value: "too short" } });
    expect(submit.disabled).toBe(true);

    // Text 10 chars — enables.
    fireEvent.change(text, { target: { value: "exactly ten" } });
    expect(submit.disabled).toBe(false);

    // Clearing category disables again.
    fireEvent.change(category, { target: { value: "" } });
    expect(submit.disabled).toBe(true);
  });

  it("case (iii) · submit POSTs the structured payload to the Phase A portal endpoint", async () => {
    postSpy.mockResolvedValue(samplePayload({
      status: "declined", decision: "declined",
      declined_at: "2026-02-09T11:00:00.000Z",
    }));

    await renderView();
    fireEvent.click(
      screen.getByTestId("estimate-toolbar-customer-decline"),
    );
    await screen.findByTestId("estimate-decline-modal");

    fireEvent.change(
      screen.getByTestId("estimate-decline-category-select"),
      { target: { value: "scope_not_what_expected" } },
    );
    const reasonText =
      "Pool decking line wasn't on the walk-through quote.";
    fireEvent.change(
      screen.getByTestId("estimate-decline-text"),
      { target: { value: reasonText } },
    );
    fireEvent.click(screen.getByTestId("estimate-decline-submit"));

    await waitFor(() => expect(postSpy).toHaveBeenCalledTimes(1));
    const [path, body] = postSpy.mock.calls[0];
    expect(path).toBe("/portal/quotes/via-token/tok-decline/decline");
    expect(body).toEqual({
      decline_reason_category: "scope_not_what_expected",
      decline_reason_text: reasonText,
    });
    // Legacy ``reason`` field must NOT be sent.
    expect(body.reason).toBeUndefined();
  });
});
