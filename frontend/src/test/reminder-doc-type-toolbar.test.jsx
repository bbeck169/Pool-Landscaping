/**
 * Feb-2026 · P0 — Estimate/Quote toolbar guard-rail vitests.
 *
 * Guards two contracts:
 *   1. The `shouldShowPaymentLinkButton` predicate is invoice-only
 *      and gates on payment-status too, so the toolbar never
 *      renders a "Payment link" button on:
 *        * an Estimate / Quote page (any status), OR
 *        * an Invoice in draft / void / paid state.
 *   2. `PublicInvoicePay` renders the friendly ``link_expired``
 *      copy when the auto-login endpoint bounced the customer to
 *      ``/pay/invoice/:id?msg=link_expired`` (no ``token=``), instead
 *      of the generic "missing token" error — matches the prod
 *      copy contract in the P0 spec.
 */
import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { shouldShowPaymentLinkButton } from "@/pages/quotes/QuoteInvoiceDetail";
import PublicInvoicePay from "@/pages/public/PublicInvoicePay";


// ═══════════════════════════════════════════════════════════════════
// 1) shouldShowPaymentLinkButton
// ═══════════════════════════════════════════════════════════════════
describe("shouldShowPaymentLinkButton · P0", () => {
  it("returns FALSE on any non-invoice doc regardless of status", () => {
    // This is the exact prod-bug shape: an Estimate in "sent" state
    // used to render the "Payment link" button that either 500'd or
    // minted a Stripe checkout session against an unapproved doc.
    expect(shouldShowPaymentLinkButton({
      isInvoice: false, docStatus: "sent",
    })).toBe(false);
    expect(shouldShowPaymentLinkButton({
      isInvoice: false, docStatus: "approved",
    })).toBe(false);
    expect(shouldShowPaymentLinkButton({
      isInvoice: false, docStatus: "draft",
    })).toBe(false);
  });

  it("returns TRUE on an invoice in sent / partially_paid / overdue", () => {
    expect(shouldShowPaymentLinkButton({
      isInvoice: true, docStatus: "sent",
    })).toBe(true);
    expect(shouldShowPaymentLinkButton({
      isInvoice: true, docStatus: "sent",
      paymentStatus: "partially_paid",
    })).toBe(true);
    expect(shouldShowPaymentLinkButton({
      isInvoice: true, docStatus: "overdue",
    })).toBe(true);
  });

  it("returns FALSE on an invoice that's still a draft", () => {
    // Draft invoices haven't been issued to the customer yet;
    // "Send invoice" (draft → sent chain) is the correct CTA.
    expect(shouldShowPaymentLinkButton({
      isInvoice: true, docStatus: "draft",
    })).toBe(false);
  });

  it("returns FALSE on a paid invoice", () => {
    expect(shouldShowPaymentLinkButton({
      isInvoice: true, docStatus: "sent", paymentStatus: "paid",
    })).toBe(false);
  });

  it("returns FALSE on a void invoice", () => {
    expect(shouldShowPaymentLinkButton({
      isInvoice: true, docStatus: "void",
    })).toBe(false);
    expect(shouldShowPaymentLinkButton({
      isInvoice: true, docStatus: "voided",
    })).toBe(false);
  });

  it("is case-insensitive for docStatus and paymentStatus", () => {
    expect(shouldShowPaymentLinkButton({
      isInvoice: true, docStatus: "SENT", paymentStatus: "UNPAID",
    })).toBe(true);
    expect(shouldShowPaymentLinkButton({
      isInvoice: true, docStatus: "Sent", paymentStatus: "Paid",
    })).toBe(false);
  });
});


// ═══════════════════════════════════════════════════════════════════
// 2) PublicInvoicePay link_expired copy
// ═══════════════════════════════════════════════════════════════════
describe("PublicInvoicePay · P0 link_expired banner", () => {
  it("renders the friendly link-expired copy when msg=link_expired and no token", () => {
    render(
      <MemoryRouter initialEntries={["/pay/invoice/inv-1?msg=link_expired"]}>
        <Routes>
          <Route path="/pay/invoice/:id" element={<PublicInvoicePay />} />
        </Routes>
      </MemoryRouter>,
    );
    // The friendly-invalid page renders (never the auth wall).
    const el = screen.getByTestId("public-invoice-pay-link-expired");
    expect(el).toBeInTheDocument();
    // Copy shape from the P0 spec: "This payment link is no longer valid.
    // To pay this invoice, please contact {tenant} …"
    expect(el.textContent).toMatch(/no longer valid/i);
    expect(el.textContent).toMatch(/contact the business/i);
  });

  it("renders the generic missing-token error when msg is absent and no token", () => {
    render(
      <MemoryRouter initialEntries={["/pay/invoice/inv-1"]}>
        <Routes>
          <Route path="/pay/invoice/:id" element={<PublicInvoicePay />} />
        </Routes>
      </MemoryRouter>,
    );
    // Generic branch — distinct testid so the assertions are
    // unambiguous and we haven't collapsed the two error states.
    expect(
      screen.getByTestId("public-invoice-pay-missing-token"),
    ).toBeInTheDocument();
  });
});
