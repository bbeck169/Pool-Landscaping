/**
 * TD-admin-dashboard-outstanding-invoices-tile · Feb-2026
 *
 * All-time Outstanding Invoices tile mounted at the top of the
 * Revenue Insights section on the Admin Dashboard.
 *
 * Data source: ``GET /api/payments/summary``.  The canonical AR
 * aggregate — filters ``doc_type == "invoice"``, excludes deleted
 * and voided/draft, and uses ``balance = total - amount_paid``
 * so partially-paid invoices surface the real residual.  The
 * same endpoint feeds ``PaymentsWidget`` (lower on the dashboard)
 * and ``InvoicesList`` — all three surfaces agree.
 *
 * The owning ``Dashboard.jsx`` lifts the summary fetch to the
 * page level so the ``RevenueChart`` outstanding badge and this
 * tile read from one shared payload, preventing the day-one
 * divergence described in the TD audit report.
 *
 * Prop contract:
 *   * ``summary``  — the ``/payments/summary`` payload, or
 *                    ``null`` when still loading, or ``undefined``
 *                    when the fetch failed.
 *   * ``onClick``  — fired on tile click, used by the owning page
 *                    to deep-link into
 *                    ``/quotes?payment_status=unpaid``.
 *
 * Styling mirrors ``KpiCard`` (amber tone — matches
 * ``PaymentsWidget``'s Outstanding tile at Dashboard.jsx:376-387).
 */
import React from "react";
import { AlertCircle } from "lucide-react";

import { colors, money } from "@/theme";
import { getAccentTone } from "@/utils/serviceLineTheme";


export function OutstandingInvoicesTile({ summary, onClick }) {
  const palette = getAccentTone("amber");
  const isLoading = summary === null;
  const isError = summary === undefined;

  const total = Number(summary?.outstanding_total || 0);
  const count = Number(summary?.outstanding_count || 0);

  const valueDisplay = isLoading
    ? "—"
    : isError
      ? "—"
      : money(total);
  const sublabelDisplay = isLoading
    ? "loading…"
    : isError
      ? "unavailable"
      : `${count} invoice${count === 1 ? "" : "s"} · all time`;

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={isLoading || isError}
      className="text-left rounded-2xl p-5 transition hover:brightness-95 active:scale-[0.99] w-full"
      style={{
        backgroundColor: palette[50],
        border: `1px solid ${colors.border}`,
        borderLeft: `4px solid ${palette[500]}`,
        opacity: isLoading || isError ? 0.75 : 1,
      }}
      data-testid="tile-outstanding-invoices"
      data-tone="amber"
      data-loading={isLoading ? "true" : "false"}
      data-error={isError ? "true" : "false"}
    >
      <div
        className="w-10 h-10 rounded-xl flex items-center justify-center mb-3"
        style={{
          backgroundColor: colors.tile.solidNavy,
          color: "#FFFFFF",
        }}
        data-testid="k74-kpi-identity-chip"
        data-tile-key="tile-outstanding-invoices"
        data-k74-solid-navy-chip="true"
      >
        <AlertCircle size={20} />
      </div>
      <div
        className="text-2xl font-bold"
        style={{ color: colors.onSurface }}
        data-testid="tile-outstanding-invoices-value"
      >
        {valueDisplay}
      </div>
      <div
        className="text-[11px] mt-0.5"
        style={{
          color: colors.onSurfaceMuted || "#64748B",
          opacity: 0.75,
        }}
        data-testid="tile-outstanding-invoices-sublabel"
      >
        {sublabelDisplay}
      </div>
      <div
        className="text-xs mt-1 font-semibold uppercase tracking-wide"
        style={{ color: palette[700] }}
      >
        Outstanding Invoices
      </div>
    </button>
  );
}


export default OutstandingInvoicesTile;
