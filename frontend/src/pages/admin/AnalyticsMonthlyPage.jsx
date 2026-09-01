/**
 * Phase H6 · Feb-2026 — Monthly Analytics Dashboard.
 *
 * Single admin page that surfaces four monthly rollups:
 *   1. Soshie Moderation cost + decisions + cache-hit rate
 *   2. Charge-template usage + revenue contribution
 *   3. Drift alerts (dispatches + worst day)
 *   4. Manual-post conversion rate per platform (H5.5 bonus)
 *
 * Not real-time (per H6 non-goal). Refetches on month change.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Shield, TrendingUp, Zap, Send, RefreshCw } from "lucide-react";

import { api } from "@/api";
import { colors } from "@/theme";

function _fmtUsd(n) {
  const v = Number(n || 0);
  return v.toLocaleString(undefined, {
    style: "currency", currency: "USD",
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  });
}

function _fmtPct(n) {
  const v = Number(n || 0);
  return `${(v * 100).toFixed(1)}%`;
}

function _monthOptions() {
  const out = [];
  const now = new Date();
  for (let i = 0; i < 12; i++) {
    const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const label = d.toLocaleString(undefined,
                                       { month: "long", year: "numeric" });
    out.push({ value: `${y}-${m}`, label });
  }
  return out;
}


function Card({ title, testid, icon: Icon, children }) {
  return (
    <section
      className="rounded-2xl p-4"
      style={{
        background: colors.surface,
        border: `1px solid ${colors.border}`,
      }}
      data-testid={testid}
    >
      <header className="flex items-center gap-2 mb-3">
        {Icon ? <Icon size={16} style={{ color: colors.brand }} /> : null}
        <h3 className="text-sm font-bold"
             style={{ color: colors.onSurface }}>
          {title}
        </h3>
      </header>
      {children}
    </section>
  );
}


function Stat({ label, value, testid, tone }) {
  const fg =
    tone === "danger" ? colors.error :
    tone === "warn" ? "#B45309" :
    tone === "ok" ? colors.success :
                    colors.onSurface;
  return (
    <div data-testid={testid}>
      <div className="text-[10px] font-bold uppercase tracking-wider"
           style={{ color: colors.muted }}>
        {label}
      </div>
      <div className="text-xl font-bold mt-0.5"
           style={{ color: fg }}>
        {value}
      </div>
    </div>
  );
}


function CardSkeleton() {
  return (
    <div className="rounded-2xl p-4 animate-pulse"
         style={{ background: colors.surface,
                    border: `1px solid ${colors.border}`,
                    minHeight: 220 }}
         data-testid="analytics-card-skeleton">
      <div className="h-4 w-40 rounded"
           style={{ background: colors.surfaceSecondary }} />
      <div className="mt-4 h-6 w-24 rounded"
           style={{ background: colors.surfaceSecondary }} />
      <div className="mt-2 h-6 w-32 rounded"
           style={{ background: colors.surfaceSecondary }} />
    </div>
  );
}


function EmptyCell({ msg = "No activity in this window", testid }) {
  return (
    <div className="text-xs mt-2"
         style={{ color: colors.muted }}
         data-testid={testid}>
      {msg}
    </div>
  );
}


function SoshieCard({ data }) {
  const d = data || {};
  const dec = d.decisions || { approve: 0, flag: 0, block: 0 };
  const total = d.calls_total || 0;
  return (
    <Card title="Soshie Moderation"
             testid="analytics-card-soshie"
             icon={Shield}>
      <div className="grid grid-cols-2 gap-4">
        <Stat label="Calls" value={total}
                 testid="soshie-calls-total" />
        <Stat label="Est. Cost" value={_fmtUsd(d.cost_estimate_usd)}
                 testid="soshie-cost-total" tone={total ? "warn" : undefined} />
      </div>
      {total > 0 ? (
        <div className="mt-4 space-y-1"
              data-testid="soshie-decisions-bar">
          {[["approve", "ok"], ["flag", "warn"], ["block", "danger"]]
            .map(([k, tone]) => {
              const v = dec[k] || 0;
              const pct = total ? Math.round((v / total) * 100) : 0;
              const bg = tone === "ok" ? colors.success
                          : tone === "warn" ? "#F59E0B"
                          : colors.error;
              return (
                <div key={k}
                        className="flex items-center gap-2"
                        data-testid={`soshie-decision-${k}`}>
                  <span className="text-xs w-14 capitalize"
                          style={{ color: colors.muted }}>
                    {k}
                  </span>
                  <div className="flex-1 h-2 rounded-full overflow-hidden"
                          style={{ background: colors.surfaceSecondary }}>
                    <div style={{
                      background: bg, width: `${pct}%`, height: "100%",
                    }} />
                  </div>
                  <span className="text-xs w-10 text-right tabular-nums"
                          style={{ color: colors.onSurface }}>
                    {v}
                  </span>
                </div>
              );
            })}
          <div className="mt-2 inline-flex items-center gap-1 text-[10px] font-bold uppercase tracking-wider px-2 py-1 rounded-full"
                style={{ background: colors.surfaceSecondary,
                           color: colors.onSurfaceSecondary }}
                data-testid="soshie-cache-pill">
            Cache hit rate {_fmtPct(d.cache_hit_rate)}
          </div>
          {/* Phase I2 · Feb-2026 — Top blocked phrases (H7 audit
              → I2 coaching signal). Empty state matches the H6
              pattern used across the page. */}
          <div className="mt-4"
                  data-testid="soshie-blocked-phrases">
            <div className="text-[10px] font-bold uppercase tracking-wider mb-1"
                    style={{ color: colors.muted }}>
              Top blocked phrases this month
            </div>
            {(d.top_blocked_phrases || []).length ? (
              <div>
                {(d.top_blocked_phrases || []).map((p) => (
                  <div key={p.phrase}
                          className="flex items-center justify-between text-xs py-1 border-t"
                          style={{ borderColor: colors.border,
                                      color: colors.onSurface }}
                          data-testid={`soshie-blocked-phrase-${p.phrase.replace(/\s+/g, "-")}`}>
                    <span className="truncate flex-1">{p.phrase}</span>
                    <span className="tabular-nums font-semibold ml-2">
                      {p.count}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-xs mt-1"
                      style={{ color: colors.muted }}
                      data-testid="soshie-blocked-phrases-empty">
                No blocked phrases this month.
              </div>
            )}
          </div>
        </div>
      ) : (
        <EmptyCell testid="soshie-empty" />
      )}
    </Card>
  );
}


