/**
 * Feb-2026 · P37d — Dispatcher GPS Auto-Start audit dashboard.
 *
 * Consumes ``GET /api/reports/gps-auto-start-audit``. Ops uses this
 * to tune the 75m default radius and diagnose systematic problems
 * (consent gaps, throttling storms, geocode drift, etc).
 *
 * Layout:
 *   1. Summary tile row — 5 outcome counts + median / p90 distance +
 *      3 distance-bucket percents (excellent / acceptable / over).
 *   2. Filters row — date range + tech filter + refresh button.
 *   3. Recent events table — last 50 arrivals, newest first.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { RefreshCw, MapPin, AlertTriangle } from "lucide-react";
import { api } from "@/api";
import { PageHeader } from "@/components/ui-kit";
import { colors } from "@/theme";


const _OUTCOME_META = {
  started:          { label: "Started",          fg: "#166534", bg: "#DCFCE7" },
  throttled:        { label: "Throttled",        fg: "#78350F", bg: "#FEF3C7" },
  out_of_radius:    { label: "Out of radius",    fg: "#7F1D1D", bg: "#FEE2E2" },
  consent_required: { label: "Consent required", fg: "#1E293B", bg: "#E2E8F0" },
  feature_disabled: { label: "Feature disabled", fg: "#1E293B", bg: "#E2E8F0" },
  already_running:  { label: "Already running",  fg: "#1E293B", bg: "#E2E8F0" },
  job_completed:    { label: "Job completed",    fg: "#1E293B", bg: "#E2E8F0" },
};


function _isoDaysAgo(n) {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString();
}


function OutcomePill({ outcome, count }) {
  const meta = _OUTCOME_META[outcome] || _OUTCOME_META.already_running;
  return (
    <div
      className="px-3 py-2 rounded-lg"
      style={{ background: meta.bg, color: meta.fg,
                 border: `1px solid ${meta.fg}22` }}
      data-testid={`gps-audit-outcome-${outcome}`}
    >
      <div className="text-[10px] font-bold uppercase tracking-wider">
        {meta.label}
      </div>
      <div className="text-2xl font-bold">{count}</div>
    </div>
  );
}


function Stat({ label, value, testid }) {
  return (
    <div className="px-3 py-2 rounded-lg"
         style={{ background: colors.surfaceSecondary,
                    color: colors.onSurface,
                    border: `1px solid ${colors.border}` }}
         data-testid={testid}>
      <div className="text-[10px] font-bold uppercase tracking-wider"
           style={{ color: colors.onSurfaceSecondary }}>
        {label}
      </div>
      <div className="text-xl font-bold">{value}</div>
    </div>
  );
}


export default function GpsAutoStartAudit() {
  const [from, setFrom] = useState(() => _isoDaysAgo(30).slice(0, 10));
  const [to, setTo] = useState(() => new Date().toISOString().slice(0, 10));
  const [techId, setTechId] = useState("");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const qp = new URLSearchParams();
      qp.set("from", new Date(`${from}T00:00:00Z`).toISOString());
      qp.set("to", new Date(`${to}T23:59:59Z`).toISOString());
      if (techId) qp.set("tech_id", techId);
      const r = await api.get(`/reports/gps-auto-start-audit?${qp}`);
      setData(r);
    } catch (e) { setData(null); }
    finally { setLoading(false); }
  }, [from, to, techId]);

  useEffect(() => { load(); }, [load]);

  const s = data?.summary || {};
  const recent = data?.recent_events || [];

  return (
    <div style={{ background: colors.bg, minHeight: "100vh" }}>
      <PageHeader
        title="GPS Auto-Start Audit"
        subtitle={
          s.total_arrivals != null
            ? `${s.total_arrivals.toLocaleString()} arrivals in window`
            : ""
        }
        icon={MapPin}
      />
      <div className="p-4 space-y-4">
        {/* Filters */}
        <div className="flex flex-wrap items-end gap-3">
          <label className="text-xs" style={{ color: colors.onSurfaceSecondary }}>
            From
            <input type="date" value={from} onChange={(e) => setFrom(e.target.value)}
              className="ml-2 px-2 py-1 rounded border text-sm"
              style={{ borderColor: colors.border,
                         background: colors.surface, color: colors.onSurface }}
              data-testid="gps-audit-from" />
          </label>
          <label className="text-xs" style={{ color: colors.onSurfaceSecondary }}>
            To
            <input type="date" value={to} onChange={(e) => setTo(e.target.value)}
              className="ml-2 px-2 py-1 rounded border text-sm"
              style={{ borderColor: colors.border,
                         background: colors.surface, color: colors.onSurface }}
              data-testid="gps-audit-to" />
          </label>
          <label className="text-xs" style={{ color: colors.onSurfaceSecondary }}>
            Tech ID
            <input type="text" value={techId}
              placeholder="optional"
              onChange={(e) => setTechId(e.target.value)}
              className="ml-2 px-2 py-1 rounded border text-sm"
              style={{ borderColor: colors.border,
                         background: colors.surface, color: colors.onSurface }}
              data-testid="gps-audit-tech-id" />
          </label>
          <button type="button" onClick={load}
                    disabled={loading}
                    data-testid="gps-audit-refresh"
                    className="ml-auto inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded-full"
                    style={{ background: colors.brand, color: "#fff",
                               opacity: loading ? 0.6 : 1 }}>
            <RefreshCw size={13} /> Refresh
          </button>
        </div>

        {/* Summary tiles */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3"
             data-testid="gps-audit-summary">
          <OutcomePill outcome="started"          count={s.started || 0} />
          <OutcomePill outcome="throttled"        count={s.throttled || 0} />
          <OutcomePill outcome="out_of_radius"    count={s.out_of_radius || 0} />
          <OutcomePill outcome="consent_required" count={s.consent_required || 0} />
          <OutcomePill outcome="feature_disabled" count={s.feature_disabled || 0} />
        </div>

        {/* Distance stats */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          <Stat label="Median distance"
                  value={s.median_distance_m != null ? `${s.median_distance_m} m` : "—"}
                  testid="gps-audit-median-distance" />
          <Stat label="P90 distance"
                  value={s.p90_distance_m != null ? `${s.p90_distance_m} m` : "—"}
                  testid="gps-audit-p90-distance" />
          <Stat label="Excellent (<25m)"
                  value={`${s.percent_excellent || 0}%`}
                  testid="gps-audit-percent-excellent" />
          <Stat label={`Acceptable (25-${s.current_radius_m || 75}m)`}
                  value={`${s.percent_acceptable || 0}%`}
                  testid="gps-audit-percent-acceptable" />
          <Stat label="Over radius"
                  value={`${s.percent_over_radius || 0}%`}
                  testid="gps-audit-percent-over-radius" />
        </div>

        {/* Recent events */}
        <div className="rounded-lg overflow-hidden border"
             style={{ borderColor: colors.border,
                        background: colors.surface }}>
          <div className="px-3 py-2 border-b text-sm font-bold"
               style={{ borderColor: colors.border,
                          color: colors.onSurface,
                          background: colors.surfaceSecondary }}>
            Recent events (last 50)
          </div>
          {recent.length === 0 ? (
            <div className="px-3 py-6 text-center text-sm"
                 style={{ color: colors.onSurfaceSecondary }}
                 data-testid="gps-audit-recent-empty">
              No arrivals in the selected window.
            </div>
          ) : (
            <table className="w-full text-xs">
              <thead>
                <tr style={{ background: colors.surfaceSecondary,
                                color: colors.onSurfaceSecondary }}>
                  <th className="px-3 py-2 text-left">Arrived</th>
                  <th className="px-3 py-2 text-left">Tech</th>
                  <th className="px-3 py-2 text-left">Customer</th>
                  <th className="px-3 py-2 text-left">Outcome</th>
                  <th className="px-3 py-2 text-right">Distance</th>
                  <th className="px-3 py-2 text-right">Radius</th>
                </tr>
              </thead>
              <tbody>
                {recent.map((r, i) => {
                  const meta = _OUTCOME_META[r.outcome]
                                 || _OUTCOME_META.already_running;
                  return (
                    <tr key={i}
                        style={{ borderTop: `1px solid ${colors.divider}` }}
                        data-testid={`gps-audit-recent-row-${i}`}>
                      <td className="px-3 py-2"
                          style={{ color: colors.onSurface }}>
                        {r.arrived_at}
                      </td>
                      <td className="px-3 py-2"
                          style={{ color: colors.onSurface }}>
                        {r.tech_name || "—"}
                      </td>
                      <td className="px-3 py-2"
                          style={{ color: colors.onSurface }}>
                        {r.customer_name || "—"}
                      </td>
                      <td className="px-3 py-2">
                        <span
                          className="inline-block px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider"
                          style={{ background: meta.bg, color: meta.fg }}
                        >
                          {meta.label}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-right"
                          style={{ color: colors.onSurface }}>
                        {r.distance_m != null ? `${r.distance_m} m` : "—"}
                      </td>
                      <td className="px-3 py-2 text-right"
                          style={{ color: colors.onSurfaceSecondary }}>
                        {r.radius_m != null ? `${r.radius_m} m` : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}
