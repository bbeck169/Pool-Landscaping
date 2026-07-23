/**
 * Phase 10 · Feb 2026 — Frontend unit tests for the two new UI surfaces.
 *   1. PromoCodeInput — valid + invalid + account_credit + clear flows.
 *   2. AdjustDialog — submit button disabled until reason ≥ 5 chars.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import PromoCodeInput from "@/components/marketing/PromoCodeInput";
import { AdjustDialog } from "@/pages/customers/CustomerCreditsPage";

const _origFetch = global.fetch;

beforeEach(() => {
  global.fetch = vi.fn();
  process.env.REACT_APP_BACKEND_URL = "https://example.test";
});


// Helper to stub /promo-codes/validate.
function stubValidate(body) {
  global.fetch.mockResolvedValueOnce({
    ok: true,
    json: async () => body,
  });
}


describe("PromoCodeInput", () => {
  it("shows discount pill for a valid next_invoice code", async () => {
    stubValidate({
      valid: true, promo_code_id: "p1", code: "SUMMER10",
      apply_to: "next_invoice", amount_cents_effective: 1000,
    });
    const onChange = vi.fn();
    render(
      <PromoCodeInput invoiceId="i1" invoiceTotalCents={10_000}
                      onChange={onChange} />
    );
    fireEvent.click(screen.getByTestId("promo-code-input-toggle"));
    fireEvent.change(screen.getByTestId("promo-code-input-code"),
                       { target: { value: "SUMMER10" } });
    fireEvent.click(screen.getByTestId("promo-code-input-apply"));
    await waitFor(() =>
      expect(screen.getByTestId("promo-code-input-applied-pill")).toBeInTheDocument()
    );
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({
      promo_code_id: "p1",
      code: "SUMMER10",
      apply_to: "next_invoice",
      discount_cents: 1000,
      effective_total_cents: 9000,
    }));
  });

  it("shows red error and does not call onChange on invalid code", async () => {
    stubValidate({ valid: false, reason: "expired" });
    const onChange = vi.fn();
    render(
      <PromoCodeInput invoiceId="i1" invoiceTotalCents={10_000}
                      onChange={onChange} />
    );
    fireEvent.click(screen.getByTestId("promo-code-input-toggle"));
    fireEvent.change(screen.getByTestId("promo-code-input-code"),
                       { target: { value: "OLD" } });
    fireEvent.click(screen.getByTestId("promo-code-input-apply"));
    const err = await screen.findByTestId("promo-code-input-error");
    expect(err.textContent).toMatch(/expired/i);
    expect(screen.queryByTestId("promo-code-input-applied-pill")).toBeNull();
    // onChange called with null to signal "clear any previously applied"
    expect(onChange).toHaveBeenCalledWith(null);
  });

  it("displays account_credit copy — total unchanged", async () => {
    stubValidate({
      valid: true, promo_code_id: "p2", code: "REF-ABC",
      apply_to: "account_credit", amount_cents_effective: 2500,
    });
    const onChange = vi.fn();
    render(
      <PromoCodeInput invoiceId="i1" invoiceTotalCents={10_000}
                      onChange={onChange} />
    );
    fireEvent.click(screen.getByTestId("promo-code-input-toggle"));
    fireEvent.change(screen.getByTestId("promo-code-input-code"),
                       { target: { value: "REF-ABC" } });
    fireEvent.click(screen.getByTestId("promo-code-input-apply"));
    const pill = await screen.findByTestId("promo-code-input-applied-pill");
    expect(pill.textContent).toMatch(/credit/);
    // total unchanged for account_credit
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({
      apply_to: "account_credit",
      effective_total_cents: 10_000,
    }));
  });

  it("clear button restores empty state", async () => {
    stubValidate({
      valid: true, promo_code_id: "p1", code: "X",
      apply_to: "next_invoice", amount_cents_effective: 500,
    });
    const onChange = vi.fn();
    render(<PromoCodeInput invoiceId="i1" invoiceTotalCents={5000}
                            onChange={onChange} />);
    fireEvent.click(screen.getByTestId("promo-code-input-toggle"));
    fireEvent.change(screen.getByTestId("promo-code-input-code"),
                       { target: { value: "X" } });
    fireEvent.click(screen.getByTestId("promo-code-input-apply"));
    await screen.findByTestId("promo-code-input-applied-pill");
    fireEvent.click(screen.getByTestId("promo-code-input-clear"));
    expect(screen.queryByTestId("promo-code-input-applied-pill")).toBeNull();
    // Last onChange with null.
    expect(onChange).toHaveBeenLastCalledWith(null);
  });
});


describe("AdjustDialog", () => {
  it("disables submit button until reason is >= 5 chars", () => {
    render(
      <AdjustDialog currentBalanceCents={5000} customerId="c1"
                     onClose={() => {}} onSaved={() => {}} />
    );
    const submit = screen.getByTestId("customer-credits-adjust-submit");
    // Empty state — disabled.
    expect(submit).toBeDisabled();
    // Only amount, no reason.
    fireEvent.change(screen.getByTestId("customer-credits-adjust-amount"),
                       { target: { value: "10" } });
    expect(submit).toBeDisabled();
    // Short reason — disabled.
    fireEvent.change(screen.getByTestId("customer-credits-adjust-reason"),
                       { target: { value: "no" } });
    expect(submit).toBeDisabled();
    // OK reason — enabled.
    fireEvent.change(screen.getByTestId("customer-credits-adjust-reason"),
                       { target: { value: "valid five plus chars" } });
    expect(submit).not.toBeDisabled();
  });
});
