/**
 * PORTAL-INVOICE-PAY-NOW-UX · Feb 2026 — DOM reorder + halo pulse
 * lock-in for the public invoice "Pay Now" CTA on BOTH magic-link
 * surfaces:
 *   • PublicInvoicePay.jsx   — /pay/invoice/:id?token=<jwt>
 *   • PublicInvoiceMagic.jsx — /i/:token
 *
 * Reorder: the ``credit-card-logos.png`` banner now sits ABOVE the
 * red Pay Now button on both surfaces (prior order was reversed).
 *
 * Halo: both buttons carry the shared ``public-invoice-pay-now-halo``
 * class defined in ``frontend/src/pages/public/public-invoice-pay-now.css``.
 * The class drives a looping red↔yellow ``box-shadow`` pulse, with a
 * ``prefers-reduced-motion: reduce`` branch that disables the
 * animation and paints a static ring instead.
 *
 * Follows the static-source lint convention of
 * ``public-invoice-pay-button.test.jsx`` — read the .jsx + .css
 * files as strings and assert the required structure, classes, and
 * media query are present. No component mount required.
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";

const PAY_SRC = fs.readFileSync(
  path.resolve(__dirname, "../pages/public/PublicInvoicePay.jsx"),
  "utf8",
);
const MAGIC_SRC = fs.readFileSync(
  path.resolve(__dirname, "../pages/public/PublicInvoiceMagic.jsx"),
  "utf8",
);
const HALO_CSS = fs.readFileSync(
  path.resolve(__dirname, "../pages/public/public-invoice-pay-now.css"),
  "utf8",
);

/** ``className`` and ``data-testid`` may sit either side of each
 * other in JSX, so matchers accept both directions. */
function nearBoth(src, testId, needle, window = 600) {
  const re = new RegExp(
    `${needle}[\\s\\S]{0,${window}}data-testid="${testId}"` +
    `|data-testid="${testId}"[\\s\\S]{0,${window}}${needle}`,
  );
  return re.test(src);
}

describe("PORTAL-INVOICE-PAY-NOW-UX · DOM reorder (logos above button)", () => {
  it("PublicInvoicePay — card-logos testid precedes pay-now testid in source", () => {
    const btnIdx = PAY_SRC.indexOf('data-testid="public-invoice-pay-now"');
    const imgIdx = PAY_SRC.indexOf('data-testid="public-invoice-pay-card-logos"');
    const wrapIdx = PAY_SRC.indexOf('data-testid="public-invoice-pay-card-logos-wrap"');
    expect(btnIdx).toBeGreaterThan(-1);
    expect(imgIdx).toBeGreaterThan(-1);
    expect(wrapIdx).toBeGreaterThan(-1);
    expect(btnIdx).toBeGreaterThan(imgIdx);
    expect(btnIdx).toBeGreaterThan(wrapIdx);
  });

  it("PublicInvoiceMagic — card-logos testid precedes pay-now testid in source", () => {
    const btnIdx = MAGIC_SRC.indexOf('data-testid="public-invoice-magic-pay-now"');
    const imgIdx = MAGIC_SRC.indexOf('data-testid="public-invoice-magic-card-logos"');
    const wrapIdx = MAGIC_SRC.indexOf('data-testid="public-invoice-magic-card-logos-wrap"');
    expect(btnIdx).toBeGreaterThan(-1);
    expect(imgIdx).toBeGreaterThan(-1);
    expect(wrapIdx).toBeGreaterThan(-1);
    expect(btnIdx).toBeGreaterThan(imgIdx);
    expect(btnIdx).toBeGreaterThan(wrapIdx);
  });

  it("PublicInvoicePay — preserves all pre-swap testids on the CTA block", () => {
    for (const tid of [
      "public-invoice-pay-cta-block",
      "public-invoice-pay-now",
      "public-invoice-pay-card-logos-wrap",
      "public-invoice-pay-card-logos",
      "public-invoice-pay-now-label-short",
      "public-invoice-pay-now-label-full",
    ]) {
      expect(PAY_SRC).toContain(`data-testid="${tid}"`);
    }
  });

  it("PublicInvoiceMagic — preserves all pre-swap testids on the CTA block", () => {
    for (const tid of [
      "public-invoice-magic-pay-now",
      "public-invoice-magic-card-logos-wrap",
      "public-invoice-magic-card-logos",
    ]) {
      expect(MAGIC_SRC).toContain(`data-testid="${tid}"`);
    }
  });
});

