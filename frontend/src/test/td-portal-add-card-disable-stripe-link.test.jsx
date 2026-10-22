/**
 * TD-portal-add-card-disable-stripe-link · Feb-2026 — source-inspection
 * regression suite.
 *
 * Guards the three FE Stripe Elements surfaces that render an
 * Add-Card UI inside the authenticated / semi-authenticated customer
 * surfaces:
 *
 *   1. components/payments/StripeAddCardForm.jsx     — portal + admin
 *      Customer Detail Payments tab (via PaymentMethodTiles).
 *   2. pages/public/AddCardPage.jsx                  — magic-link
 *      public /portal/add-card page.
 *   3. pages/BusinessSignup.jsx                      — tenant signup
 *      card-on-file form.
 *
 * Each surface MUST pass `wallets: { link: "never", applePay: "never",
 * googlePay: "never" }` on the <Elements> provider options. This
 * disables Stripe Link's browser-side account auto-detection — closing
 * the admin-impersonation / shared-browser cross-contamination leak
 * documented in memory/td_portal_add_card_disable_stripe_link_phase0
 * _recon.md (Section 5 "Admin impersonation + Link cross-contamination").
 *
 * Source-inspection pattern (readFileSync + regex) is deliberate so
 * the guard works without instantiating Stripe mocks and survives
 * component refactors that move state around.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";

const SURFACES = [
  {
    label: "StripeAddCardForm (portal + admin Customer Detail)",
    path: resolve(__dirname, "../components/payments/StripeAddCardForm.jsx"),
  },
  {
    label: "AddCardPage (magic-link add-card)",
    path: resolve(__dirname, "../pages/public/AddCardPage.jsx"),
  },
  {
    label: "BusinessSignup (tenant signup card-on-file)",
    path: resolve(__dirname, "../pages/BusinessSignup.jsx"),
  },
];

describe("TD-portal-add-card-disable-stripe-link · FE Elements wallet config", () => {
  for (const { label, path } of SURFACES) {
    const src = readFileSync(path, "utf8");

    it(`${label}: Elements options disable Stripe Link`, () => {
      // Must set wallets.link = "never" somewhere in the file.
      expect(src).toMatch(/wallets\s*:\s*\{[^}]*link\s*:\s*["']never["']/);
    });

    it(`${label}: Elements options also disable Apple Pay`, () => {
      expect(src).toMatch(/wallets\s*:\s*\{[^}]*applePay\s*:\s*["']never["']/);
    });

    it(`${label}: Elements options also disable Google Pay`, () => {
      expect(src).toMatch(/wallets\s*:\s*\{[^}]*googlePay\s*:\s*["']never["']/);
    });

    it(`${label}: ticket reference is present in the file`, () => {
      expect(src).toContain("TD-portal-add-card-disable-stripe-link");
    });
  }
});

describe("TD-portal-add-card-disable-stripe-link · PaymentElement retained", () => {
  // D5 — keep PaymentElement on the two surfaces that use it; do NOT
  // switch to CardElement. The desired-state screenshot shows the
  // Card/Bank tabs UX which only PaymentElement provides.
  it("StripeAddCardForm still mounts <PaymentElement>", () => {
    const src = readFileSync(
      resolve(__dirname, "../components/payments/StripeAddCardForm.jsx"),
      "utf8",
    );
    expect(src).toMatch(/<PaymentElement\b/);
    expect(src).not.toMatch(/<CardElement\b/);
  });

  it("AddCardPage still mounts <PaymentElement>", () => {
    const src = readFileSync(
      resolve(__dirname, "../pages/public/AddCardPage.jsx"),
      "utf8",
    );
    expect(src).toMatch(/<PaymentElement\b/);
    expect(src).not.toMatch(/<CardElement\b/);
  });
});
