/**
 * Feb 2026 · Invoice Pay Now restyle lock-in.
 *
 * Static source-lint asserting BOTH customer-facing invoice viewers
 * ship the same full-width red Pay Now CTA at the top of the page:
 *   1. ``PublicInvoiceMagic`` (/i/:token) → shared ``InvoiceView``
 *      toolbar CTA (``invoice-pay-now-btn``).
 *   2. ``PortalInvoiceDetail`` (/portal/invoices/:id) → its own
 *      top-of-page ``port-pay`` CTA rendered above the InvoiceView.
 *
 * The two buttons intentionally share the same design-system red
 * tokens (``bg-red-600 hover:bg-red-700``) so the customer sees a
 * consistent primary action regardless of which surface the email
 * link routes them to.
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";

const IV_SRC = fs.readFileSync(
  path.resolve(__dirname, "../components/InvoiceView.jsx"),
  "utf8",
);

const PORTAL_SRC = fs.readFileSync(
  path.resolve(__dirname, "../pages/portal/PortalPages.jsx"),
  "utf8",
);


// ── helpers ────────────────────────────────────────────────────────
// The className attribute in JSX sits ABOVE the ``data-testid`` on
// each button in this codebase, so every "class near testid" check
// needs to accept either directional ordering.
function nearBoth(src, testId, needle, window = 400) {
  const re = new RegExp(
    `${needle}[\\s\\S]{0,${window}}data-testid="${testId}"` +
    `|data-testid="${testId}"[\\s\\S]{0,${window}}${needle}`,
  );
  return re.test(src);
}


describe("Invoice Pay Now restyle · InvoiceView (top-of-page CTA)", () => {
  it("uses the design-system red tokens (bg-red-600 hover:bg-red-700)", () => {
    expect(nearBoth(IV_SRC, "invoice-pay-now-btn", "bg-red-600", 600)).toBe(true);
    expect(
      nearBoth(IV_SRC, "invoice-pay-now-btn", "hover:bg-red-700", 600),
    ).toBe(true);
  });

  it("spans the full width of its container (w-full class)", () => {
    expect(nearBoth(IV_SRC, "invoice-pay-now-btn", "\\bw-full\\b", 400)).toBe(true);
  });

  it("no raw red hex on the CTA — design-system tokens only", () => {
    const startIdx = IV_SRC.indexOf("invoice-pay-now-wrapper");
    const endIdx = IV_SRC.indexOf("</button>", startIdx);
    expect(startIdx).toBeGreaterThan(-1);
    expect(endIdx).toBeGreaterThan(startIdx);
    const ctaBlock = IV_SRC.slice(startIdx, endIdx);
    expect(ctaBlock).not.toMatch(/#(DC2626|B91C1C|EF4444|FEE2E2)/i);
    expect(ctaBlock).not.toMatch(/background:\s*"#[a-f0-9]{6}"/i);
  });

  it("wrapper forces flex-basis 100% + order:-1 so the CTA occupies its own row", () => {
    expect(IV_SRC).toMatch(
      /invoice-pay-now-wrapper[\s\S]{0,400}flex:\s*"1 1 100%"[\s\S]{0,200}order:\s*-1|invoice-pay-now-wrapper[\s\S]{0,400}order:\s*-1[\s\S]{0,200}flex:\s*"1 1 100%"/,
    );
  });

  it("preserves canPay gate (only shows when not paid AND balance > 0)", () => {
    expect(IV_SRC).toMatch(/\{canPay \? \(/);
  });

  it("preserves the onClick handler that opens the PaymentForm modal", () => {
    expect(
      nearBoth(IV_SRC, "invoice-pay-now-btn", "setPayOpen\\(true\\)", 400),
    ).toBe(true);
  });

  it("keeps the CreditCard icon + balance-aware label", () => {
    // Both should be within a ~800-char window around the testid.
    expect(IV_SRC).toMatch(
      /invoice-pay-now-btn[\s\S]{0,800}<CreditCard[\s\S]{0,400}Pay \$\{fmtMoney/,
    );
  });
});


describe("Invoice Pay Now restyle · PortalInvoiceDetail top port-pay CTA", () => {
  it("port-pay button uses the design-system red tokens", () => {
    expect(nearBoth(PORTAL_SRC, "port-pay", "bg-red-600", 400)).toBe(true);
    expect(nearBoth(PORTAL_SRC, "port-pay", "hover:bg-red-700", 400)).toBe(true);
  });

  it("port-pay button spans the full width of its container (w-full)", () => {
    expect(nearBoth(PORTAL_SRC, "port-pay", "\\bw-full\\b", 400)).toBe(true);
  });

  it("port-pay preserves the paid/balance gate (honest CTA)", () => {
    // Feb 2026 · P0 Bug B — CTA must not fire on paid invoices with
    // stale amount_paid.
    expect(PORTAL_SRC).toMatch(
      /balance > 0\s*&&\s*\(doc\?\.payment_status \|\| ""\)\.toLowerCase\(\) !== "paid"/,
    );
  });

  it("port-pay preserves the onClick payment-form modal handler", () => {
    expect(nearBoth(PORTAL_SRC, "port-pay", "setPayNowOpen\\(true\\)", 600))
      .toBe(true);
  });

  it("port-pay preserves the CreditCard icon + `Pay ${money(balance)}` copy", () => {
    // testid → forward window into the closing </button>.
    const idx = PORTAL_SRC.indexOf('data-testid="port-pay"');
    expect(idx).toBeGreaterThan(-1);
    const forward = PORTAL_SRC.slice(idx, idx + 600);
    expect(forward).toMatch(/<CreditCard/);
    expect(forward).toMatch(/Pay \$\{money\(balance\)\}/);
  });

  it("no raw red hex on the port-pay CTA either", () => {
    const startIdx = PORTAL_SRC.indexOf('data-testid="port-pay"');
    expect(startIdx).toBeGreaterThan(-1);
    const openIdx = PORTAL_SRC.lastIndexOf("<button", startIdx);
    const closeIdx = PORTAL_SRC.indexOf("</button>", startIdx);
    const block = PORTAL_SRC.slice(openIdx, closeIdx);
    expect(block).not.toMatch(/#(DC2626|B91C1C|EF4444|FEE2E2)/i);
  });
});


describe("Invoice Pay Now restyle · consistency between the two viewers", () => {
  it("BOTH CTAs use the SAME red-600 / red-700 design-system tokens", () => {
    // Locks in the "same class list on both" contract so a future
    // edit that ships red-500 or red-700 on one but not the other
    // fails CI.
    expect(nearBoth(IV_SRC, "invoice-pay-now-btn", "bg-red-600", 600)).toBe(true);
    expect(nearBoth(PORTAL_SRC, "port-pay", "bg-red-600", 400)).toBe(true);
    expect(
      nearBoth(IV_SRC, "invoice-pay-now-btn", "hover:bg-red-700", 600),
    ).toBe(true);
    expect(nearBoth(PORTAL_SRC, "port-pay", "hover:bg-red-700", 400)).toBe(true);
  });

  it("BOTH CTAs use w-full (full-width contract)", () => {
    expect(nearBoth(IV_SRC, "invoice-pay-now-btn", "\\bw-full\\b", 400)).toBe(true);
    expect(nearBoth(PORTAL_SRC, "port-pay", "\\bw-full\\b", 400)).toBe(true);
  });
});
