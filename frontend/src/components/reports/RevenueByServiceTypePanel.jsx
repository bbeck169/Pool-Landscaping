import React from "react";
import { api } from "@/api";
import { colors } from "@/theme";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { HorizontalBarChart } from "./HorizontalBarChart";
import { LensToggle } from "./LensToggle";
import { downloadCsv } from "./downloadCsv";
import { downloadServerPdf } from "./downloadServerPdf";
import { formatCurrency } from "./formatters";

function buildQuery(f) {
  const p = new URLSearchParams();
  p.set("period", f.period || "mtd");
  if (f.period === "custom" && f.start && f.end) {
    p.set("start", f.start);
    p.set("end", f.end);
  }
  p.set("lens", f.lens || "invoiced");
  if (f.service_type) p.set("service_type", f.service_type);
  if (f.tech_id) p.set("tech_id", f.tech_id);
  return p.toString();
}

/**
 * Phase R1.b · Feb-2026 — Revenue by Service Type panel.
 *
 * Backend endpoint: ``/reports/kpi/revenue_by_service_type``.
 * Rows are shaped
 *   { service_category_id, service_category_name, revenue, invoice_count }
 *
 * Aquaterra invoices rarely populate ``service_category_id`` on
 * their line items, so an "Uncategorized" bucket usually holds
 * the bulk of the volume — this is expected R1.a behavior and
 * covered by ``TestRevenueByServiceType::test_uncategorized_bucket_when_field_missing``.
 */
export function RevenueByServiceTypePanel({ filters, onLensChange, testid = "rev-svc-panel" }) {
  const [state, setState] = React.useState({ loading: true });
  const qs = buildQuery(filters);

  const [pdfBusy, setPdfBusy] = React.useState(false);
  const downloadPdf = async () => {
    if (pdfBusy) return;
    setPdfBusy(true);
    try { await downloadServerPdf(
      `/reports/kpi/revenue_by_service_type/export.pdf?${qs}`,
      `revenue-by-service-type-${filters.period || "mtd"}-${filters.lens || "invoiced"}.pdf`,
    ); }
    catch (e) { toast.error(e?.message || "PDF download failed"); }
    finally { setPdfBusy(false); }
  };

  React.useEffect(() => {
    let live = true;
    setState({ loading: true });
    (async () => {
      try {
        const r = await api.get(`/reports/kpi/revenue_by_service_type?${qs}`);
        if (live) setState({ loading: false, data: r });
      } catch (e) {
        if (live) setState({ loading: false, error: e?.message || "Failed" });
      }
    })();
    return () => { live = false; };
  }, [qs]);

  const rows = state.data?.rows || [];
  const chartRows = rows.slice(0, 15).map((r) => ({
    label: r.service_category_name || "(untyped)",
    value: Number(r.revenue || 0),
    id: r.service_category_id || null,
  }));

  const exportCsv = () => {
    const body = rows.map((r) => [
      r.service_category_name || "",
      r.service_category_id || "",
      Number(r.revenue || 0).toFixed(2),
      Number(r.invoice_count || 0),
    ]);
    downloadCsv(
      `revenue-by-service-type-${filters.period || "mtd"}-${filters.lens || "invoiced"}.csv`,
      ["Service Category", "Category ID", "Revenue", "Invoices"],
      body,
    );
  };

  return (
    <section className="space-y-4" data-testid={testid}>
      <header className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h2 className="text-lg font-bold" style={{ color: colors.onSurface }}>
            Revenue by Service Type
          </h2>
          <p className="text-xs" style={{ color: colors.onSurfaceSecondary }}>
            {state.loading ? "Loading…" : state.error ? "Error" : (
              <>
                {formatCurrency(state.data?.total)} total ·{" "}
                {state.data?.row_count || 0} categor{state.data?.row_count === 1 ? "y" : "ies"}
              </>
            )}
          </p>
        </div>
        <div className="flex items-center gap-3">
          {onLensChange ? (
            <LensToggle
              value={filters.lens || "invoiced"}
              onChange={onLensChange}
            />
          ) : null}
          <Button
            variant="ghost"
            onClick={exportCsv}
            disabled={state.loading || rows.length === 0}
            data-testid={`${testid}-export`}
          >
            Export CSV
          </Button>
          <Button
            variant="ghost"
            onClick={downloadPdf}
            disabled={pdfBusy}
            data-testid={`${testid}-export-pdf`}
          >
            {pdfBusy ? "Preparing…" : "Download PDF"}
          </Button>
        </div>
      </header>

      <HorizontalBarChart
        data={chartRows}
        format="currency"
        height={Math.max(200, chartRows.length * 28)}
        testid={`${testid}-chart`}
      />

      <div
        className="rounded-xl border overflow-hidden"
        style={{ backgroundColor: colors.surface, borderColor: colors.border }}
      >
        <table className="w-full text-sm" data-testid={`${testid}-table`}>
          <thead style={{ backgroundColor: colors.surfaceSecondary }}>
            <tr>
              <th className="text-left px-3 py-2 font-semibold"
                  style={{ color: colors.onSurfaceSecondary }}>Category</th>
              <th className="text-right px-3 py-2 font-semibold"
                  style={{ color: colors.onSurfaceSecondary }}>Invoices</th>
              <th className="text-right px-3 py-2 font-semibold"
                  style={{ color: colors.onSurfaceSecondary }}>Revenue</th>
            </tr>
          </thead>
          <tbody>
            {state.loading ? (
              <tr><td colSpan={3} className="px-3 py-6 text-center text-xs"
                      style={{ color: colors.onSurfaceSecondary }}>Loading…</td></tr>
            ) : state.error ? (
              <tr><td colSpan={3} className="px-3 py-6 text-center text-xs"
                      style={{ color: colors.error }}>{state.error}</td></tr>
            ) : rows.length === 0 ? (
              <tr><td colSpan={3} className="px-3 py-6 text-center text-xs"
                      style={{ color: colors.onSurfaceSecondary }}
                      data-testid={`${testid}-empty`}>No revenue for this period</td></tr>
            ) : rows.map((r) => (
              <tr key={r.service_category_id || r.service_category_name}
                  style={{ borderTop: `1px solid ${colors.border}` }}
                  data-testid={`${testid}-row-${r.service_category_id || 'uncat'}`}>
                <td className="px-3 py-2" style={{ color: colors.onSurface }}>
                  {r.service_category_name || "(untyped)"}
                </td>
                <td className="text-right px-3 py-2"
                    style={{ color: colors.onSurfaceSecondary }}>
                  {r.invoice_count}
                </td>
                <td className="text-right px-3 py-2 font-semibold"
                    style={{ color: colors.onSurface }}>
                  {formatCurrency(r.revenue)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export default RevenueByServiceTypePanel;
