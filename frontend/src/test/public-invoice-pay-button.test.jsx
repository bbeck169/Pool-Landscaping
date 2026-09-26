/**
 * Feb 2026 · Public invoice Pay Now CTA + card-logos composite banner.
 *
 * Static source-lint lock-in for both public magic-link surfaces:
 *   • ``PublicInvoicePay``  — /pay/invoice/:id?token=<jwt>
 *   • ``PublicInvoiceMagic`` — /i/:token
 *
 * Both now render the same ``credit-card-logos.png`` banner in
 * ``frontend/public/logos/`` directly below the red Pay Now button.
 * Matches the pattern used by ``invoice-pay-now-restyle.test.jsx``:
 * read the .jsx as a string and assert the classes / attrs / order
 * are present. This is a styling swap so no component mount is
 * needed.
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";

const PAY_SRC   = fs.readFileSync(
  path.resolve(__dirname, "../pages/public/PublicInvoicePay.jsx"),
  "utf8",
);
const MAGIC_SRC = fs.readFileSync(
  path.resolve(__dirname, "../pages/public/PublicInvoiceMagic.jsx"),
  "utf8",
);

/** ``className`` and ``data-testid`` can be in either order in JSX. */
function nearBoth(src, testId, needle, window = 600) {
  const re = new RegExp(
    `${needle}[\\s\\S]{0,${window}}data-testid="${testId}"` +
    `|data-testid="${testId}"[\\s\\S]{0,${window}}${needle}`,
  );
  return re.test(src);
}

describe("PublicInvoicePay · red Pay Now CTA + card-logos banner", () => {
  it("Pay Now button uses the design-system red tokens with visible focus ring", () => {
    // bg-red-600 (surface), hover:bg-red-700 (hover), focus ring on
    // red-500 with an offset so it stays visible.
    expect(nearBoth(PAY_SRC, "public-invoice-pay-now", "bg-red-600")).toBe(true);
    expect(nearBoth(PAY_SRC, "public-invoice-pay-now", "hover:bg-red-700")).toBe(true);
    expect(nearBoth(PAY_SRC, "public-invoice-pay-now", "focus:ring-red-500")).toBe(true);
    expect(nearBoth(PAY_SRC, "public-invoice-pay-now", "focus:ring-offset-2")).toBe(true);
  });

  it("Pay Now button label reads \"Pay Now\" and interpolates the amount at ≥sm", () => {
    // Narrow-screen fallback is the compact "Pay Now"; ≥sm shows the
    // full "Pay Now - $X.XX" using the file's own fmtMoney helper.
    expect(PAY_SRC).toMatch(/>\s*Pay Now\s*</);
    expect(PAY_SRC).toMatch(/Pay Now - \$\$\{amountStr\}/);
    // Amount source is the fmtMoney helper — not a hardcoded string.
    expect(PAY_SRC).toMatch(/const amountStr = fmtMoney\(totalDue\)/);
  });

  it("renders the single composite card-logos image with correct src, alt, and classes", () => {
    // The four inline SVG badges were replaced with one PNG asset in
    // ``frontend/public/logos/``. ``h-8 w-auto`` keeps the same visual
    // height; ``mx-auto block`` centers it inside its parent.
    expect(PAY_SRC).toContain('src="/logos/credit-card-logos.png"');
    expect(PAY_SRC).toContain('alt="Cards accepted"');
    expect(
      nearBoth(PAY_SRC, "public-invoice-pay-card-logos", "\\bh-8\\b"),
    ).toBe(true);
    expect(
      nearBoth(PAY_SRC, "public-invoice-pay-card-logos", "\\bw-auto\\b"),
    ).toBe(true);
    expect(
      nearBoth(PAY_SRC, "public-invoice-pay-card-logos", "\\bmx-auto\\b"),
    ).toBe(true);
    // No lingering inline SVG helper — the four per-network testIDs
    // are gone.
    expect(PAY_SRC).not.toMatch(/CardNetworkMark\s*\(/);
    expect(PAY_SRC).not.toContain('data-testid="pay-icon-visa"');
    expect(PAY_SRC).not.toContain('data-testid="pay-icon-mastercard"');
    expect(PAY_SRC).not.toContain('data-testid="pay-icon-amex"');
    expect(PAY_SRC).not.toContain('data-testid="pay-icon-discover"');
  });

  it("card-logos wrapper is centered (flex + justify-center) with mt-3 gap below the button", () => {
    // Wrapper class list.
    expect(
      nearBoth(PAY_SRC, "public-invoice-pay-card-logos-wrap",
                "flex justify-center"),
    ).toBe(true);
    // mt-3 gap from the Pay Now button above.
    expect(
      nearBoth(PAY_SRC, "public-invoice-pay-card-logos-wrap", "\\bmt-3\\b"),
    ).toBe(true);
  });

  it("suppresses the InvoiceView toolbar duplicate when the top CTA is visible", () => {
    // Passing hideToolbarPayNow={canPay} collapses the sibling CTA
    // inside <InvoiceView> so the customer sees a single primary
    // action at the top of the page.
    expect(PAY_SRC).toMatch(/hideToolbarPayNow=\{canPay/);
  });
});

describe("PublicInvoiceMagic · mirrors the composite card-logos banner", () => {
  it("renders the same /logos/credit-card-logos.png banner directly under its Pay Now button", () => {
    // Same asset path.
    expect(MAGIC_SRC).toContain('src="/logos/credit-card-logos.png"');
    // Same accessibility copy.
    expect(MAGIC_SRC).toContain('alt="Cards accepted"');
    // Same class shape (h-8 + w-auto + mx-auto + block) so both
    // surfaces render an identical banner.
    expect(
      nearBoth(MAGIC_SRC, "public-invoice-magic-card-logos", "\\bh-8\\b"),
    ).toBe(true);
    expect(
      nearBoth(MAGIC_SRC, "public-invoice-magic-card-logos", "\\bw-auto\\b"),
    ).toBe(true);
    expect(
      nearBoth(MAGIC_SRC, "public-invoice-magic-card-logos", "\\bmx-auto\\b"),
    ).toBe(true);
    // Wrapper is centered.
    expect(
      nearBoth(MAGIC_SRC, "public-invoice-magic-card-logos-wrap",
                "flex justify-center"),
    ).toBe(true);
    // The image block must sit AFTER the pay-now button in source
    // order — that's what places it directly below on the page.
    const btnIdx = MAGIC_SRC.indexOf('data-testid="public-invoice-magic-pay-now"');
    const imgIdx = MAGIC_SRC.indexOf('data-testid="public-invoice-magic-card-logos"');
    expect(btnIdx).toBeGreaterThan(-1);
    expect(imgIdx).toBeGreaterThan(btnIdx);
  });
});
