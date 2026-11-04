/**
 * Feb-2026 · Phase C — signature-before-approve gate Vitest.
 *
 * Covers the customer-facing surface (EstimateView) at magic-link
 * mode:
 *   1. Payload with ``require_signature_before_approve=false``
 *      renders the Approve button as normal (enabled).
 *   2. Payload with ``require_signature_before_approve=true`` AND
 *      ``signature_status !== "signed"`` disables Approve, surfaces
 *      the "Sign to enable" hint, and renders the "Sign now" CTA.
 *   3. Payload with ``require_signature_before_approve=true`` AND
 *      ``signature_status === "signed"`` renders Approve enabled.
 *   4. Decline is NEVER gated by signature (regression guard).
 *   5. "Sign now" CTA dispatches ``open-signature-flow`` window
 *      event with { estimateId, token } so the surrounding portal
 *      shell can open its signature widget.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";

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
    estimate_id: "q-phase-c-1",
    status: "sent",
    decision: null,
    accepted_at: null, declined_at: null,
    sent_at: "2026-02-09T10:00:00.000Z", sent_via: "email",
    company: { name: "Phase C Co" },
    bill_to: { name: "Cust", customer_number: "C-1" },
    property_address: "1 Any",
    header: { estimate_number: "EST-C1", estimate_date: "2026-02-09",
                customer_number: "C-1" },
    title: "Phase C Estimate",
    line_items: [
      { description: "Pool clean", total: 100, quantity: 1,
        unit_price: 100, customer_status: "pending" },
    ],
    totals: {
      subtotal: 100, taxes: 0, amount_paid: 0, total_estimated_cost: 100,
      original_subtotal: 100, original_tax: 0, original_total: 100,
      original_discount_value: 0,
      adjusted_subtotal: 100, adjusted_tax: 0, adjusted_total: 100,
      adjusted_discount_value: 0,
      has_declined_lines: false, declined_line_count: 0,
    },
    notes: null,
    as_customer: true,
    // Phase C surface fields — default OFF for a clean payload.
    signature_status: null,
    require_signature_before_approve: false,
    ...overrides,
  };
}

async function renderView(overrides = {}) {
  getSpy.mockResolvedValue(samplePayload(overrides));
  render(<EstimateView token="tok-c1" isAdmin={false} />);
  await waitFor(
    () => expect(screen.queryByTestId("estimate-view")).toBeTruthy(),
  );
}


describe("EstimateView · Phase C · signature-before-approve gate", () => {
  it("flag=false → Approve enabled, no signature hint", async () => {
    await renderView({ require_signature_before_approve: false });
    const btn = screen.getByTestId("estimate-toolbar-customer-approve");
    expect(btn.disabled).toBe(false);
    expect(btn.getAttribute("data-signature-blocked")).toBe("false");
    expect(screen.queryByTestId("approve-blocked-by-signature-hint"))
      .toBeNull();
    expect(screen.queryByTestId("approve-sign-now-cta")).toBeNull();
  });

  it("flag=true + not signed → Approve disabled + hint + Sign-now CTA",
    async () => {
      await renderView({
        require_signature_before_approve: true,
        signature_status: null,
      });
      const btn = screen.getByTestId("estimate-toolbar-customer-approve");
      expect(btn.disabled).toBe(true);
      expect(btn.getAttribute("data-signature-blocked")).toBe("true");
      expect(btn.getAttribute("title")).toMatch(/sign/i);
      // Hint + CTA visible.
      const hint = screen.getByTestId("approve-blocked-by-signature-hint");
      expect(hint.textContent).toMatch(/sign/i);
      expect(screen.getByTestId("approve-sign-now-cta")).toBeTruthy();
    });

  it("flag=true + signed → Approve enabled, hint hidden", async () => {
    await renderView({
      require_signature_before_approve: true,
      signature_status: "signed",
    });
    const btn = screen.getByTestId("estimate-toolbar-customer-approve");
    expect(btn.disabled).toBe(false);
    expect(btn.getAttribute("data-signature-blocked")).toBe("false");
    expect(screen.queryByTestId("approve-blocked-by-signature-hint"))
      .toBeNull();
  });

  it("Decline is NEVER gated by signature (now: Decline absent entirely)", async () => {
    // TD-estimate-public-decline-whole-remove-plus-reason-optional ·
    // Feb-2026 — the whole-estimate Decline CTA was removed from the
    // customer surface; the invariant of "Decline is never gated by
    // signature" collapses to "Decline is not rendered at all", so
    // the signature-gate hint on Approve remains the only user-
    // visible blocker.
    await renderView({
      require_signature_before_approve: true,
      signature_status: null,
    });
    expect(
      screen.queryByTestId("estimate-toolbar-customer-decline"),
    ).toBeNull();
  });

  it("Sign-now CTA dispatches open-signature-flow with estimate + token",
    async () => {
      await renderView({
        require_signature_before_approve: true,
        signature_status: null,
      });
      const events = [];
      const listener = (ev) => events.push(ev.detail);
      window.addEventListener("open-signature-flow", listener);
      try {
        fireEvent.click(screen.getByTestId("approve-sign-now-cta"));
        await waitFor(() => expect(events.length).toBe(1));
        expect(events[0]).toEqual({
          estimateId: "q-phase-c-1",
          token: "tok-c1",
        });
      } finally {
        window.removeEventListener("open-signature-flow", listener);
      }
    });
});
