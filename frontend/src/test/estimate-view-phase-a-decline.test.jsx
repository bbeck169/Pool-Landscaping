/**
 * EstimateView · Feb-2026 · Phase A — Vitest coverage.
 *
 * Verifies the Phase A customer-portal decline UX:
 *   1. Per-line "Decline" button visible on sent/viewed docs, hidden
 *      once the doc is finalized or off-window.
 *   2. Confirm dialog fires with the correct copy + testids.
 *   3. Optimistic replace of the payload after decline / undecline.
 *   4. Undecline button replaces Decline once a line is declined.
 *   5. Adjusted-total strike-through row appears when
 *      ``totals.has_declined_lines`` is true.
 *   6. Top-level customer-approve / customer-decline buttons carry
 *      the new Phase A testids AND the legacy testid hidden spans
 *      remain queryable for back-compat.
 *   7. Buttons disabled when status is off-window (e.g. draft).
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

// Confirm dialog auto-accept so ``accept()`` flows through.
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
    header: { estimate_number: "EST-001", estimate_date: "2026-02-09",
               customer_number: "C-1" },
    title: "Test Estimate",
    line_items: [
      { description: "Pool clean", total: 100, quantity: 1, unit_price: 100,
        customer_status: "pending" },
      { description: "Chemicals", total: 100, quantity: 2, unit_price: 50,
        customer_status: "pending" },
    ],
    totals: {
      subtotal: 200, taxes: 20, amount_paid: 0, total_estimated_cost: 220,
      original_subtotal: 200, original_tax: 20, original_total: 220,
      original_discount_value: 0,
      adjusted_subtotal: 200, adjusted_tax: 20, adjusted_total: 220,
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
  render(<EstimateView token="tok-abc" isAdmin={false} />);
  await waitFor(() => expect(screen.queryByTestId("estimate-view")).toBeTruthy());
}


describe("EstimateView · Phase A · per-line decline", () => {
  it("renders per-line Decline buttons on a sent doc", async () => {
    await renderView();
    expect(screen.getByTestId("estimate-line-item-decline-0")).toBeTruthy();
    expect(screen.getByTestId("estimate-line-item-decline-1")).toBeTruthy();
  });

  it("hides per-line buttons when status is draft (off-window)", async () => {
    await renderView({ status: "draft" });
    expect(screen.queryByTestId("estimate-line-item-decline-0")).toBeNull();
  });

  it("hides per-line buttons when the doc is already finalized", async () => {
    await renderView({ decision: "accepted", status: "accepted",
                        accepted_at: "2026-02-09" });
    expect(screen.queryByTestId("estimate-line-item-decline-0")).toBeNull();
    expect(screen.getByTestId("estimate-accepted-pill")).toBeTruthy();
  });

  it("opens the confirm dialog and POSTs to the decline endpoint", async () => {
    postSpy.mockResolvedValue(samplePayload({
      line_items: [
        { description: "Pool clean", total: 100, customer_status: "declined",
          customer_declined_at: "2026-02-09" },
        { description: "Chemicals", total: 100, customer_status: "pending" },
      ],
      totals: { subtotal: 200, taxes: 20, amount_paid: 0,
                 total_estimated_cost: 220,
                 original_total: 220, adjusted_total: 110,
                 has_declined_lines: true, declined_line_count: 1 },
    }));
    await renderView();
    fireEvent.click(screen.getByTestId("estimate-line-item-decline-0"));
    // Confirm dialog surfaces.
    expect(screen.getByTestId("estimate-line-item-decline-dialog")).toBeTruthy();
    fireEvent.change(screen.getByTestId("estimate-line-item-decline-reason"),
                       { target: { value: "not needed" } });
    fireEvent.click(screen.getByTestId("estimate-line-item-decline-confirm"));
    await waitFor(() => expect(postSpy).toHaveBeenCalledTimes(1));
    const [path, body] = postSpy.mock.calls[0];
    expect(path).toBe("/portal/quotes/via-token/tok-abc/line-items/0/decline");
    expect(body.reason).toBe("not needed");
    // Adjusted total strike-through row now renders.
    await waitFor(() => expect(screen.queryByTestId("estimate-totals-adjusted-row")).toBeTruthy());
    expect(screen.getByTestId("estimate-totals-original").textContent).toContain("220");
    expect(screen.getByTestId("estimate-totals-adjusted").textContent).toContain("110");
    // Declined chip shows on the row.
    expect(screen.getByTestId("estimate-line-item-declined-chip-0")).toBeTruthy();
  });

  it("undecline replaces the row and POSTs to the undecline endpoint", async () => {
    postSpy.mockResolvedValue(samplePayload());
    await renderView({
      line_items: [
        { description: "Pool clean", total: 100,
          customer_status: "declined" },
        { description: "Chemicals", total: 100,
          customer_status: "pending" },
      ],
      totals: { subtotal: 200, taxes: 20, amount_paid: 0,
                 total_estimated_cost: 220,
                 original_total: 220, adjusted_total: 110,
                 has_declined_lines: true, declined_line_count: 1 },
    });
    // Line 0 shows Undo decline button.
    expect(screen.getByTestId("estimate-line-item-undecline-0")).toBeTruthy();
    fireEvent.click(screen.getByTestId("estimate-line-item-undecline-0"));
    await waitFor(() => expect(postSpy).toHaveBeenCalledTimes(1));
    const [path] = postSpy.mock.calls[0];
    expect(path).toBe("/portal/quotes/via-token/tok-abc/line-items/0/undecline");
  });
});


describe("EstimateView · Phase A · top-level approve / decline", () => {
  it("renders Approve testid on a sent doc; Decline removed per TD-decline-whole-remove", async () => {
    await renderView();
    expect(screen.getByTestId("estimate-toolbar-customer-approve")).toBeTruthy();
    // TD-estimate-public-decline-whole-remove-plus-reason-optional ·
    // Feb-2026 — whole-estimate Decline CTA + its hidden
    // ``estimate-toolbar-decline-btn`` legacy-alias span were both
    // removed from the customer surface.  Approve + its legacy
    // ``estimate-toolbar-accept-btn`` alias remain.
    expect(screen.queryByTestId("estimate-toolbar-customer-decline")).toBeNull();
    expect(screen.getByTestId("estimate-toolbar-accept-btn")).toBeTruthy();
    expect(screen.queryByTestId("estimate-toolbar-decline-btn")).toBeNull();
  });

  it("Approve fires POST to the new path-based endpoint", async () => {
    postSpy.mockResolvedValue(samplePayload({ decision: "accepted",
                                                 status: "accepted" }));
    await renderView();
    fireEvent.click(screen.getByTestId("estimate-toolbar-customer-approve"));
    await waitFor(() => expect(postSpy).toHaveBeenCalledTimes(1));
    expect(postSpy.mock.calls[0][0])
      .toBe("/portal/quotes/via-token/tok-abc/approve");
  });

  it("hides approve once status is off-window (draft); Decline never renders", async () => {
    await renderView({ status: "draft" });
    expect(screen.queryByTestId("estimate-toolbar-customer-approve")).toBeNull();
    expect(screen.queryByTestId("estimate-toolbar-customer-decline")).toBeNull();
  });
});


describe("EstimateView · Phase A · totals block", () => {
  it("adjusted-total row is hidden when no declined lines", async () => {
    await renderView();
    expect(screen.queryByTestId("estimate-totals-adjusted-row")).toBeNull();
  });

  it("adjusted-total row surfaces original + adjusted when declined", async () => {
    await renderView({
      totals: { subtotal: 200, taxes: 20, amount_paid: 0,
                 total_estimated_cost: 220,
                 original_total: 220, adjusted_total: 110,
                 has_declined_lines: true, declined_line_count: 1 },
      line_items: [
        { description: "Pool clean", total: 100,
          customer_status: "declined" },
        { description: "Chemicals", total: 100,
          customer_status: "pending" },
      ],
    });
    expect(screen.getByTestId("estimate-totals-adjusted-row")).toBeTruthy();
    expect(screen.getByTestId("estimate-totals-original").textContent).toMatch(/220/);
    expect(screen.getByTestId("estimate-totals-adjusted").textContent).toMatch(/110/);
  });
});


// ─── TD-estimate-public-decline-whole-remove-plus-reason-optional ──
// Feb-2026 — regression locks for the two requirements of the ticket:
//   (1) the whole-estimate Decline CTA is ABSENT from every
//       customer-visible surface on the classic branch.
//   (2) the per-line decline modal carries a VISIBLE ``<label>``
//       element ("Optional reason") wired to the textarea via
//       ``htmlFor`` + ``id``.  Reason stays STRICTLY OPTIONAL — no
//       ``required`` attribute, the Decline-this-line submit button
//       is NOT empty-gated.
describe("EstimateView · TD-decline-whole-remove", () => {
  it("whole-estimate Decline is absent from every customer surface", async () => {
    await renderView();
    for (const testid of [
      "estimate-toolbar-customer-decline",
      "estimate-toolbar-decline-btn",     // hidden legacy alias
      "estimate-bottom-decline-quote-btn",// grouped-layout bottom CTA
      "estimate-mobile-decline-btn",      // sticky mobile action bar
      "flipbook-decline-btn",             // flipbook sign page
      "estimate-decline-modal",           // whole-estimate modal root
      "estimate-decline-submit",          // whole-estimate submit
      "estimate-decline-category-select", // whole-estimate category
      "estimate-decline-text",            // whole-estimate reason
    ]) {
      expect(screen.queryByTestId(testid)).toBeNull();
    }
  });

  it("per-line decline modal renders a visible <label htmlFor> element", async () => {
    await renderView({
      line_items: [
        { description: "Pool clean", total: 100, quantity: 1,
          unit_price: 100, customer_status: "pending" },
      ],
    });
    fireEvent.click(screen.getByTestId("estimate-line-item-decline-0"));
    const label = screen.getByTestId(
      "estimate-line-item-decline-reason-label",
    );
    expect(label).toBeTruthy();
    expect(label.tagName).toBe("LABEL");
    expect(label.textContent.trim()).toBe("Optional reason");
    expect(label.getAttribute("for"))
      .toBe("estimate-line-item-decline-reason");
    const textarea = screen.getByTestId("estimate-line-item-decline-reason");
    expect(textarea.id).toBe("estimate-line-item-decline-reason");
    // STRICTLY optional — no required attribute, no minLength.
    expect(textarea.hasAttribute("required")).toBe(false);
    expect(textarea.getAttribute("minlength")).toBeNull();
    // Confirm submit is NOT empty-gated — only busy-gated.
    const submit = screen.getByTestId("estimate-line-item-decline-confirm");
    expect(submit.disabled).toBe(false);
  });

  it("per-line decline posts with empty reason body when customer leaves it blank", async () => {
    postSpy.mockResolvedValue(samplePayload({}));
    await renderView({
      line_items: [
        { description: "Pool clean", total: 100, quantity: 1,
          unit_price: 100, customer_status: "pending" },
      ],
    });
    fireEvent.click(screen.getByTestId("estimate-line-item-decline-0"));
    fireEvent.click(screen.getByTestId("estimate-line-item-decline-confirm"));
    await waitFor(() => expect(postSpy).toHaveBeenCalledTimes(1));
    expect(postSpy.mock.calls[0][0])
      .toBe("/portal/quotes/via-token/tok-abc/line-items/0/decline");
    expect(postSpy.mock.calls[0][1]).toEqual({ reason: "" });
  });
});
