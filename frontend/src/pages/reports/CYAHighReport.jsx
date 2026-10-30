/**
 * Feb-2026 · CYA Over-Threshold Report (operator fix v2).
 *
 * Route: ``/reports/cya-high`` (AdminOnly-gated in App.js).
 * Endpoints: ``GET /api/reports/cya-high`` + ``/export.csv``.
 *
 * Admins see one row per historical Cyanuric Acid reading above
 * the threshold (default 100 ppm, strict ``>``). All reports
 * participate — including drafts and legacy rows without
 * ``submitted_at``. Customer name cell deep-links to the
 * customer detail page.
 *
 * Row shape (BE commit ``ed6538929``):
 *   { customer_id, customer_name, job_id, job_date, value }
 */
import React, { useCallback, useEffect, useState } from "react";
import { api } from "@/api";
import { toast } from "@/hooks/use-toast";
import { CustomerLink } from "@/components/customer";
import PageHeader from "@/components/layout/PageHeader";
import { Droplets, FileText } from "lucide-react";


function _shortDate(iso) {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleDateString(); } catch { return iso; }
}


function _csv(items) {
  const rows = [
    ["customer_id", "customer_name", "job_id", "job_date", "value"],
    ...(items || []).map((r) => [
      r.customer_id || "",
      r.customer_name || "",
      r.job_id || "",
      r.job_date || "",
      r.value ?? "",
    ]),
  ];
  return rows.map((r) => r.map((c) => {
    const s = String(c ?? "");
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  }).join(",")).join("\n");
}


function _download(name, text) {
  const blob = new Blob([text], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = name;
  document.body.appendChild(a); a.click(); document.body.removeChild(a);
  URL.revokeObjectURL(url);
}


export default function CYAHighReport() {
  const [threshold, setThreshold] = useState(100);
  const [dfrom, setDfrom] = useState("");
  const [dto, setDto] = useState("");
  const [state, setState] = useState({ loading: true });

  const load = useCallback(async () => {
    setState({ loading: true });
    try {
      const params = new URLSearchParams();
      params.set("threshold", String(threshold));
      if (dfrom) params.set("from", dfrom);
      if (dto) params.set("to", dto);
      const res = await api.get(
        `/reports/cya-high?${params.toString()}`,
      );
      setState({ loading: false, data: res });
    } catch (e) {
      const msg = e?.message || "Failed to load CYA report";
      setState({ loading: false, error: msg });
      try {
        toast({
          title: "CYA report failed",
          description: msg,
          variant: "destructive",
        });
      } catch { /* toast shim absent in some test envs */ }
    }
  }, [threshold, dfrom, dto]);

  useEffect(() => { load(); }, [load]);

  const d = state.data || {};
  const items = d.items || [];
  const isLoading = state.loading;
  const isError = !!state.error;

  const onExport = () => {
    _download("cya-high.csv", _csv(items));
  };

  return (
    <div
      className="p-4 md:p-8 max-w-7xl mx-auto"
      data-testid="cya-high-report"
    >
      <PageHeader
        title={
          <span data-testid="cya-high-title">
            <Droplets
              size={20}
              style={{ display: "inline", marginRight: 8,
                       verticalAlign: "-3px" }}
            />
            CYA Over Threshold
          </span>
        }
        subtitle={
          <span data-testid="cya-high-subtitle">
            One row per historical Cyanuric Acid reading above the
            threshold (default 100 ppm) across every service report.
          </span>
        }
      />

      {/* Filter row */}
      <div className="flex flex-wrap gap-3 items-end mt-4 mb-6">
        <label className="flex flex-col text-sm">
          <span className="mb-1 text-gray-600">Threshold (ppm)</span>
          <input
            type="number"
            min="1"
            step="1"
            value={threshold}
            onChange={(e) => setThreshold(
              Math.max(1, Number(e.target.value) || 1),
            )}
            className="border rounded px-3 py-1.5 w-32"
            data-testid="cya-threshold-input"
          />
        </label>
        <label className="flex flex-col text-sm">
          <span className="mb-1 text-gray-600">From</span>
          <input
            type="date"
            value={dfrom}
            onChange={(e) => setDfrom(e.target.value)}
            className="border rounded px-3 py-1.5"
            data-testid="cya-from-input"
          />
        </label>
        <label className="flex flex-col text-sm">
          <span className="mb-1 text-gray-600">To</span>
          <input
            type="date"
            value={dto}
            onChange={(e) => setDto(e.target.value)}
            className="border rounded px-3 py-1.5"
            data-testid="cya-to-input"
          />
        </label>
        <button
          type="button"
          onClick={onExport}
          disabled={!items.length}
          className="ml-auto inline-flex items-center gap-2 px-4 py-2
                     rounded bg-slate-800 text-white text-sm
                     disabled:opacity-40"
          data-testid="cya-export-csv-btn"
        >
          <FileText size={16} />
          Export CSV
        </button>
      </div>

      {/* States */}
      {isLoading && (
        <div data-testid="cya-high-loading" className="py-8 text-gray-500">
          Loading…
        </div>
      )}

      {isError && !isLoading && (
        <div
          data-testid="cya-high-error"
          className="py-8 text-red-700 bg-red-50 border border-red-200
                     rounded px-4"
        >
          {state.error}
        </div>
      )}

      {!isLoading && !isError && items.length === 0 && (
        <div
          data-testid="cya-high-empty"
          className="py-10 text-gray-500 text-center border border-dashed
                     rounded"
        >
          No readings above {threshold} ppm in the selected window.
        </div>
      )}

      {!isLoading && !isError && items.length > 0 && (
        <div className="overflow-x-auto border rounded">
          <table
            className="min-w-full text-sm"
            data-testid="cya-high-table"
          >
            <thead className="bg-slate-50 text-left">
              <tr>
                <th className="px-3 py-2">Customer</th>
                <th className="px-3 py-2">Job date</th>
                <th className="px-3 py-2 text-right">CYA reading (ppm)</th>
              </tr>
            </thead>
            <tbody>
              {items.map((r, idx) => (
                <tr
                  key={`${r.job_id || "no-job"}-${idx}`}
                  className="border-t hover:bg-slate-50"
                  data-testid={`cya-row-${r.job_id || "no-job"}-${idx}`}
                >
                  <td className="px-3 py-2">
                    <CustomerLink
                      customerId={r.customer_id}
                      name={r.customer_name}
                    />
                  </td>
                  <td className="px-3 py-2">{_shortDate(r.job_date)}</td>
                  <td className="px-3 py-2 text-right font-semibold">
                    {r.value}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
