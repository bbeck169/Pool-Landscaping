/**
 * Feb-2026 · Universal mobile-responsive redesign · shared
 * totals-block card for customer-facing docs.
 *
 * Renders a total row with dashed divider above. When
 * ``totals.has_declined_lines === true`` we render TWO rows
 * (Original strike-through + Adjusted bold) so the customer can
 * see the impact of their per-line decline decisions.
 *
 * Testids
 * -------
 *   ${prefix}-totals-block             root container
 *   ${prefix}-totals-row-final         final total row
 *   ${prefix}-totals-row-{key}         any additional row
 *   ${prefix}-totals-adjusted-row      the two-row split when
 *                                       has_declined_lines=true
 *   ${prefix}-totals-adjusted-note     legacy annotation copy
 */
import React from "react";


function fmt(n) {
  const v = Number(n || 0);
  try {
    return v.toLocaleString("en-US", {
      style: "currency", currency: "USD",
    });
  } catch {
    return `$${v.toFixed(2)}`;
  }
}


export default function DocTotalsBlock({
  totals = {},
  rows = null,
  testidPrefix = "doc",
}) {
  const derived = rows || defaultRows(totals);
  const hasSplit = Boolean(totals.has_declined_lines
    && totals.adjusted_total != null);

  return (
    <div
      className="doc-totals-block"
      data-testid={`${testidPrefix}-totals-block`}
      style={{
        padding: "12px 16px 16px",
        fontSize: 15,
      }}
    >
      <div style={{
        borderTop: "1.5px dashed #94A3B8",
        marginBottom: 8,
      }} />
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <tbody>
          {derived.map((r, i) => (
            <tr key={r.key || i}
                data-highlight={r.highlight ? "true" : "false"}
                data-testid={`${testidPrefix}-totals-row-${r.key || i}`}>
              <td
                style={{
                  padding: "4px 0",
                  color: r.highlight ? "#0F172A" : "#6B7280",
                  fontWeight: r.highlight ? 800 : 500,
                  fontSize: r.highlight ? 18 : 14,
                }}
              >
                {r.label}
              </td>
              <td
                style={{
                  padding: "4px 0",
                  textAlign: "right",
                  fontWeight: 700,
                  color: "#0F172A",
                  fontSize: r.highlight ? 20 : 14,
                  fontVariantNumeric: "tabular-nums",
                }}
              >
                {r.value}
              </td>
            </tr>
          ))}
          {hasSplit ? (
            <tr data-testid={`${testidPrefix}-totals-adjusted-row`}>
              <td colSpan={2} style={{ padding: "8px 0 0" }}>
                <div style={{
                  display: "flex", justifyContent: "space-between",
                  alignItems: "baseline", gap: 12,
                }}>
                  <span style={{
                    color: "#6B7280", fontSize: 13,
                    textDecoration: "line-through",
                  }}>
                    Original Total:{" "}
                    <span
                      data-testid={`${testidPrefix}-totals-original`}
                      style={{ color: "#9CA3AF" }}
                    >
                      {fmt(totals.original_total ?? totals.total ??
                        totals.total_estimated_cost)}
                    </span>
                  </span>
                  <span style={{
                    color: "#0F172A", fontSize: 18, fontWeight: 800,
                    fontVariantNumeric: "tabular-nums",
                  }}>
                    Adjusted Total:{" "}
                    <span data-testid={`${testidPrefix}-totals-adjusted`}>
                      {fmt(totals.adjusted_total)}
                    </span>
                  </span>
                </div>
              </td>
            </tr>
          ) : null}
        </tbody>
      </table>
      {totals.has_declined_lines ? (
        <div
          data-testid={`${testidPrefix}-totals-adjusted-note`}
          style={{
            marginTop: 8, fontSize: 12,
            color: "#92400E", fontStyle: "italic",
          }}
        >
          Adjusted for {totals.declined_line_count || "declined"} declined
          line item{totals.declined_line_count === 1 ? "" : "s"}.
        </div>
      ) : null}
    </div>
  );
}


function defaultRows(t = {}) {
  const out = [];
  if (t.subtotal != null) {
    out.push({ key: "subtotal", label: "Subtotal", value: fmt(t.subtotal) });
  }
  if (t.taxes != null) {
    out.push({ key: "taxes", label: "Taxes", value: fmt(t.taxes) });
  }
  if (t.amount_paid != null && Number(t.amount_paid) > 0) {
    out.push({
      key: "amount-paid", label: "Amount paid", value: fmt(t.amount_paid),
    });
  }
  const finalLabel = t.balance_due != null ? "Balance due"
    : t.total_estimated_cost != null ? "Total (USD)"
    : "Total (USD)";
  const finalValue = fmt(
    t.balance_due ?? t.total_estimated_cost ?? t.total ?? 0,
  );
  out.push({
    key: "final", label: finalLabel, value: finalValue, highlight: true,
  });
  return out;
}
