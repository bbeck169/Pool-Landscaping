/**
 * Phase 47d · Feb 2026 — Mobile quote-pay Stripe-direct migration.
 *
 * Source-inspection guard for `mobile/app/quote/[id].tsx`.
 *   • Must call `POST /invoices/{id}/request-payment-link` (the Phase-47
 *     endpoint), NOT the mythical `/payments/admin/generate-link/{id}`.
 *   • Must read `payment_url` off the response (matches the Phase-47
 *     backend contract).
 *   • No Lumino / Zapier references remain on the mobile pay path.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";

const _mobileQuote = readFileSync(
  resolve(__dirname, "../../../mobile/app/quote/[id].tsx"),
  "utf8",
);

describe("Phase 47d · mobile quote-pay Stripe-direct migration", () => {
  it("no longer calls the mythical /payments/admin/generate-link/{id} endpoint", () => {
    // Strip comments — the migration comment names the mythical
    // endpoint on purpose so future maintainers understand the swap.
    const codeOnly = _mobileQuote
      .replace(/\/\*[\s\S]*?\*\//g, "")
      .replace(/^\s*\/\/.*$/gm, "");
    expect(codeOnly).not.toContain("/payments/admin/generate-link/");
  });

  it("calls the Phase-47 /invoices/{id}/request-payment-link endpoint", () => {
    expect(_mobileQuote).toContain("/invoices/${id}/request-payment-link");
  });

  it("destructures payment_url off the response for the Share sheet", () => {
    expect(_mobileQuote).toMatch(
      /const\s*\{\s*payment_url\s*\}\s*=\s*await\s+api\.post\(/,
    );
  });

  it("has no Lumino / Zapier / dispatch references on the pay path", () => {
    // Strip comments before scanning — the migration docstring names
    // both providers on purpose so future maintainers know why we
    // moved off them.
    const codeOnly = _mobileQuote
      .replace(/\/\*[\s\S]*?\*\//g, "")
      .replace(/^\s*\/\/.*$/gm, "");
    expect(codeOnly).not.toMatch(/lumino/i);
    expect(codeOnly).not.toMatch(/zapier/i);
    expect(codeOnly).not.toContain("dispatch_invoice_link_request");
  });

  it("preserves the recordManual → /quotes/${id}/pay call (manual/offline)", () => {
    // Phase 47d audit confirmed the ledger path stays. Regression guard.
    expect(_mobileQuote).toContain("/quotes/${id}/pay");
    expect(_mobileQuote).toMatch(/record\s*(manual|offline)/i);
  });
});
