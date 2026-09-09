/**
 * Feb-2026 · Batch #4 · Logo ship — cross-surface Vitest.
 *
 * Asserts ``data-testid="doc-header-logo"`` renders on:
 *   • Invoice admin/portal detail (<InvoiceView>)
 *   • Estimate admin/portal detail (<EstimateView>)
 *   • Magic-link public estimate view (token-mode <EstimateView>)
 *
 * Also spot-checks the ``getTenantLogoUrl`` helper's resolution
 * order (company override > tenant override > shared default).
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, cleanup } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

vi.mock("@/api", () => ({
  api: { get: vi.fn(), post: vi.fn() },
  TOKEN_KEY: "token",
}));

import { api } from "@/api";
import EstimateView from "@/components/EstimateView";
import InvoiceView from "@/components/InvoiceView";
import {
  getTenantLogoUrl,
  DEFAULT_LOGO_URL,
  DEFAULT_LOGO_ALT,
} from "@/lib/tenantLogo";


const COMPANY_DEFAULT = {
  name: "Pool & Landscaping of Vistancia",
  address: "12 Vistancia Blvd, Peoria, AZ",
  phone: "555-0100",
  website: "www.plofv.com",
  email: "hello@plofv.com",
  logo_url: DEFAULT_LOGO_URL,
};

const INVOICE_PAYLOAD = {
  company: COMPANY_DEFAULT,
  bill_to: { name: "Jane Doe", address: "1 Main St" },
  property_address: null,
  header: {
    invoice_number: "INV-0001",
    invoice_date: "2026-09-09",
    credit_available: 0,
    outstanding_balance: 250,
  },
  line_items: [
    { description: "Service", cost_rate: 100, qty_hr: 1, percent: 0, total: 100 },
  ],
  totals: { subtotal: 100, this_invoice: 100, amount_paid: 0, total_due: 100 },
  notes: "Thanks!",
  is_due_on_receipt: false,
  payment_status: "unpaid",
};

const ESTIMATE_PAYLOAD = {
  estimate_id: "est-1",
  status: "sent",
  decision: null,
  accepted_at: null, declined_at: null, decline_reason: null,
  sent_at: "2026-09-09T20:00:00+00:00",
  sent_via: "email", expires_at: null,
  company: COMPANY_DEFAULT,
  bill_to: { name: "Jane Doe", address: "1 Main St" },
  property_address: null,
  header: {
    customer_number: "c-1",
    estimate_number: "EST-0001",
    estimate_date: "2026-09-09",
  },
  title: "Quote",
  line_items: [
    { description: "Service", quantity: 1, total: 100,
      customer_status: "pending", retail_price_snapshot: 100 },
  ],
  totals: { subtotal: 100, taxes: 0, amount_paid: 0, total_estimated_cost: 100 },
  notes: null,
  as_customer: true,
  customer_view: { customer_group_display: false, groups: [] },
};


describe("Batch #4 · Logo ship · tenantLogo helper", () => {
  it("company override wins over tenant + default", () => {
    expect(getTenantLogoUrl(
      { logo_url: "https://cdn/co.png" },
      { logo_url: "https://cdn/te.png" },
    )).toBe("https://cdn/co.png");
  });
  it("tenant override wins over default", () => {
    expect(getTenantLogoUrl({}, { logo_url: "https://cdn/te.png" }))
      .toBe("https://cdn/te.png");
  });
  it("defaults to the shared Pool & Landscaping of Vistancia asset", () => {
    expect(getTenantLogoUrl({}, {})).toBe(DEFAULT_LOGO_URL);
    expect(getTenantLogoUrl()).toBe(DEFAULT_LOGO_URL);
  });
  it("DEFAULT_LOGO_URL points at the new @1x asset", () => {
    expect(DEFAULT_LOGO_URL).toBe(
      "/logos/pool-landscaping-of-vistancia@1x.png",
    );
  });
});


describe("Batch #4 · Logo ship · InvoiceView", () => {
  beforeEach(() => {
    api.get.mockReset();
    api.post.mockReset();
    api.get.mockResolvedValue(INVOICE_PAYLOAD);
  });

  it("renders doc-header-logo with alt + src from the tenant helper", async () => {
    render(
      <MemoryRouter>
        <InvoiceView invoiceId="inv-1" />
      </MemoryRouter>,
    );
    const logo = await waitFor(
      () => screen.getByTestId("doc-header-logo"),
    );
    expect(logo.tagName).toBe("IMG");
    expect(logo.getAttribute("src")).toBe(DEFAULT_LOGO_URL);
    expect(logo.getAttribute("alt")).toBe(COMPANY_DEFAULT.name);
    expect(logo.getAttribute("data-surface")).toBe("invoice");
    cleanup();
  });
});


describe("Batch #4 · Logo ship · EstimateView (admin + magic-link)", () => {
  beforeEach(() => {
    api.get.mockReset();
    api.post.mockReset();
    api.get.mockResolvedValue(ESTIMATE_PAYLOAD);
  });

  it("renders doc-header-logo on the admin surface", async () => {
    render(
      <MemoryRouter>
        <EstimateView estimateId="est-1" isAdmin />
      </MemoryRouter>,
    );
    const logo = await waitFor(
      () => screen.getByTestId("doc-header-logo"),
    );
    expect(logo.getAttribute("src")).toBe(DEFAULT_LOGO_URL);
    expect(logo.getAttribute("data-surface")).toBe("estimate");
    cleanup();
  });

  it("renders doc-header-logo on the magic-link (token) surface", async () => {
    render(
      <MemoryRouter>
        <EstimateView token="tok-abc" isAdmin={false} />
      </MemoryRouter>,
    );
    const logo = await waitFor(
      () => screen.getByTestId("doc-header-logo"),
    );
    expect(logo.getAttribute("alt")).toBe(COMPANY_DEFAULT.name);
    cleanup();
  });

  it("falls back to DEFAULT_LOGO_ALT when company.name is absent", async () => {
    api.get.mockResolvedValueOnce({
      ...ESTIMATE_PAYLOAD,
      company: { ...COMPANY_DEFAULT, name: "" },
    });
    render(
      <MemoryRouter>
        <EstimateView token="tok-xyz" isAdmin={false} />
      </MemoryRouter>,
    );
    const logo = await waitFor(
      () => screen.getByTestId("doc-header-logo"),
    );
    expect(logo.getAttribute("alt")).toBe(DEFAULT_LOGO_ALT);
    cleanup();
  });
});
