/**
 * Feb-2026 · P0 Bug B lock-in — Pay Now visibility on InvoiceView.
 *
 * Static source-lint (no full DOM mount — the InvoiceView component
 * pulls in the entire aggregator response shape, which is too much
 * scaffolding for a lint-level ship guard). If the CTA regresses
 * (someone removes it or hides it behind the wrong condition),
 * this test fires BEFORE the customer-facing bug ships.
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";

const IV_SRC = fs.readFileSync(
  path.resolve(__dirname, "../components/InvoiceView.jsx"),
  "utf8",
);

const IV_CSS = fs.readFileSync(
  path.resolve(__dirname, "../components/InvoiceView.css"),
  "utf8",
);


describe("P0 Bug B · Pay Now CTA on the customer-facing invoice", () => {
  it("Toolbar Pay Now button carries the stable testid", () => {
    expect(IV_SRC).toMatch(/data-testid="invoice-pay-now-btn"/);
  });

  it("Pay Now is gated on canPay (payment_status != paid AND total_due > 0)", () => {
    // Regression guard — someone flipping the gate to
    // ``payment_status === 'paid'`` (i.e. the OPPOSITE) would
    // silently hide the CTA for every unpaid customer.
    expect(IV_SRC).toMatch(
      /canPay\s*=\s*\(payment_status\s*\|\|\s*""\)\.toLowerCase\(\)\s*!==\s*"paid"[\s\S]{0,80}totals\?\.total_due/,
    );
  });

  it("Toolbar Pay Now label shows the outstanding amount, not generic 'Pay Now'", () => {
    // Feb-2026 P0 spec — button copy is ``Pay $XXX.XX``. As of the
    // Feb-2026 currency-format standardization, the label routes
    // through the canonical ``formatCurrency`` helper (which
    // emits the ``$`` prefix itself) so the source shape is now
    // ``Pay {formatCurrency(totals?.total_due || 0)}``.
    expect(IV_SRC).toMatch(/Pay \{formatCurrency\(totals\?\.total_due/);
  });

  it("Toolbar Pay Now uses the design-system red danger tone (Feb 2026 restyle)", () => {
    // Feb 2026 · Invoice Pay Now restyle — the top pay CTA moved from
    // landscape-green (#059669) to the design-system red token
    // (bg-red-600 / hover:bg-red-700) so the customer-facing invoice
    // page has a single, prominent, full-width Pay Now that visually
    // separates from the toolbar's secondary actions.
    expect(IV_SRC).toContain('data-testid="invoice-pay-now-btn"');
    // ``className`` sits ABOVE the testid in the JSX (order-agnostic).
    expect(IV_SRC).toMatch(
      /bg-red-600[\s\S]{0,600}data-testid="invoice-pay-now-btn"|invoice-pay-now-btn[\s\S]{0,600}bg-red-600/,
    );
    expect(IV_SRC).toMatch(
      /hover:bg-red-700[\s\S]{0,600}data-testid="invoice-pay-now-btn"|invoice-pay-now-btn[\s\S]{0,600}hover:bg-red-700/,
    );
    // Legacy landscape-green is gone from the CTA block.
    expect(IV_SRC).not.toMatch(
      /invoice-pay-now-btn[\s\S]{0,600}background:\s*"#059669"/,
    );
  });

  it("Toolbar Pay Now spans the full width of its container (Feb 2026 restyle)", () => {
    // Full-width contract — Tailwind ``w-full`` on the button + a
    // ``flex-basis: 100%`` wrapper so secondary toolbar buttons wrap
    // to the next row instead of overflowing.
    expect(IV_SRC).toMatch(
      /\bw-full\b[\s\S]{0,400}data-testid="invoice-pay-now-btn"|invoice-pay-now-btn[\s\S]{0,400}\bw-full\b/,
    );
    expect(IV_SRC).toMatch(
      /invoice-pay-now-wrapper[\s\S]{0,400}flex:\s*"1 1 100%"|flex:\s*"1 1 100%"[\s\S]{0,400}invoice-pay-now-wrapper/,
    );
  });

  it("Toolbar CSS enables flex-wrap so the full-width Pay CTA lays out cleanly", () => {
    expect(IV_CSS).toMatch(/\.iv-toolbar\s*\{[\s\S]{0,400}flex-wrap:\s*wrap/);
  });

  it("Sticky mobile pay bar renders when there's a balance", () => {
    expect(IV_SRC).toMatch(/data-testid="invoice-mobile-pay-bar"/);
    expect(IV_SRC).toMatch(/data-testid="invoice-mobile-pay-btn"/);
    expect(IV_SRC).toMatch(/iv-mobile-pay-bar/);
  });

  it("Mobile pay bar is hidden on tablet+ viewports (max-width: 640px gate)", () => {
    // The CSS must gate the bar behind the phone media query so
    // desktop users don't see a floating full-width bar.
    expect(IV_CSS).toMatch(/\.iv-mobile-pay-bar\s*\{\s*display:\s*none/);
    expect(IV_CSS).toMatch(/@media\s*\(max-width:\s*640px\)[\s\S]{0,1200}\.iv-mobile-pay-bar\s*\{[\s\S]{0,200}display:\s*block/);
  });

  it("Mobile pay bar hides in printable mode", () => {
    // ``!printable && canPay`` is the ONLY gate that mounts the bar.
    expect(IV_SRC).toMatch(
      /!printable\s*&&\s*canPay\s*\?\s*\(\s*<div\s+className="iv-mobile-pay-bar"/,
    );
  });

  it("Mobile pay bar shows the outstanding balance in the CTA copy", () => {
    // Feb-2026 currency-format standardization — same shape as
    // the toolbar CTA.
    expect(IV_SRC).toMatch(/iv-mobile-pay-btn[\s\S]{0,400}Pay \{formatCurrency/);
  });

  it("Both CTAs open the same PaymentForm modal (single flow)", () => {
    // Regression guard — someone splitting the mobile CTA into a
    // separate flow would fork the save-on-first-payment logic.
    // Order-agnostic — setPayOpen may sit above OR below the testid.
    expect(IV_SRC).toMatch(
      /setPayOpen\(true\)[\s\S]{0,400}invoice-pay-now-btn|invoice-pay-now-btn[\s\S]{0,400}setPayOpen\(true\)/,
    );
    expect(IV_SRC).toMatch(
      /setPayOpen\(true\)[\s\S]{0,400}invoice-mobile-pay-btn|invoice-mobile-pay-btn[\s\S]{0,400}setPayOpen\(true\)/,
    );
  });
});
