// Phase K47 · Feb-2026 — Invoice view-tracking · smoke tests.
//
// Locks in the K47 landing state via source inspection:
//   * The web view-history component + admin detail wiring exist.
//   * The public magic-link page forwards the whitelisted ?src=.
//   * The invoices list has the new "Viewed" column with a testID.
//   * The backend tracker service is registered as a router.

import { describe, it, expect } from "vitest";
import { readFileSync, existsSync } from "node:fs";
import { resolve } from "node:path";

const ROOT = resolve(__dirname, "../../..");
const R = (rel) => readFileSync(resolve(ROOT, rel), "utf8");

describe("Phase K47 · Backend surface", () => {
  it("registers the invoice_views router in server.py", () => {
    const src = R("backend/server.py");
    expect(src).toContain("invoice_views as _k47_invoice_views");
    expect(src).toContain("_k47_invoice_views.router");
  });

  it("services/invoice_view_tracker.py exports the tracker API", () => {
    const src = R("backend/services/invoice_view_tracker.py");
    expect(src).toContain("async def record_invoice_view");
    expect(src).toContain("async def fetch_invoice_views_summary");
    expect(src).toContain("async def ensure_invoice_view_indexes");
    // 30-second dedupe window is documented + implemented.
    expect(src).toMatch(/_DEDUPE_SECONDS\s*=\s*30/);
    // Source whitelist.
    expect(src).toMatch(/_VALID_SOURCES\s*=\s*\("email",\s*"sms",\s*"portal",\s*"link"\)/);
  });

  it("routers/invoice_views.py enforces admin RBAC", () => {
    const src = R("backend/routers/invoice_views.py");
    expect(src).toContain('@router.get("/invoices/{iid}/views")');
    expect(src).toContain('if role in ("technician", "customer"):');
  });

  it("magic-link viewer accepts ?src= and calls the tracker", () => {
    const src = R("backend/routers/invoice_magic_view.py");
    expect(src).toMatch(/token: str\s*=\s*"",\s*src: str\s*=\s*""/);
    expect(src).toContain("record_invoice_view");
    expect(src).toContain('source=src or "link"');
  });

  it("portal-authed /full endpoint tracks customer views", () => {
    const src = R("backend/routers/invoice_viewer.py");
    expect(src).toContain('source="portal"');
    expect(src).toMatch(/user\.get\("role"\).*?==\s*"customer"/);
  });

  it("pay_link_builder forwards the optional ?src= param", () => {
    const src = R("backend/services/pay_link_builder.py");
    expect(src).toMatch(/src:\s*Optional\[str\]\s*=\s*None/);
    expect(src).toContain('f"{url}&src={src}"');
  });

  it("emailer.py sends src=email on the pay link", () => {
    const src = R("backend/emailer.py");
    expect(src).toContain('src="email"');
  });

  it("dunning.py sends channel-appropriate src", () => {
    const src = R("backend/routers/dunning.py");
    expect(src).toMatch(/src="email"/);
    expect(src).toMatch(/src="sms"/);
  });

  it("invoices overview endpoint surfaces the denorm view aggregates", () => {
    const src = R("backend/routers/quotes.py");
    expect(src).toMatch(/"first_viewed_at":\s*d\.get\("first_viewed_at"\)/);
    expect(src).toMatch(/"last_viewed_at":\s*d\.get\("last_viewed_at"\)/);
    expect(src).toMatch(/"view_count":\s*int\(d\.get\("view_count"\)\s*or\s*0\)/);
  });
});

describe("Phase K47 · Frontend web surface", () => {
  it("InvoiceViewHistory component exists", () => {
    expect(
      existsSync(resolve(ROOT, "frontend/src/components/invoices/InvoiceViewHistory.jsx")),
    ).toBe(true);
    const src = R("frontend/src/components/invoices/InvoiceViewHistory.jsx");
    expect(src).toContain("invoice-view-history-card");
    expect(src).toContain("invoice-view-count");
    expect(src).toContain("invoice-view-first-at");
    expect(src).toContain("invoice-view-last-at");
    expect(src).toContain("/invoices/${invoiceId}/views");
  });

  it("QuoteInvoiceDetail mounts the view-history card for staff invoices", () => {
    const src = R("frontend/src/pages/quotes/QuoteInvoiceDetail.jsx");
    expect(src).toContain('import InvoiceViewHistory from "@/components/invoices/InvoiceViewHistory"');
    expect(src).toContain("{isInvoice && isStaff && <InvoiceViewHistory invoiceId={doc.id} />}");
  });

  it("InvoicesList has the Viewed column with a per-row testID", () => {
    const src = R("frontend/src/pages/invoices/InvoicesList.jsx");
    expect(src).toContain(">Viewed<");
    expect(src).toContain("invoice-viewed-${r.id}");
    expect(src).toContain("r.first_viewed_at");
  });

  it("PublicInvoicePay whitelists ?src= before forwarding", () => {
    const src = R("frontend/src/pages/public/PublicInvoicePay.jsx");
    expect(src).toContain("magicSrc={src}");
    expect(src).toMatch(/"email",\s*"sms",\s*"portal",\s*"link"/);
  });

  it("InvoiceView forwards magicSrc to the /full-magic query string", () => {
    const src = R("frontend/src/components/InvoiceView.jsx");
    expect(src).toContain("magicSrc");
    expect(src).toContain('params.set("src", magicSrc)');
  });
});

describe("Phase K47 · Mobile parity", () => {
  it("InvoiceViewHistory component exists (mobile)", () => {
    expect(
      existsSync(resolve(ROOT, "mobile/src/components/invoices/InvoiceViewHistory.tsx")),
    ).toBe(true);
    const src = R("mobile/src/components/invoices/InvoiceViewHistory.tsx");
    expect(src).toContain("invoice-view-history-card");
    expect(src).toContain("/invoices/${invoiceId}/views");
  });

  it("Invoice detail screen mounts the view-history component", () => {
    const src = R("mobile/app/invoice/[id].tsx");
    expect(src).toContain(
      // eslint concat splits the literal so the ImportValidator's naive
      // regex doesn't parse this as a real import specifier.
      'import InvoiceViewHistory ' +
      'from "@/src/components/invoices/InvoiceViewHistory"',
    );
    expect(src).toContain("<InvoiceViewHistory invoiceId={id!} />");
  });

  it("Mobile invoices list renders a Viewed pill", () => {
    const src = R("mobile/app/invoices.tsx");
    expect(src).toContain("invoice-viewed-${item.id}");
    expect(src).toContain("item.first_viewed_at");
  });
});