function ChargeTemplatesCard({ data }) {
  const d = data || {};
  const top = d.top_templates || [];
  const unused = d.unused_templates || [];
  return (
    <Card title="Charge Templates"
             testid="analytics-card-templates"
             icon={Zap}>
      <div className="grid grid-cols-2 gap-4">
        <Stat label="Applies (month)"
                 value={d.total_applies || 0}
                 testid="templates-applies-total" />
        <Stat label="Templates on file"
                 value={d.total_templates || 0}
                 testid="templates-count-total" />
      </div>
      {top.length ? (
        <div className="mt-3"
                data-testid="templates-top-list">
          <div className="text-[10px] font-bold uppercase tracking-wider mb-1"
                style={{ color: colors.muted }}>
            Top 3 (by revenue)
          </div>
          {top.map((t) => {
            const cur = Number(t.revenue_contribution_usd || 0);
            const prior = Number(t.prior_year_revenue_usd || 0);
            const dropPct = (cur > 0 && prior > 0 && cur < prior)
              ? Math.round(((prior - cur) / prior) * 100) : 0;
            const showYoy = dropPct > 20;
            return (
            <div key={t.template_id}
                    className="flex items-center justify-between text-sm py-1 border-t"
                    style={{ borderColor: colors.border,
                                color: colors.onSurface }}
                    data-testid={`templates-top-${t.template_id}`}>
              <span className="truncate flex-1 flex items-center gap-2">
                {t.name}
                {showYoy ? (
                  <span className="text-[9px] font-bold px-1.5 py-0.5 rounded-full"
                           style={{ background: "#FEE2E2",
                                       color: "#991B1B" }}
                           data-testid={`templates-yoy-${t.template_id}`}>
                    ↓ {dropPct}% YoY
                  </span>
                ) : null}
              </span>
              <span className="tabular-nums text-xs"
                       style={{ color: colors.muted }}>
                {t.apply_count}×
              </span>
              <span className="tabular-nums font-semibold ml-3">
                {_fmtUsd(t.revenue_contribution_usd)}
              </span>
            </div>
            );
          })}
        </div>
      ) : (
        <EmptyCell msg="No templates applied this month"
                       testid="templates-empty" />
      )}
      {unused.length ? (
        <div className="mt-3 text-xs" style={{ color: colors.muted }}
              data-testid="templates-unused">
          {unused.length} unused template(s) — oldest sitting for
          {" "}{unused[0]?.days_since_created ?? 0} days.
        </div>
      ) : null}
    </Card>
  );
}


