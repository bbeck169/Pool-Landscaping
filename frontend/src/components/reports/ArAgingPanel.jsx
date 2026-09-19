import React from "react";
import { api } from "@/api";
import { colors } from "@/theme";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { HorizontalBarChart } from "./HorizontalBarChart";
import { downloadCsv } from "./downloadCsv";
import { downloadServerPdf } from "./downloadServerPdf";
import { formatCurrency } from "./formatters";
import { CustomerLink } from "@/components/customer";

function buildQuery(f) {
  const p = new URLSearchParams();
  p.set("period", f.period || "mtd");
  if (f.period === "custom" && f.start && f.end) {
    p.set("start", f.start);
    p.set("end", f.end);
  }
  if (f.service_type) p.set("service_type", f.service_type);
  if (f.tech_id) p.set("tech_id", f.tech_id);
  return p.toString();
}

const BUCKET_ORDER = ["0-30", "31-60", "61-90", "90+"];

/**
 * Phase R1.b · Feb-2026 — AR Aging panel.
 *
 * Two views stacked:
 *   * Bucket bar chart (``ar_aging.rows`` — always 4 buckets).
 *   * Per-customer drill-down table (``ar_aging_by_customer``)
 *     with a "See invoices" link that scrolls the Unpaid Invoices
 *     panel below and pre-filters it to the customer.
 *
 * ``onCustomerFocus(customerId)`` — invoked when a row's action
 * button is clicked. Parent (Financial tab) implements it by
 * pushing ``?customer_id=<id>`` into the URL, which the Unpaid
 * Invoices panel reads to scope its own fetch.
 */
export function ArAgingPanel({ filters, onCustomerFocus, testid = "ar-aging-panel" }) {
  const [bucket, setBucket] = React.useState({ loading: true });
  const [byCust, setByCust] = React.useState({ loading: true });
  const qs = buildQuery(filters);

  const [pdfBusy, setPdfBusy] = React.useState(false);
  const downloadPdf = async () => {
    if (pdfBusy) return;
    setPdfBusy(true);
    try { await downloadServerPdf(
      `/reports/kpi/ar_aging_by_customer/export.pdf?${qs}&limit=100`,
      `ar-aging-${filters.period || "mtd"}.pdf`,
    ); }
    catch (e) { toast.error(e?.message || "PDF download failed"); }
    finally { setPdfBusy(false); }
  };

  React.useEffect(() => {
    let live = true;
    setBucket({ loading: true });
    setByCust({ loading: true });
    (async () => {
      const [b, c] = await Promise.all([
        api.get(`/reports/kpi/ar_aging?${qs}`).catch((e) => ({ __err: e?.message })),
        api.get(`/reports/kpi/ar_aging_by_customer?${qs}&limit=100`).catch((e) => ({ __err: e?.message })),
      ]);
      if (!live) return;
      setBucket({ loading: false, ...(b || {}) });
      setByCust({ loading: false, ...(c || {}) });
    })();
    return () => { live = false; };
  }, [qs]);

  const chartRows = React.useMemo(() => {
    const rows = bucket.rows || [];
    const map = Object.fromEntries(rows.map((r) => [r.bucket, r]));
    return BUCKET_ORDER.map((k) => ({
      label: `${k} days`,
      value: Number(map[k]?.amount || 0),
      id: k,
    }));
  }, [bucket.rows]);

  const exportBucketsCsv = () => {
    const body = BUCKET_ORDER.map((k) => {
      const r = (bucket.rows || []).find((x) => x.bucket === k) || {};
      return [k, Number(r.amount || 0).toFixed(2), Number(r.invoice_count || 0)];
    });
    downloadCsv(
      `ar-aging-${filters.period || "mtd"}.csv`,
      ["Bucket", "Amount", "Invoice Count"],
      body,
    );
  };

  const custRows = byCust.rows || [];

  return (
    <section className="space-y-4" data-testid={testid}>
      <header className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h2 className="text-lg font-bold" style={{ color: colors.onSurface }}>
            AR Aging
          </h2>
          <p className="text-xs" style={{ color: colors.onSurfaceSecondary }}>
            {bucket.loading ? "Loading…" : bucket.__err ? "Error" : (
              <>
                {formatCurrency(bucket.total)} outstanding
                {typeof bucket.net_terms_days === "number"
                  ? ` · Net ${bucket.net_terms_days}` : ""}
              </>
            )}
          </p>
        </div>
        <Button
          variant="ghost"
          onClick={exportBucketsCsv}
          disabled={bucket.loading || !bucket.rows?.length}
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
      </header>

      <HorizontalBarChart
        data={chartRows}
        format="currency"
        height={200}
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
                  style={{ color: colors.onSurfaceSecondary }}>Customer</th>
              <th className="text-right px-3 py-2 font-semibold"
                  style={{ color: colors.onSurfaceSecondary }}>Invoices</th>
              <th className="text-right px-3 py-2 font-semibold"
                  style={{ color: colors.onSurfaceSecondary }}>Oldest (days)</th>
              <th className="text-right px-3 py-2 font-semibold"
                  style={{ color: colors.onSurfaceSecondary }}>Outstanding</th>
              <th className="text-right px-3 py-2 font-semibold"
                  style={{ color: colors.onSurfaceSecondary }}></th>
            </tr>
          </thead>
          <tbody>
            {byCust.loading ? (
              <tr><td colSpan={5} className="px-3 py-6 text-center text-xs"
                      style={{ color: colors.onSurfaceSecondary }}>Loading…</td></tr>
            ) : byCust.__err ? (
              <tr><td colSpan={5} className="px-3 py-6 text-center text-xs"
                      style={{ color: colors.error }}>{byCust.__err}</td></tr>
            ) : custRows.length === 0 ? (
              <tr><td colSpan={5} className="px-3 py-6 text-center text-xs"
                      style={{ color: colors.onSurfaceSecondary }}
                      data-testid={`${testid}-empty`}>No outstanding balances</td></tr>
            ) : custRows.slice(0, 25).map((r) => (
              <tr key={r.customer_id || r.customer_name}
                  style={{ borderTop: `1px solid ${colors.border}` }}
                  data-testid={`${testid}-row-${r.customer_id || "unknown"}`}>
                <td className="px-3 py-2" style={{ color: colors.onSurface }}>
                  <CustomerLink customerId={r.customer_id} name={r.customer_name || "(unnamed)"} />
                </td>
                <td className="text-right px-3 py-2"
                    style={{ color: colors.onSurfaceSecondary }}>
                  {r.invoice_count}
                </td>
                <td className="text-right px-3 py-2"
                    style={{ color: colors.onSurfaceSecondary }}>
                  {r.oldest_days_overdue}
                </td>
                <td className="text-right px-3 py-2 font-semibold"
                    style={{ color: colors.onSurface }}>
                  {formatCurrency(r.total_outstanding)}
                </td>
                <td className="text-right px-3 py-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => r.customer_id && onCustomerFocus && onCustomerFocus(r.customer_id)}
                    disabled={!r.customer_id}
                    data-testid={`${testid}-drill-${r.customer_id || "unknown"}`}
                  >
                    See invoices
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export default ArAgingPanel;
