/**
 * Phase 47.3 — Job Costing panel.
 * Reads GET /jobs/{id}/costing and renders progress bars per bucket.
 * Embedded inside JobDetail as a collapsible section.
 */
import React, { useEffect, useState } from "react";
import { RefreshCw, DollarSign } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";

function money(cents) {
  const v = (cents || 0) / 100;
  return v.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 0 });
}

function toneForPct(pct) {
  if (pct > 100) return { bar: "#DC2626", label: "over" };
  if (pct >= 80) return { bar: "#F59E0B", label: "warn" };
  return { bar: "#16A34A", label: "ok" };
}

export default function JobCostingPanel({ jobId }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState(null);

  const load = async () => {
    if (!jobId) return;
    setLoading(true); setErr(null);
    try {
      const res = await api.get(`/jobs/${jobId}/costing`);
      setData(res);
    } catch (e) { setErr(e.message); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); /* eslint-disable-line */ }, [jobId]);

  if (loading && !data) return (
    <div className="text-xs px-3 py-2 rounded-md" style={{ color: colors.muted }}
         data-testid="job-costing-loading">Loading costing…</div>
  );
  if (err) return (
    <div className="rounded-md p-3 text-sm"
         style={{ background: "#FEF2F2", border: "1px solid #FECACA", color: "#B91C1C" }}
         data-testid="job-costing-error">{err}</div>
  );
  if (!data) return null;

  const rows = [
    { label: "Labor",     baseline: data.baseline.labor_cents,     actual: data.actual.labor_cents,     pct: data.progress.labor_pct },
    { label: "Materials", baseline: data.baseline.materials_cents, actual: data.actual.materials_cents, pct: data.progress.materials_pct },
    { label: "Equipment", baseline: data.baseline.equipment_cents, actual: data.actual.equipment_cents, pct: data.progress.equipment_pct },
  ];
  const marginTone = (data.actual_margin_pct >= data.estimated_margin_pct) ? "#16A34A" : "#DC2626";

  return (
    <div className="rounded-2xl p-4 mt-4"
         style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
         data-testid="job-costing-panel">
      <div className="flex items-center gap-2 mb-3">
        <DollarSign size={16} color={colors.brand} />
        <div className="text-sm font-bold" style={{ color: colors.onSurface }}>Job Costing</div>
        <div className="text-xs" style={{ color: colors.muted }}>
          · {data.time_entries_count} time entries · {Math.round(data.total_labor_minutes / 60 * 10) / 10}h
        </div>
        <div style={{ flex: 1 }} />
        <button onClick={load} className="text-xs font-semibold inline-flex items-center gap-1 px-2 py-1 rounded-md"
                style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
                data-testid="job-costing-refresh">
          <RefreshCw size={12} /> Refresh
        </button>
      </div>

      <div className="space-y-3 mb-4">
        {rows.map((r) => {
          const tone = toneForPct(r.pct);
          const pctCapped = Math.min(150, r.pct);
          return (
            <div key={r.label} data-testid={`job-costing-row-${r.label.toLowerCase()}`}>
              <div className="flex justify-between text-xs mb-1">
                <span className="font-semibold" style={{ color: colors.onSurface }}>{r.label}</span>
                <span style={{ color: colors.muted }}>
                  {money(r.actual)} / {money(r.baseline)} · <b style={{ color: tone.bar }}>{r.pct}%</b>
                </span>
              </div>
              <div className="h-2 rounded-full overflow-hidden" style={{ background: colors.surfaceSecondary }}>
                <div className="h-full transition-all"
                     style={{ width: `${pctCapped}%`, background: tone.bar }} />
              </div>
            </div>
          );
        })}
      </div>

      <div className="grid grid-cols-2 gap-3 pt-3" style={{ borderTop: `1px solid ${colors.border}` }}>
        <div data-testid="job-costing-estimated-profit">
          <div className="text-xs uppercase font-semibold" style={{ color: colors.muted }}>Estimated net profit</div>
          <div className="text-lg font-bold" style={{ color: colors.onSurface }}>
            {money(data.estimated_net_profit_cents)}
          </div>
          <div className="text-xs" style={{ color: colors.muted }}>{data.estimated_margin_pct}% margin</div>
        </div>
        <div data-testid="job-costing-actual-profit">
          <div className="text-xs uppercase font-semibold" style={{ color: colors.muted }}>Actual net profit</div>
          <div className="text-lg font-bold" style={{ color: marginTone }}>
            {money(data.actual_net_profit_cents)}
          </div>
          <div className="text-xs" style={{ color: colors.muted }}>{data.actual_margin_pct}% margin</div>
        </div>
      </div>
    </div>
  );
}
