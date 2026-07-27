/**
 * Task RR/SS Phase 2 · Feb 2026 — pure-component render coverage for
 * ``InvoiceCreditApplied``. The 3 new admin pages
 * (``AiToolAuditPage``, ``AiPersonasScopePage``, ``CustomerCreditsPage``)
 * are covered by manual screenshot verification in the report — they
 * hit ``api.get`` in a ``useEffect`` and are flaky under Vitest's
 * jsdom transport in this repo, so we don't drive them here.
 */
import React from "react";
import { describe, it, expect, afterEach, vi } from "vitest";
import { render, cleanup, screen } from "@testing-library/react";

vi.mock("lucide-react", () => new Proxy({}, {
  get: () => (props) => React.createElement("span", props),
}));

import InvoiceCreditApplied from "@/components/InvoiceCreditApplied";

describe("Task SS Phase 2 · InvoiceCreditApplied", () => {
  afterEach(() => cleanup());

  it("renders nothing when credits_applied_cents=0 (backward-compat)", () => {
    const { container } = render(
      <InvoiceCreditApplied invoice={{ credits_applied_cents: 0 }} />
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing when invoice is null/undefined", () => {
    const { container: c1 } = render(<InvoiceCreditApplied invoice={null} />);
    expect(c1.firstChild).toBeNull();
    const { container: c2 } = render(<InvoiceCreditApplied />);
    expect(c2.firstChild).toBeNull();
  });

  it("partial branch shows both amounts and subtracts credit from balance", () => {
    render(
      <InvoiceCreditApplied invoice={{
        credits_applied_cents: 1500,      // $15
        total: 50.0, amount_paid: 0,
        payment_status: "unpaid",
      }} />
    );
    expect(screen.getByTestId("invoice-credit-partial")).toBeTruthy();
    expect(
      screen.getByTestId("invoice-credit-amount").textContent,
    ).toContain("$15.00");
    expect(
      screen.getByTestId("invoice-credit-balance-due").textContent,
    ).toContain("$35.00");
  });

  it("partial branch factors in prior card-paid amount too", () => {
    render(
      <InvoiceCreditApplied invoice={{
        credits_applied_cents: 1000,      // $10 credit
        total: 50.0, amount_paid: 15.0,   // $15 paid on card previously
        payment_status: "unpaid",
      }} />
    );
    // Balance due = 50 - 10 (credit) - 15 (paid) = $25.
    expect(
      screen.getByTestId("invoice-credit-balance-due").textContent,
    ).toContain("$25.00");
  });

  it("fully-covered branch renders when paid_method=service_credit", () => {
    render(
      <InvoiceCreditApplied invoice={{
        credits_applied_cents: 5000,
        total: 50.0, amount_paid: 0,
        payment_status: "paid",
        paid_method: "service_credit",
      }} />
    );
    expect(screen.getByTestId("invoice-credit-fully-covered")).toBeTruthy();
    // Partial testid must NOT also render.
    expect(screen.queryByTestId("invoice-credit-partial")).toBeNull();
  });

  it("fully-covered branch renders when paid+no card payment recorded", () => {
    // Edge case: no explicit paid_method but status is paid and no
    // card payment logged — treat as service_credit-paid.
    render(
      <InvoiceCreditApplied invoice={{
        credits_applied_cents: 5000,
        total: 50.0, amount_paid: 0,
        payment_status: "paid",
      }} />
    );
    expect(screen.getByTestId("invoice-credit-fully-covered")).toBeTruthy();
  });
});
