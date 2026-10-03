/**
 * Phase 2 B2 · Feb-2026 · QuoteInvoiceDetail — recipient-type badge
 * + lead-invoice notice coverage.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";

vi.mock("@/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() },
  TOKEN_KEY: "token",
}));
vi.mock("@/auth", () => ({
  useAuth: () => ({ user: { role: "admin", id: "u-1" }, token: "t" }),
}));

import { api } from "@/api";
import QuoteInvoiceDetail from "@/pages/quotes/QuoteInvoiceDetail";

function makeDoc(overrides) {
  return {
    id: "doc-1",
    doc_type: "quote",
    status: "sent",
    decision: null,
    title: "Test Doc",
    customer_id: null,
    customer_name: "Lead Lenny",
    total: 500,
    amount_paid: 0,
    payment_status: "unpaid",
    line_items: [],
    tenant_id: "t-1",
    recipient_type: "customer",
    recipient_id: null,
    converted_invoice_id: null,
    ...overrides,
  };
}

function mountWithDoc(doc) {
  api.get.mockReset();
  api.get.mockImplementation(async (path) => {
    if (path.startsWith(`/quotes/${doc.id}`)
        && !path.includes("/signature")
        && !path.includes("/versions")
        && !path.includes("/edit-history")) {
      return doc;
    }
    if (path.startsWith("/settings/terms")) {
      return { default_invoice_terms: "", default_quote_terms: "" };
    }
    if (path.includes("/signature")) return { signed: false };
    if (path.includes("/versions")) return { total: 0 };
    return {};
  });
  const route = doc.doc_type === "invoice" ? "/invoices" : "/quotes";
  return render(
    <MemoryRouter initialEntries={[`${route}/${doc.id}`]}>
      <Routes>
        <Route
          path={`${route}/:id`}
          element={<QuoteInvoiceDetail _docType={doc.doc_type} />}
        />
      </Routes>
    </MemoryRouter>,
  );
}

describe("Phase 2 B2 · QuoteInvoiceDetail · recipient-type badge", () => {
  it("renders a 'Lead' badge when recipient_type=lead", async () => {
    mountWithDoc(makeDoc({
      id: "q-lead-1", doc_type: "quote",
      recipient_type: "lead", recipient_id: "l-99",
    }));
    const badge = await waitFor(
      () => screen.getByTestId("quote-recipient-type-badge"),
    );
    expect(badge).toHaveAttribute("data-recipient-type", "lead");
    expect(badge).toHaveTextContent(/lead/i);
  });

  it("renders a 'Customer' badge when recipient_type=customer", async () => {
    mountWithDoc(makeDoc({
      id: "q-cust-1", doc_type: "quote",
      recipient_type: "customer", recipient_id: "c-1",
    }));
    const badge = await waitFor(
      () => screen.getByTestId("quote-recipient-type-badge"),
    );
    expect(badge).toHaveAttribute("data-recipient-type", "customer");
    expect(badge).toHaveTextContent(/customer/i);
  });

  it("renders a 'Customer' badge for legacy docs with no recipient_type (back-compat)", async () => {
    mountWithDoc(makeDoc({
      id: "q-legacy-1", doc_type: "quote",
      recipient_type: null, recipient_id: null,
      customer_id: "c-legacy", customer_name: "Legacy Customer",
    }));
    const badge = await waitFor(
      () => screen.getByTestId("quote-recipient-type-badge"),
    );
    expect(badge).toHaveAttribute("data-recipient-type", "customer");
    expect(badge).toHaveTextContent(/customer/i);
  });
});

describe("Phase 2 B2 · QuoteInvoiceDetail · lead-invoice notice", () => {
  it("renders the lead-invoice notice when doc_type=invoice AND recipient_type=lead", async () => {
    mountWithDoc(makeDoc({
      id: "inv-lead-1", doc_type: "invoice",
      recipient_type: "lead", recipient_id: "l-99",
    }));
    const notice = await waitFor(
      () => screen.getByTestId("invoice-lead-recipient-notice"),
    );
    expect(notice).toHaveTextContent(/card-on-file autopay unavailable/i);
    expect(notice).toHaveTextContent(/hosted checkout/i);
  });

  it("does NOT render the lead-invoice notice on quotes (even if recipient_type=lead)", async () => {
    mountWithDoc(makeDoc({
      id: "q-lead-2", doc_type: "quote",
      recipient_type: "lead", recipient_id: "l-99",
    }));
    await waitFor(() => screen.getByTestId("quote-recipient-type-badge"));
    expect(screen.queryByTestId("invoice-lead-recipient-notice")).toBeNull();
  });

  it("does NOT render the lead-invoice notice on customer-recipient invoices", async () => {
    mountWithDoc(makeDoc({
      id: "inv-cust-1", doc_type: "invoice",
      recipient_type: "customer", recipient_id: "c-1",
    }));
    await waitFor(() => screen.getByTestId("quote-recipient-type-badge"));
    expect(screen.queryByTestId("invoice-lead-recipient-notice")).toBeNull();
  });
});