function DriftCard({ data }) {
  const d = data || {};
  const drifted = (d.days_with_drift || 0) > 0;
  return (
    <Card title="Drift Alerts"
             testid="analytics-card-drift"
             icon={TrendingUp}>
      <div className="grid grid-cols-2 gap-4">
        <Stat label="Dispatches"
                 value={d.dispatches_total || 0}
                 testid="drift-dispatches" />
        <Stat label="Clean days"
                 value={d.clean_heartbeats || 0}
                 tone="ok"
                 testid="drift-clean" />
      </div>
      <div className="mt-3 text-xs" style={{ color: colors.muted }}>
        Dispatch success rate:{" "}
        <span className="font-semibold"
                 style={{ color: colors.onSurface }}
                 data-testid="drift-success-rate">
          {_fmtPct(d.dispatch_success_rate)}
        </span>
      </div>
      {drifted ? (
        <div className="mt-3 inline-flex items-center gap-1 text-[10px] font-bold uppercase tracking-wider px-2 py-1 rounded-full"
              style={{ background: "#FEE2E2", color: colors.error,
                         border: "1px solid #FCA5A5" }}
              data-testid="drift-days-badge">
          {d.days_with_drift} day(s) with drift
        </div>
      ) : (
        <div className="mt-3 inline-flex items-center gap-1 text-[10px] font-bold uppercase tracking-wider px-2 py-1 rounded-full"
              style={{ background: "#DCFCE7", color: "#166534",
                         border: "1px solid #86EFAC" }}
              data-testid="drift-days-badge">
          All clean
        </div>
      )}
      {d.worst_day ? (
        <div className="mt-2 text-xs" style={{ color: colors.muted }}
              data-testid="drift-worst-day">
          Worst day:{" "}
          <span className="font-semibold"
                   style={{ color: colors.onSurface }}>
            {d.worst_day.date}
          </span>{" "}
          — {d.worst_day.dangling_refs_total} dangling refs
        </div>
      ) : null}
    </Card>
  );
}


function ManualConversionCard({ data }) {
  const d = data || {};
  const rows = d.by_platform || [];
  return (
    <Card title="Manual Post Conversion"
             testid="analytics-card-manual"
             icon={Send}>
      <div className="grid grid-cols-3 gap-3">
        <Stat label="Generated"
                 value={d.posts_generated_total || 0}
                 testid="manual-generated" />
        <Stat label="Posted"
                 value={d.posts_marked_posted_total || 0}
                 tone="ok"
                 testid="manual-posted" />
        <Stat label="Rate"
                 value={_fmtPct(d.conversion_rate)}
                 testid="manual-rate" />
      </div>
      {rows.length ? (
        <table className="w-full text-sm mt-3"
                  data-testid="manual-per-platform">
          <thead>
            <tr className="text-[10px] font-bold uppercase tracking-wider"
                 style={{ color: colors.muted }}>
              <th className="text-left py-1">Platform</th>
              <th className="text-right py-1">Gen</th>
              <th className="text-right py-1">Posted</th>
              <th className="text-right py-1">Rate</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.platform}
                    className="border-t"
                    style={{ borderColor: colors.border,
                                color: colors.onSurface }}
                    data-testid={`manual-row-${r.platform}`}>
                <td className="py-1 capitalize">{r.platform}</td>
                <td className="text-right tabular-nums">{r.generated}</td>
                <td className="text-right tabular-nums">{r.marked_posted}</td>
                <td className="text-right tabular-nums font-semibold">
                  {_fmtPct(r.conversion_rate)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <EmptyCell msg="No manual-only drafts this month"
                       testid="manual-empty" />
      )}
    </Card>
  );
}


export default function AnalyticsMonthlyPage() {
  const options = useMemo(_monthOptions, []);
  const [month, setMonth] = useState(options[0].value);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  const load = useCallback(async (m) => {
    setLoading(true);
    setErr("");
    try {
      const res = await api.get(
        `/admin/analytics/monthly?month=${encodeURIComponent(m)}`);
      setData(res || null);
    } catch (e) {
      setErr(e?.message || "Failed to load analytics");
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(month); }, [month, load]);

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6"
         data-testid="analytics-monthly-page">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-2xl font-bold"
               style={{ color: colors.onSurface }}>
            Analytics
          </h1>
          <p className="text-sm mt-1"
              style={{ color: colors.muted }}>
            Monthly rollups across Soshie moderation, charge
            templates, drift alerts, and manual-post conversion.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={month}
            onChange={(e) => setMonth(e.target.value)}
            className="text-sm font-semibold px-3 py-1.5 rounded-md"
            style={{ background: colors.surfaceSecondary,
                        color: colors.onSurfaceSecondary,
                        border: `1px solid ${colors.border}` }}
            data-testid="analytics-month-picker"
          >
            {options.map((o) => (
              <option key={o.value} value={o.value}
                         data-testid={`analytics-month-${o.value}`}>
                {o.label}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => load(month)}
            aria-label="Refresh"
            className="p-1 rounded-md"
            style={{ color: colors.muted, background: "transparent" }}
            data-testid="analytics-refresh"
          >
            <RefreshCw size={14} style={{ opacity: loading ? 0.4 : 1 }} />
          </button>
        </div>
      </div>

      {err ? (
        <div className="p-3 text-sm rounded-lg mb-4"
              style={{ background: "#FEE2E2", color: colors.error,
                         border: "1px solid #FCA5A5" }}
              data-testid="analytics-error">
          {err}
        </div>
      ) : null}

      {loading && !data ? (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <CardSkeleton />
          <CardSkeleton />
          <CardSkeleton />
          <CardSkeleton />
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <SoshieCard data={data?.soshie_moderation} />
          <ChargeTemplatesCard data={data?.charge_templates} />
          <DriftCard data={data?.drift_alerts} />
          <ManualConversionCard data={data?.soshie_manual_conversion} />
        </div>
      )}
    </div>
  );
}
