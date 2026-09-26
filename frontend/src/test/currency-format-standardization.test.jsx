/**
 * Feb 2026 · Currency-format standardization on <EstimateView> +
 * <InvoiceView>.
 *
 * Both surfaces now route every money field through the canonical
 * ``formatCurrency`` helper in ``components/reports/formatters.js``
 * so both render "$333,333.33" (US locale, comma-grouped, 2-decimal,
 * ``$`` prefix). The local ``fmt`` / ``fmtMoney`` helpers are
 * preserved only for the non-money carve-outs:
 *
 *   EstimateView.jsx — ``bh``, ``t_bh``, ``margin_pct``, ``total_b_hrs``
 *     (billable hours + margin percent)
 *   InvoiceView.jsx  — ``li.percent`` (line-item discount %)
 *
 * This suite mixes ONE runtime formatCurrency assertion (to pin
 * the exact visual contract) with static source-lint over the two
 * .jsx files (matches the pattern already used by
 * ``invoice-pay-now-restyle.test.jsx`` — no component mount).
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";
import { formatCurrency } from "../components/reports/formatters";

const ESTIMATE_SRC = fs.readFileSync(
  path.resolve(__dirname, "../components/EstimateView.jsx"),
  "utf8",
);
const INVOICE_SRC = fs.readFileSync(
  path.resolve(__dirname, "../components/InvoiceView.jsx"),
  "utf8",
);

describe("Currency standardization · $333,333.33 shape", () => {
  it("``formatCurrency(333333.33)`` returns the exact ``$333,333.33`` contract from the spec title", () => {
    // The canonical helper is ``v.toLocaleString('en-US',
    // { style: 'currency', currency: 'USD', minimumFractionDigits: 2,
    // maximumFractionDigits: 2 })`` — locks the visual shape:
    //   * ``$`` prefix, no space
    //   * comma-grouped thousands
    //   * exactly 2 decimals
    expect(formatCurrency(333333.33)).toBe("$333,333.33");
    // Rep line-item total from the spec's other examples.
    expect(formatCurrency(33445)).toBe("$33,445.00");
    // Small value + zero, both keep the 2-decimal shape.
    expect(formatCurrency(120)).toBe("$120.00");
    expect(formatCurrency(0)).toBe("$0.00");
  });

  it("EstimateView imports ``formatCurrency`` and applies it to every money site", () => {
    expect(ESTIMATE_SRC).toMatch(
      /import\s+\{\s*formatCurrency\s*\}\s+from\s+"@\/components\/reports\/formatters"/,
    );
    // Representative sample of the 16 money sites — group subtotal
    // (× 2, desktop + mobile), line-item ``cost_rate`` / ``m_rate``
    // / ``t_b_cost`` / ``total`` (desktop + mobile card), summary
    // ``subtotal`` / ``taxes`` / ``amount_paid`` /
    // ``total_estimated_cost`` / ``estimated_profit`` /
    // ``total_b_hrs_revenue``, adjusted-total original + adjusted,
    // decline-modal.
    for (const call of [
      "formatCurrency(g.subtotal)",
      "formatCurrency(li.cost_rate)",
      "formatCurrency(li.m_rate)",
      "formatCurrency(li.t_b_cost)",
      "formatCurrency(li.total)",
      "formatCurrency(totals.subtotal)",
      "formatCurrency(totals.taxes)",
      "formatCurrency(totals.amount_paid)",
      "formatCurrency(totals.total_estimated_cost)",
      "formatCurrency(totals.original_total)",
      "formatCurrency(totals.adjusted_total)",
      "formatCurrency(totals.estimated_profit)",
      "formatCurrency(totals.total_b_hrs_revenue)",
      "formatCurrency(line_items[lineDeclineOpen]?.total)",
    ]) {
      expect(ESTIMATE_SRC, `missing ${call}`).toContain(call);
    }
  });

  it("EstimateView preserves ``fmt(...)`` for the 4 non-money carve-outs (hours + margin %)", () => {
    // Explicit non-money contract per the spec:
    //   * ``bh`` / ``t_bh`` / ``total_b_hrs`` — billable hours
    //   * ``margin_pct`` — percentage
    // These must NOT flow through formatCurrency, or hours/%
    // fields would print with a spurious ``$``.
    expect(ESTIMATE_SRC).toContain("{fmt(li.bh)}");
    expect(ESTIMATE_SRC).toContain("{fmt(li.t_bh)}");
    expect(ESTIMATE_SRC).toContain("{fmt(li.margin_pct)}");
    expect(ESTIMATE_SRC).toContain("{fmt(totals.total_b_hrs)}");
    // And explicitly assert NONE of the four appear routed
    // through formatCurrency.
    expect(ESTIMATE_SRC).not.toContain("formatCurrency(li.bh)");
    expect(ESTIMATE_SRC).not.toContain("formatCurrency(li.t_bh)");
    expect(ESTIMATE_SRC).not.toContain("formatCurrency(li.margin_pct)");
    expect(ESTIMATE_SRC).not.toContain("formatCurrency(totals.total_b_hrs)");
  });

  it("neither EstimateView nor InvoiceView emit a literal ``$`` prefix adjacent to formatCurrency", () => {
    // The canonical helper already emits ``$`` — a lingering
    // literal prefix would produce ``$$333,333.33`` when
    // formatCurrency runs. This guard also catches the historical
    // ``$${fmt(...)}`` shape in template literals.
    //
    // The regex hits ANY of:
    //   * ``${formatCurrency(...)}`` — the template-literal double-$
    //   * ``$${formatCurrency(...)}`` — an escaped-double-$ variant
    expect(ESTIMATE_SRC).not.toMatch(/\$\{formatCurrency/);
    expect(ESTIMATE_SRC).not.toMatch(/\$\$/);
    expect(INVOICE_SRC).not.toMatch(/\$\{formatCurrency/);
    expect(INVOICE_SRC).not.toMatch(/\$\$/);
  });

  it("InvoiceView imports ``formatCurrency`` and applies it to every money site (li.percent kept on fmtMoney)", () => {
    expect(INVOICE_SRC).toMatch(
      /import\s+\{\s*formatCurrency\s*\}\s+from\s+"@\/components\/reports\/formatters"/,
    );
    // Every money site — header, line-item ``cost_rate`` / ``total``,
    // summary block, footer stub.
    for (const call of [
      "formatCurrency(header.credit_available)",
      "formatCurrency(header.outstanding_balance)",
      "formatCurrency(li.cost_rate)",
      "formatCurrency(li.total)",
      "formatCurrency(totals.subtotal)",
      "formatCurrency(totals.this_invoice)",
      "formatCurrency(totals.amount_paid)",
      "formatCurrency(totals.total_due)",
      "formatCurrency(totals?.total_due || 0)",
    ]) {
      expect(INVOICE_SRC, `missing ${call}`).toContain(call);
    }
    // The single non-money carve-out — line-item discount % —
    // stays on the local ``fmtMoney`` helper so the percent
    // cell doesn't accidentally print with a leading ``$``.
    expect(INVOICE_SRC).toContain("{fmtMoney(li.percent)}");
    // But no OTHER ``fmtMoney(...)`` JSX call site should
    // remain. Match on the JSX-cell shape ``{fmtMoney(...)}``
    // — this specifically excludes the ``function fmtMoney(n)``
    // definition and any JSDoc reference to the helper's name.
    const callSites = INVOICE_SRC.match(/\{fmtMoney\(/g) || [];
    expect(callSites.length).toBe(1);
  });

  it("InvoiceView pay CTA labels use formatCurrency without a literal ``$`` prefix", () => {
    // Both pay CTAs — the desktop toolbar one and the mobile pay
    // bar — must read ``Pay {formatCurrency(...)}``, not the old
    // ``Pay ${fmtMoney(...)}`` shape (which would render as
    // ``Pay $$120.00`` post-swap). The button block is long
    // (~600 chars from test-id to label), so span the whole
    // button by looking forward until the closing ``</button>``.
    const idxToolbar = INVOICE_SRC.indexOf('data-testid="invoice-pay-now-btn"');
    expect(idxToolbar).toBeGreaterThan(-1);
    const btnEnd = INVOICE_SRC.indexOf("</button>", idxToolbar);
    expect(btnEnd).toBeGreaterThan(idxToolbar);
    const toolbarSlice = INVOICE_SRC.slice(idxToolbar, btnEnd);
    expect(toolbarSlice).toMatch(/Pay \{formatCurrency\(totals\?\.total_due/);
    // Mobile pay bar — same shape, no literal ``$``.
    expect(INVOICE_SRC).toMatch(/Pay \{formatCurrency\(totals\?\.total_due \|\| 0\)\}/);
    // And the old shape must be fully gone.
    expect(INVOICE_SRC).not.toMatch(/Pay \$\{fmtMoney/);
  });
});
