/**
 * Phase K79 · Feb-2026 — Customer-view preview modal.
 *
 * Renders exactly what the customer will see on the shared estimate
 * link / portal / email: line items rolled up into groups by
 * ``service_category_id``, with the doc-level tax/discount/total
 * footer preserved.
 *
 * Client-side aggregation using the same rules as the backend helper
 * (services/quotes/customer_view.py). See:
 *   * First-appearance order for groups.
 *   * Empty ``service_category_id`` bucket into "Other" at the tail.
 *   * long_description is INTERNAL only — never in this modal.
 *
 * Uses the descriptions passed in by the parent — matches the pending
 * (unsaved-but-typed) state so preview reflects the admin's WIP.
 */
import React from "react";
import { X } from "lucide-react";
import { colors, money } from "@/theme";


function _groupLines(lines, cats, descriptions) {
  const buckets = new Map();
  for (const li of lines || []) {
    const raw = li?.service_category_id;
    const key = typeof raw === "string" && raw.trim() ? raw : "__other__";
    const qty = Number(li?.quantity || 0);
    const unit = Number(li?.unit_price || 0);
    const subtotal = qty * unit;
    if (!buckets.has(key)) {
      const label = key === "__other__"
        ? "Other"
        : ((cats || []).find((c) => c.id === key)?.name || key);
      const description = key === "__other__"
        ? ""
        : (descriptions?.[key] || "").trim();
      buckets.set(key, {
        id: key === "__other__" ? null : key,
        label,
        description,
        subtotal: 0,
      });
    }
    buckets.get(key).subtotal += subtotal;
  }
  const rows = [];
  let other = null;
  for (const [key, row] of buckets.entries()) {
    row.subtotal = Math.round(row.subtotal * 100) / 100;
    if (key === "__other__") other = row;
    else rows.push(row);
  }
  if (other) rows.push(other);
  return rows;
}


export default function K79CustomerViewPreview({
  doc, serviceCategories, descriptions, onClose,
}) {
  const groups = _groupLines(
    doc?.line_items || [], serviceCategories, descriptions,
  );
  const groupedSum = groups.reduce((s, g) => s + g.subtotal, 0);
  const subtotal = Number(doc?.subtotal || groupedSum);
  const tax = Number(doc?.tax || 0);
  const total = Number(doc?.total || (subtotal + tax));
  const enabled = doc?.customer_group_display !== false;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: "rgba(15, 23, 42, 0.55)" }}
      data-testid="k79-preview-modal"
      onClick={(e) => { if (e.target === e.currentTarget) onClose?.(); }}
    >
      <div
        className="w-full max-w-2xl rounded-2xl overflow-hidden"
        style={{ background: colors.surface,
                  border: `1px solid ${colors.border}` }}
      >
        <div
          className="flex items-center justify-between px-5 py-3"
          style={{ background: colors.surfaceSecondary,
                    borderBottom: `1px solid ${colors.divider}` }}
        >
          <div className="flex items-center gap-3">
            <div>
              <div className="text-sm font-bold"
                    style={{ color: colors.onSurface }}>
                Customer view preview
              </div>
              <div className="text-xs" style={{ color: colors.muted }}>
                This is what the customer sees on the shared link,
                portal, and PDF.
              </div>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1 rounded hover:bg-black/5"
            style={{ color: colors.muted }}
            data-testid="k79-preview-close"
          >
            <X size={16} />
          </button>
        </div>

        <div className="p-5">
          <div
            className="text-xs uppercase font-bold mb-2"
            style={{ color: colors.muted }}
            data-testid="k79-preview-mode-label"
          >
            {enabled ? "Grouped layout (on)" : "Itemized fallback (off)"}
          </div>

          {enabled ? (
            <table className="w-full text-sm"
                    data-testid="k79-preview-grouped-table">
              <thead>
                <tr style={{ borderBottom: `1px solid ${colors.divider}` }}>
                  <th className="text-left px-2 py-2 font-semibold"
                      style={{ color: colors.onSurfaceSecondary }}>
                    Service
                  </th>
                  <th className="text-right px-2 py-2 font-semibold w-32"
                      style={{ color: colors.onSurfaceSecondary }}>
                    Subtotal
                  </th>
                </tr>
              </thead>
              <tbody>
                {groups.length === 0 ? (
                  <tr>
                    <td colSpan={2} className="px-2 py-4 text-center"
                        style={{ color: colors.muted }}
                        data-testid="k79-preview-empty">
                      No line items to preview.
                    </td>
                  </tr>
                ) : groups.map((g, i) => (
                  <tr
                    key={g.id || `other-${i}`}
                    data-testid={
                      `k79-preview-group-${g.id || "other"}`
                    }
                    style={{
                      borderBottom: `1px solid ${colors.divider}`,
                    }}
                  >
                    <td className="px-2 py-3">
                      <div className="font-semibold"
                            style={{ color: colors.onSurface }}>
                        {g.label}
                      </div>
                      {g.description ? (
                        <div className="text-xs mt-1"
                              style={{ color: colors.muted }}
                              data-testid={
                                `k79-preview-desc-${g.id || "other"}`
                              }>
                          {g.description}
                        </div>
                      ) : null}
                    </td>
                    <td className="px-2 py-3 text-right font-semibold"
                        style={{ color: colors.onSurface }}>
                      {money(g.subtotal)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <table className="w-full text-sm"
                    data-testid="k79-preview-itemized-table">
              <thead>
                <tr style={{ borderBottom: `1px solid ${colors.divider}` }}>
                  <th className="text-left px-2 py-2 font-semibold"
                      style={{ color: colors.onSurfaceSecondary }}>
                    Item
                  </th>
                  <th className="text-right px-2 py-2 font-semibold"
                      style={{ color: colors.onSurfaceSecondary }}>
                    Qty
                  </th>
                  <th className="text-right px-2 py-2 font-semibold"
                      style={{ color: colors.onSurfaceSecondary }}>
                    Unit
                  </th>
                  <th className="text-right px-2 py-2 font-semibold w-24"
                      style={{ color: colors.onSurfaceSecondary }}>
                    Total
                  </th>
                </tr>
              </thead>
              <tbody>
                {(doc?.line_items || []).map((li, i) => (
                  <tr key={i}
                      style={{
                        borderBottom: `1px solid ${colors.divider}`,
                      }}>
                    <td className="px-2 py-2 font-semibold"
                        style={{ color: colors.onSurface }}>
                      {li.description}
                    </td>
                    <td className="px-2 py-2 text-right"
                        style={{ color: colors.onSurfaceSecondary }}>
                      {li.quantity || 0}
                    </td>
                    <td className="px-2 py-2 text-right"
                        style={{ color: colors.onSurfaceSecondary }}>
                      {money(li.unit_price || 0)}
                    </td>
                    <td className="px-2 py-2 text-right font-semibold"
                        style={{ color: colors.onSurface }}>
                      {money(
                        Number(li.quantity || 0)
                        * Number(li.unit_price || 0)
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <div className="mt-4 flex justify-end">
            <div className="w-64 space-y-1 text-sm">
              <div className="flex justify-between">
                <span style={{ color: colors.muted }}>Subtotal</span>
                <span data-testid="k79-preview-subtotal">
                  {money(subtotal)}
                </span>
              </div>
              <div className="flex justify-between">
                <span style={{ color: colors.muted }}>
                  Tax ({doc?.tax_rate ?? 0}%)
                </span>
                <span>{money(tax)}</span>
              </div>
              <div className="flex justify-between font-bold"
                    style={{ color: colors.brand }}>
                <span>Total</span>
                <span data-testid="k79-preview-total">{money(total)}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
