/**
 * Feb 2026 · Public invoice Pay Now CTA + card-network icon row.
 *
 * Static source-lint lock-in for the redesigned ``PublicInvoicePay``
 * (``/pay/invoice/:id?token=<jwt>``) surface. Matches the pattern
 * used by ``invoice-pay-now-restyle.test.jsx``: read the .jsx as a
 * string and assert both the class list and the icon-row shape are
 * present. This is a styling change so no component mount is needed.
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";

const SRC = fs.readFileSync(
  path.resolve(__dirname, "../pages/public/PublicInvoicePay.jsx"),
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

describe("PublicInvoicePay · red Pay Now CTA + card icons", () => {
  it("Pay Now button uses the design-system red tokens with visible focus ring", () => {
    // bg-red-600 (surface), hover:bg-red-700 (hover), focus ring on
    // red-500 with an offset so it stays visible.
    expect(nearBoth(SRC, "public-invoice-pay-now", "bg-red-600")).toBe(true);
    expect(nearBoth(SRC, "public-invoice-pay-now", "hover:bg-red-700")).toBe(true);
    expect(nearBoth(SRC, "public-invoice-pay-now", "focus:ring-red-500")).toBe(true);
    expect(nearBoth(SRC, "public-invoice-pay-now", "focus:ring-offset-2")).toBe(true);
  });

  it("Pay Now button label reads \"Pay Now\" and interpolates the amount at ≥sm", () => {
    // Narrow-screen fallback is the compact "Pay Now"; ≥sm shows the
    // full "Pay Now - $X.XX" using the file's own fmtMoney helper.
    expect(SRC).toMatch(/>\s*Pay Now\s*</);
    expect(SRC).toMatch(/Pay Now - \$\$\{amountStr\}/);
    // Amount source is the fmtMoney helper — not a hardcoded string.
    expect(SRC).toMatch(/const amountStr = fmtMoney\(totalDue\)/);
  });

  it("renders all 4 card-network icons with aria-label + data-testid", () => {
    const networks = [
      { label: "Visa",             testId: "pay-icon-visa" },
      { label: "Mastercard",       testId: "pay-icon-mastercard" },
      { label: "American Express", testId: "pay-icon-amex" },
      { label: "Discover",         testId: "pay-icon-discover" },
    ];
    for (const { label, testId } of networks) {
      expect(SRC).toContain(`testId="${testId}"`);
      expect(SRC).toContain(`label="${label}"`);
    }
    // The <CardNetworkMark> component wires both attrs into the DOM
    // — aria-label={label} and data-testid={testId}.
    expect(SRC).toMatch(/aria-label=\{label\}/);
    expect(SRC).toMatch(/data-testid=\{testId\}/);
  });

  it("card-icon row is centered (flex + justify-center) and has mt-3 gap below the button", () => {
    // Icon-row container class list.
    expect(
      nearBoth(SRC, "public-invoice-pay-card-icons",
                "flex flex-row items-center justify-center gap-4"),
    ).toBe(true);
    // mt-3 gap from the button above.
    expect(nearBoth(SRC, "public-invoice-pay-card-icons", "\\bmt-3\\b")).toBe(true);
  });

  it("suppresses the InvoiceView toolbar duplicate when the top CTA is visible", () => {
    // Passing hideToolbarPayNow={canPay} collapses the sibling CTA
    // inside <InvoiceView> so the customer sees a single primary
    // action at the top of the page.
    expect(SRC).toMatch(/hideToolbarPayNow=\{canPay/);
  });
});