describe("PORTAL-INVOICE-PAY-NOW-UX · halo pulse class applied to both buttons", () => {
  it("PublicInvoicePay — pay-now button carries public-invoice-pay-now-halo class", () => {
    expect(
      nearBoth(PAY_SRC, "public-invoice-pay-now",
        "public-invoice-pay-now-halo", 600),
    ).toBe(true);
  });

  it("PublicInvoiceMagic — pay-now button carries public-invoice-pay-now-halo class", () => {
    expect(
      nearBoth(MAGIC_SRC, "public-invoice-magic-pay-now",
        "public-invoice-pay-now-halo", 600),
    ).toBe(true);
  });

  it("both files import the shared halo stylesheet", () => {
    expect(PAY_SRC).toMatch(/import\s+"\.\/public-invoice-pay-now\.css"/);
    expect(MAGIC_SRC).toMatch(/import\s+"\.\/public-invoice-pay-now\.css"/);
  });

  it("existing Stripe handler + canPay gate preserved on both surfaces", () => {
    // ``onClick={() => setPayOpen(true)}`` must still gate the modal.
    expect(nearBoth(PAY_SRC, "public-invoice-pay-now",
      "setPayOpen\\(true\\)", 600)).toBe(true);
    expect(nearBoth(MAGIC_SRC, "public-invoice-magic-pay-now",
      "setPayOpen\\(true\\)", 600)).toBe(true);
    // ``canPay`` ternary gate guards the whole block on both files.
    expect(PAY_SRC).toMatch(/const canPay =/);
    expect(MAGIC_SRC).toMatch(/const canPay =/);
    // PaymentForm modal is still mounted conditionally on payOpen.
    expect(PAY_SRC).toMatch(/\{payOpen \? \(\s*<PaymentForm/);
    expect(MAGIC_SRC).toMatch(/\{payOpen \? \(\s*<PaymentForm/);
  });

  it("existing design-system red tokens still live on the Pay Now button", () => {
    // Reorder + halo must NOT drop the bg-red-600 / hover:bg-red-700
    // / w-full / rounded-xl contract locked in by
    // invoice-pay-now-restyle.test.jsx.
    for (const cls of ["w-full", "bg-red-600", "hover:bg-red-700",
        "text-white", "font-semibold", "rounded-xl"]) {
      expect(nearBoth(PAY_SRC, "public-invoice-pay-now",
        cls.replace(/-/g, "\\-"), 600)).toBe(true);
      expect(nearBoth(MAGIC_SRC, "public-invoice-magic-pay-now",
        cls.replace(/-/g, "\\-"), 600)).toBe(true);
    }
  });

  it("focus ring on PublicInvoicePay button preserved after reorder", () => {
    // PublicInvoicePay specifically ships focus:outline-none +
    // focus:ring-2 + focus:ring-red-500 + focus:ring-offset-2.
    expect(nearBoth(PAY_SRC, "public-invoice-pay-now",
      "focus:ring-red-500", 600)).toBe(true);
    expect(nearBoth(PAY_SRC, "public-invoice-pay-now",
      "focus:ring-offset-2", 600)).toBe(true);
  });
});

describe("PORTAL-INVOICE-PAY-NOW-UX · halo stylesheet contract", () => {
  it("defines the public-invoice-pay-now-halo class with the scoped keyframe", () => {
    expect(HALO_CSS).toMatch(/\.public-invoice-pay-now-halo\s*\{/);
    expect(HALO_CSS).toMatch(
      /animation:\s*publicInvoicePayNowHalo\s+2s\s+ease-in-out\s+infinite/,
    );
  });

  it("declares the @keyframes rule with 0% / 50% / 100% stops", () => {
    expect(HALO_CSS).toMatch(/@keyframes\s+publicInvoicePayNowHalo\s*\{/);
    // 0% and 100% carry the red ring; 50% transitions through yellow.
    expect(HALO_CSS).toMatch(/0%\s*\{[\s\S]*?rgba\(239,\s*68,\s*68/);
    expect(HALO_CSS).toMatch(/50%\s*\{[\s\S]*?rgba\(250,\s*204,\s*21/);
    expect(HALO_CSS).toMatch(/100%\s*\{[\s\S]*?rgba\(239,\s*68,\s*68/);
  });

  it("cycles between red (239,68,68) and yellow (250,204,21) via box-shadow", () => {
    // Red stop + yellow stop both reach via box-shadow — never
    // via ``background`` so hover/disabled surface stays untouched.
    expect(HALO_CSS).toMatch(/box-shadow:/);
    expect(HALO_CSS).not.toMatch(/background:\s*(red|yellow|rgba\((239|250))/);
  });

  it("respects prefers-reduced-motion: reduce — disables animation + paints static ring", () => {
    expect(HALO_CSS).toMatch(
      /@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{[\s\S]*?\.public-invoice-pay-now-halo[\s\S]*?animation:\s*none/,
    );
    // Static ring fallback so the CTA stays emphasised under
    // reduced-motion.
    expect(HALO_CSS).toMatch(
      /@media\s*\(prefers-reduced-motion:\s*reduce\)[\s\S]*?box-shadow:/,
    );
  });

  it("keeps click target clean — no pointer-events override, no transform", () => {
    // Guardrail — halo must never block clicks or shift the button
    // off its natural position.
    expect(HALO_CSS).not.toMatch(/pointer-events\s*:/);
    expect(HALO_CSS).not.toMatch(/\btransform\s*:/);
  });
});

describe("PORTAL-INVOICE-PAY-NOW-UX · spacing after reorder", () => {
  it("PublicInvoicePay — card-logos wrap carries mb-3 (gap above the button)", () => {
    expect(
      nearBoth(PAY_SRC, "public-invoice-pay-card-logos-wrap",
        "\\bmb-3\\b", 600),
    ).toBe(true);
    // The old ``mt-3`` (gap from the button above) is now gone —
    // the banner is the top-of-block element so top-margin would
    // be dead-weight. Guard against reintroduction.
    expect(
      nearBoth(PAY_SRC, "public-invoice-pay-card-logos-wrap",
        "\\bmt-3\\b", 600),
    ).toBe(false);
  });

  it("PublicInvoiceMagic — card-logos wrap carries mb-3 (gap above the button)", () => {
    expect(
      nearBoth(MAGIC_SRC, "public-invoice-magic-card-logos-wrap",
        "\\bmb-3\\b", 600),
    ).toBe(true);
    expect(
      nearBoth(MAGIC_SRC, "public-invoice-magic-card-logos-wrap",
        "\\bmt-3\\b", 600),
    ).toBe(false);
  });
});
