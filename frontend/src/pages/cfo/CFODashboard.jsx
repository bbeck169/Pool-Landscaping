/**
 * Phase 32 · Step 2 — AI CFO Dashboard (web).
 *
 * Read-only Wave-1+2 CFO surface. Consumes ONLY the backend spine
 * shipped in Step 1:
 *
 *   GET  /api/cfo/dashboard?period=…
 *   GET  /api/cfo/forecast?horizon=…
 *   GET  /api/cfo/anomalies?window_days=…&z=…
 *   POST /api/cfo/categorize?dry_run=…&force=…
 *   GET  /api/cfo/llm-usage
 *
 * Honest UI — every field the backend flags `mocked:true` renders
 * dimmed with a `mocked-badge` tooltip carrying the `reason` string.
 * No silent fallbacks.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  TrendingUp, DollarSign, Wallet, Percent, PieChart as PieIcon, LineChart as LineIcon,
  AlertTriangle, Sparkles, Loader2, RefreshCw,
} from "lucide-react";
import {
  BarChart, Bar, PieChart, Pie, Cell, ComposedChart, Line, Area,
  XAxis, YAxis, Tooltip, ResponsiveContainer, Legend, CartesianGrid,
} from "recharts";
import { api } from "@/api";
import { useAuth } from "@/auth";
import { Forbidden } from "@/hooks/usePermissions";
import QnAPanel from "@/components/cfo/QnAPanel";
import ScenarioPanel from "@/components/cfo/ScenarioPanel";

const c = {
  brand: "#0EA5E9", brandDark: "#075985",
  border: "#E2E8F0", muted: "#64748B", onSurface: "#0F172A",
  surface: "#FFFFFF", surfaceAlt: "#F8FAFC",
  ok: "#059669", okBg: "#D1FAE5",
  warn: "#B45309", warnBg: "#FEF3C7",
  danger: "#B91C1C", dangerBg: "#FEE2E2",
  chart: ["#0EA5E9", "#059669", "#B45309", "#7C3AED", "#DB2777", "#0891B2",
           "#65A30D", "#DC2626", "#6B7280"],
};

const CATEGORY_ORDER = [
  "labor", "chemicals", "fuel", "equipment", "marketing",
  "insurance", "subscription", "tax", "other",
];

const fmt = (n) =>
  typeof n === "number"
    ? n.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 0 })
    : "—";

// ─── Mocked badge (shared) ────────────────────────────────────────────
function MockedBadge({ reason }) {
  return (
    <span
      title={reason || "Mocked value — data source not wired"}
      className="ml-1 inline-flex items-center px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wide"
      style={{ background: c.warnBg, color: c.warn }}
      data-testid="mocked-badge"
    >
      mocked
    </span>
  );
}

// ─── KPI tile ─────────────────────────────────────────────────────────
function KPI({ testid, label, value, icon: Icon, mocked, reason, sub }) {
  return (
    <div
      className="p-4 rounded-xl"
      style={{ background: c.surface, border: `1px solid ${c.border}` }}
      data-testid={testid}
    >
      <div className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-wider"
           style={{ color: c.muted }}>
        {Icon ? <Icon size={12} /> : null}
        {label}
        {mocked ? <MockedBadge reason={reason} /> : null}
      </div>
      <div className={`text-xl font-bold mt-1 ${mocked ? "opacity-60" : ""}`}
           style={{ color: c.onSurface }}>
        {value}
      </div>
      {sub ? (
        <div className="text-[11px] mt-1" style={{ color: c.muted }}>{sub}</div>
      ) : null}
    </div>
  );
}

// ─── Categorize preview modal ─────────────────────────────────────────
// Phase 32 · Step 2 · T2 fix — modal now auto-closes after a successful
// confirm. The parent handles the success/warning banner + refresh.
function CategorizeModal({ open, onClose, onConfirmed }) {
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (!open) { setPreview(null); setBusy(false); setErr(""); return; }
    (async () => {
      setBusy(true); setErr("");
      try {
        const p = await api.post("/cfo/categorize?dry_run=true&force=true",
                                   { limit: 100 });
        setPreview(p);
      } catch (e) { setErr(e?.message || "Preview failed."); }
      finally { setBusy(false); }
    })();
  }, [open]);

  const confirm = async () => {
    setBusy(true); setErr("");
    try {
      const r = await api.post("/cfo/categorize?dry_run=false&force=true",
                                { limit: 100 });
      // T2 fix: bubble the result to the parent and close the modal in
      // the same tick. The parent renders the success/warning banner
      // and triggers the dashboard refresh — no post-confirm state
      // survives inside the modal.
      onConfirmed?.(r);
      onClose?.();
    } catch (e) {
      setErr(e?.message || "Categorize failed.");
    } finally { setBusy(false); }
  };

  if (!open) return null;
  return (
    <div
      onClick={onClose}
      style={{ position: "fixed", inset: 0, zIndex: 50,
                background: "rgba(15,23,42,0.55)",
                display: "flex", alignItems: "center", justifyContent: "center" }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{ background: c.surface, borderRadius: 12, width: "min(520px, 96vw)",
                  padding: 20, boxShadow: "0 20px 60px rgba(0,0,0,0.35)" }}
        data-testid="cfo-categorize-preview"
      >
        <div className="text-lg font-bold mb-2" style={{ color: c.onSurface }}>
          Auto-categorize expenses
        </div>
        <div className="text-xs mb-3" style={{ color: c.muted }}>
          Uses Claude via Emergent LLM. Categories:
          {" "}{CATEGORY_ORDER.join(", ")}.
        </div>

        {busy && !preview ? (
          <div className="py-6 flex items-center justify-center">
            <Loader2 className="animate-spin" size={22} color={c.brand} />
          </div>
        ) : null}

        {err ? (
          <div className="text-xs px-2 py-2 rounded mb-3"
               style={{ background: c.dangerBg, color: c.danger }}
               data-testid="cfo-categorize-error">{err}</div>
        ) : null}

        {preview ? (
          <div className="space-y-2 text-sm" data-testid="cfo-categorize-preview-body">
            <div>Scanned: <b>{preview.scanned}</b> uncategorized checks.</div>
            <div>Would categorize (dry-run): <b>{preview.categorized}</b></div>
            <div className="text-xs" style={{ color: c.muted }}>
              Tokens (est): {preview.tokens_used} · Quota used:
              {" "}{preview.usage?.request_count}/{preview.usage?.quota}
            </div>
            {preview.mocked && (preview.reasons || []).length > 0 ? (
              <div className="text-xs px-2 py-1 rounded"
                   style={{ background: c.warnBg, color: c.warn }}>
                LLM reasons: {(preview.reasons || []).join(" · ")}
              </div>
            ) : null}
          </div>
        ) : null}

        <div className="flex items-center gap-2 mt-4">
          <div style={{ flex: 1 }} />
          <button
            onClick={onClose}
            className="px-3 py-1.5 rounded-md text-sm font-semibold"
            style={{ border: `1px solid ${c.border}`, background: c.surface,
                      color: c.onSurface, cursor: "pointer" }}
            data-testid="cfo-categorize-cancel"
          >
            Cancel
          </button>
          <button
            onClick={confirm}
            disabled={busy || !preview}
            className="px-3 py-1.5 rounded-md text-sm font-bold"
            style={{ background: c.brand, color: "#fff", border: 0,
                      cursor: busy ? "wait" : "pointer",
                      opacity: (busy || !preview) ? 0.6 : 1 }}
            data-testid="cfo-categorize-confirm"
          >
            {busy ? "Running…" : "Run auto-categorize"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Dashboard ────────────────────────────────────────────────────────
export default function CFODashboard() {
  const { user } = useAuth();
  const role = user?.role || "";
  const allowed = role === "admin" || role === "super_admin";

  const [period, setPeriod] = useState("ytd");
  const [customStart, setCustomStart] = useState("");
  const [customEnd, setCustomEnd] = useState("");
  const [horizon, setHorizon] = useState(60);
  const [dash, setDash] = useState(null);
  const [forecast, setForecast] = useState(null);
  const [anom, setAnom] = useState(null);
  const [usage, setUsage] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [categorizeOpen, setCategorizeOpen] = useState(false);
  // T2 fix — top-of-page banner surfaced after the categorize modal
  // closes. `{kind: 'ok'|'warn', text}`. Auto-dismisses after 6s.
  const [categorizeBanner, setCategorizeBanner] = useState(null);

  const load = useCallback(async () => {
    if (!allowed) return;
    setLoading(true); setErr("");
    try {
      const qs = new URLSearchParams({ period });
      if (period === "custom" && customStart) qs.set("start", customStart);
      if (period === "custom" && customEnd)   qs.set("end", customEnd);
      const [d, f, a, u] = await Promise.all([
        api.get(`/cfo/dashboard?${qs.toString()}`),
        api.get(`/cfo/forecast?horizon=${horizon}`),
        api.get(`/cfo/anomalies?window_days=90&z=2.0`),
        api.get(`/cfo/llm-usage`).catch(() => null),
      ]);
      setDash(d); setForecast(f); setAnom(a); setUsage(u);
    } catch (e) { setErr(e?.message || "Failed to load."); }
    finally { setLoading(false); }
  }, [allowed, period, customStart, customEnd, horizon]);
  useEffect(() => { load(); }, [load]);

  const expenseChartData = useMemo(() => {
    if (!dash?.expense_by_category) return [];
    const idx = Object.fromEntries(CATEGORY_ORDER.map((k, i) => [k, i]));
    return [...dash.expense_by_category].sort(
      (a, b) => (idx[a.category] ?? 99) - (idx[b.category] ?? 99)
    );
  }, [dash]);

  if (!allowed) {
    return <Forbidden reason="AI CFO is admin-only." />;
  }

  return (
    <div className="p-4 md:p-6" style={{ background: c.surfaceAlt, minHeight: "100%" }}
         data-testid="cfo-dashboard">
      {/* Header */}
      <div className="flex items-center gap-3 mb-4">
        <TrendingUp size={22} color={c.brand} />
        <div>
          <div className="text-2xl font-bold" style={{ color: c.onSurface }}>AI CFO</div>
          <div className="text-xs" style={{ color: c.muted }}>
            Revenue · Expenses · Cash · Forecast · Anomalies · Auto-categorize.
          </div>
        </div>
        <div style={{ flex: 1 }} />
        <button onClick={load}
                className="inline-flex items-center gap-1 px-3 py-1.5 rounded-md text-sm font-semibold"
                style={{ background: c.surface, border: `1px solid ${c.border}`, cursor: "pointer" }}
                data-testid="cfo-refresh">
          {loading ? <Loader2 className="animate-spin" size={14} /> : <RefreshCw size={14} />}
          Refresh
        </button>
        <button onClick={() => setCategorizeOpen(true)}
                className="inline-flex items-center gap-1 px-3 py-1.5 rounded-md text-sm font-bold"
                style={{ background: c.brand, color: "#fff", border: 0, cursor: "pointer" }}
                data-testid="cfo-run-categorize">
          <Sparkles size={14} /> Run auto-categorize
        </button>
      </div>

      {err ? (
        <div className="rounded-md p-3 text-sm mb-4"
             style={{ background: c.dangerBg, color: c.danger, border: `1px solid ${c.danger}` }}
             data-testid="cfo-error">{err}</div>
      ) : null}

      {/* T2 fix — categorize completion banner (auto-dismisses in 6s). */}
      {categorizeBanner ? (
        <div
          className="rounded-md p-3 text-sm mb-4 flex items-center gap-2"
          style={{
            background: categorizeBanner.kind === "ok" ? c.okBg : c.warnBg,
            color: categorizeBanner.kind === "ok" ? c.ok : c.warn,
            border: `1px solid ${categorizeBanner.kind === "ok" ? c.ok : c.warn}`,
          }}
          data-testid="cfo-categorize-done"
        >
          <Sparkles size={14} />
          <span style={{ flex: 1 }}>{categorizeBanner.text}</span>
          <button
            onClick={() => setCategorizeBanner(null)}
            className="text-xs font-bold"
            style={{ background: "transparent", border: 0, cursor: "pointer",
                      color: "inherit" }}
            data-testid="cfo-categorize-done-dismiss"
          >
            Dismiss
          </button>
        </div>
      ) : null}

      {/* Period pills */}
      <div className="flex items-center gap-2 mb-4" data-testid="cfo-period-pills">
        {[
          { k: "mtd", label: "MTD" },
          { k: "qtd", label: "QTD" },
          { k: "ytd", label: "YTD" },
          { k: "custom", label: "Custom" },
        ].map((p) => (
          <button
            key={p.k}
            onClick={() => setPeriod(p.k)}
            className="px-3 py-1.5 rounded-full text-xs font-bold"
            style={{
              background: period === p.k ? c.brand : c.surface,
              color: period === p.k ? "#fff" : c.onSurface,
              border: `1px solid ${period === p.k ? c.brand : c.border}`,
              cursor: "pointer",
            }}
            data-testid={`cfo-period-${p.k}`}
          >
            {p.label}
          </button>
        ))}
        {period === "custom" ? (
          <>
            <input type="date" value={customStart}
                    onChange={(e) => setCustomStart(e.target.value)}
                    className="px-2 py-1 rounded-md text-xs"
                    style={{ border: `1px solid ${c.border}`, background: c.surface }}
                    data-testid="cfo-period-custom-start" />
            <span className="text-xs" style={{ color: c.muted }}>→</span>
            <input type="date" value={customEnd}
                    onChange={(e) => setCustomEnd(e.target.value)}
                    className="px-2 py-1 rounded-md text-xs"
                    style={{ border: `1px solid ${c.border}`, background: c.surface }}
                    data-testid="cfo-period-custom-end" />
          </>
        ) : null}
      </div>

      {/* KPI grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
        <KPI testid="cfo-kpi-revenue" label="Revenue" value={fmt(dash?.revenue?.total)}
             icon={DollarSign} mocked={dash?.revenue?.mocked} />
        <KPI testid="cfo-kpi-expenses" label="Expenses" value={fmt(dash?.expenses?.total)}
             icon={DollarSign} mocked={dash?.expenses?.mocked} />
        <KPI testid="cfo-kpi-gross-profit" label="Gross Profit" value={fmt(dash?.gross_profit)}
             icon={TrendingUp} />
        <KPI testid="cfo-kpi-margin" label="Profit Margin" value={
              dash ? `${dash.profit_margin_pct?.toFixed(1)}%` : "—"
             } icon={Percent} />
        <KPI testid="cfo-kpi-cash-on-hand" label="Cash on Hand"
             value={fmt(dash?.cash_on_hand?.value)}
             icon={Wallet}
             mocked={dash?.cash_on_hand?.mocked}
             reason={dash?.cash_on_hand?.reason} />
        <KPI testid="cfo-ar-0-30"    label="AR 0-30"    value={fmt(dash?.ar_aging?.["0_30"])} />
        <KPI testid="cfo-ar-31-60"   label="AR 31-60"   value={fmt(dash?.ar_aging?.["31_60"])} />
        <KPI testid="cfo-ar-61-90"   label="AR 61-90"   value={fmt(dash?.ar_aging?.["61_90"])} />
        <KPI testid="cfo-ar-90-plus" label="AR 90+"     value={fmt(dash?.ar_aging?.["90_plus"])} />
        <div className="col-span-2 md:col-span-3 p-3 rounded-xl text-xs"
             style={{ background: c.warnBg, color: c.warn, border: `1px solid ${c.warn}` }}
             title={dash?.ap_aging?.reason || ""}
             data-testid="cfo-ap-aging">
          AP aging unavailable
          <MockedBadge reason={dash?.ap_aging?.reason} />
          <div className="text-[11px] mt-0.5" style={{ color: c.warn }}>
            {dash?.ap_aging?.reason || "AP bills collection is not wired in this environment."}
          </div>
        </div>
      </div>

      {/* Revenue by source + Expenses by category */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 mb-6">
        <div className="rounded-xl p-4" style={{ background: c.surface, border: `1px solid ${c.border}` }}
             data-testid="cfo-revenue-source">
          <div className="text-sm font-bold flex items-center gap-1 mb-3" style={{ color: c.onSurface }}>
            <DollarSign size={14} /> Revenue by source
          </div>
          {(dash?.revenue_by_source || []).length === 0 ? (
            <div className="text-xs" style={{ color: c.muted }}>No revenue in this period.</div>
          ) : (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={dash.revenue_by_source}>
                <CartesianGrid strokeDasharray="3 3" stroke={c.border} />
                <XAxis dataKey="source" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} />
                <Tooltip formatter={(v) => fmt(v)} />
                <Bar dataKey="total" fill={c.brand} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>

        <div className="rounded-xl p-4" style={{ background: c.surface, border: `1px solid ${c.border}` }}
             data-testid="cfo-expense-category">
          <div className="text-sm font-bold flex items-center gap-1 mb-3" style={{ color: c.onSurface }}>
            <PieIcon size={14} /> Expenses by category
          </div>
          {expenseChartData.length === 0 ? (
            <div className="text-xs" style={{ color: c.muted }}>No categorized expenses yet — try Run auto-categorize.</div>
          ) : (
            <ResponsiveContainer width="100%" height={220}>
              <PieChart>
                <Pie data={expenseChartData} dataKey="total" nameKey="category"
                      cx="50%" cy="50%" outerRadius={80} label={(e) => e.category}>
                  {expenseChartData.map((_, i) => (
                    <Cell key={i} fill={c.chart[i % c.chart.length]} />
                  ))}
                </Pie>
                <Tooltip formatter={(v) => fmt(v)} />
              </PieChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      {/* Forecast */}
      <div className="rounded-xl p-4 mb-6" style={{ background: c.surface, border: `1px solid ${c.border}` }}
           data-testid="cfo-forecast">
        <div className="flex items-center gap-2 mb-3">
          <LineIcon size={14} color={c.brand} />
          <div className="text-sm font-bold" style={{ color: c.onSurface }}>Cash Flow Forecast</div>
          {forecast?.mocked ? <MockedBadge reason={forecast.reason} /> : null}
          <div style={{ flex: 1 }} />
          {[30, 60, 90, 180].map((h) => (
            <button key={h}
                    onClick={() => setHorizon(h)}
                    className="px-2 py-1 rounded text-xs font-bold"
                    style={{
                      background: horizon === h ? c.brand : c.surface,
                      color: horizon === h ? "#fff" : c.onSurface,
                      border: `1px solid ${horizon === h ? c.brand : c.border}`,
                      cursor: "pointer",
                    }}
                    data-testid={`cfo-forecast-horizon-${h}`}>{h}d</button>
          ))}
        </div>
        {forecast?.buckets?.length ? (
          <ResponsiveContainer width="100%" height={240}>
            <ComposedChart data={forecast.buckets}>
              <CartesianGrid strokeDasharray="3 3" stroke={c.border} />
              <XAxis dataKey="week_start" tick={{ fontSize: 10 }} />
              <YAxis tick={{ fontSize: 10 }} />
              <Tooltip formatter={(v) => fmt(v)} />
              <Legend />
              <Area type="monotone" dataKey="cash_in"  fill={c.ok}     stroke={c.ok}     fillOpacity={0.25} />
              <Area type="monotone" dataKey="cash_out" fill={c.danger} stroke={c.danger} fillOpacity={0.25} />
              <Line type="monotone" dataKey="net" stroke={c.brandDark} strokeWidth={2} dot={false} />
            </ComposedChart>
          </ResponsiveContainer>
        ) : (
          <div className="text-xs" style={{ color: c.muted }}>No forecast data yet.</div>
        )}
        <div className="flex items-center gap-3 mt-2 text-xs" style={{ color: c.muted }}>
          <div>Net projected: <b>{fmt(forecast?.net_projected)}</b></div>
          {forecast?.runway_days_if_negative != null ? (
            <div style={{ color: c.danger }}>Runway if negative: {forecast.runway_days_if_negative}d</div>
          ) : (
            <div style={{ color: c.ok }}>Positive cash flow projected.</div>
          )}
        </div>
      </div>

      {/* Anomalies */}
      <div className="rounded-xl p-4 mb-6" style={{ background: c.surface, border: `1px solid ${c.border}` }}
           data-testid="cfo-anomalies-list">
        <div className="text-sm font-bold flex items-center gap-2 mb-3" style={{ color: c.onSurface }}>
          <AlertTriangle size={14} color={c.warn} /> Expense anomalies (z ≥ 2.0, last 90d)
        </div>
        {!(anom?.items || []).length ? (
          <div className="text-xs" style={{ color: c.muted }} data-testid="cfo-anomalies-empty">
            No categorized checks in the window yet.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr style={{ color: c.muted, fontSize: 11, textTransform: "uppercase" }}>
                <th className="text-left py-1">Category</th>
                <th className="text-right py-1">Current</th>
                <th className="text-right py-1">Mean</th>
                <th className="text-right py-1">Stddev</th>
                <th className="text-right py-1">Z</th>
                <th className="text-right py-1">Flag</th>
              </tr>
            </thead>
            <tbody>
              {[...anom.items]
                .sort((a, b) => Math.abs(b.current_period_total - b.mean) - Math.abs(a.current_period_total - a.mean))
                .map((it, i) => (
                  <tr key={i} data-testid="cfo-anomaly-item"
                      style={{ borderTop: `1px solid ${c.border}`,
                                background: it.is_anomaly ? c.dangerBg : "transparent" }}>
                    <td className="py-1.5" style={{ color: c.onSurface, fontWeight: 600 }}>{it.category}</td>
                    <td className="py-1.5 text-right">{fmt(it.current_period_total)}</td>
                    <td className="py-1.5 text-right">{fmt(it.mean)}</td>
                    <td className="py-1.5 text-right">{fmt(it.stddev)}</td>
                    <td className="py-1.5 text-right">{it.z.toFixed(1)}</td>
                    <td className="py-1.5 text-right">
                      {it.is_anomaly ? (
                        <span className="px-1.5 py-0.5 rounded text-[10px] font-bold uppercase"
                              style={{ background: c.danger, color: "#fff" }}>anomaly</span>
                      ) : (
                        <span style={{ color: c.muted }}>normal</span>
                      )}
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        )}
      </div>

      {/* LLM usage strip */}
      <div className="rounded-xl px-4 py-3 flex items-center gap-3 text-xs"
           style={{ background: c.surface, border: `1px solid ${c.border}`, color: c.muted }}
           data-testid="cfo-llm-usage">
        <Sparkles size={12} color={c.brand} />
        LLM usage today —
        Requests: <b style={{ color: c.onSurface }}>{usage?.request_count ?? 0}/{usage?.quota ?? 100}</b>
        · Tokens: <b style={{ color: c.onSurface }}>{usage?.tokens_used ?? 0}</b>
        {usage?.request_count >= (usage?.quota ?? 100) ? (
          <span className="ml-2 px-1.5 py-0.5 rounded text-[10px] font-bold uppercase"
                style={{ background: c.warnBg, color: c.warn }}>
            soft-quota hit — use ?force=true to override
          </span>
        ) : null}
      </div>

      <CategorizeModal
        open={categorizeOpen}
        onClose={() => setCategorizeOpen(false)}
        onConfirmed={(r) => {
          // T2 fix — modal closed itself; show the banner + refresh
          // dashboard/anomalies/llm-usage in one call.
          const kind = (r?.mocked || (r?.reasons || []).length > 0) ? "warn" : "ok";
          const text = kind === "ok"
            ? `Categorized ${r?.categorized ?? 0} transactions · used ${r?.tokens_used ?? 0} tokens`
            : `Categorized ${r?.categorized ?? 0} transactions · LLM warning: ${(r?.reasons || []).join(" · ") || "partial mock"}`;
          setCategorizeBanner({ kind, text });
          load();
          // Auto-dismiss after 6s so the banner doesn't linger.
          setTimeout(() => setCategorizeBanner(null), 6000);
        }}
      />

      {/* Phase 33 · Step 2 — Wave 3 UI: NL Q&A + Scenario Planner */}
      <QnAPanel
        period={period}
        customStart={customStart}
        customEnd={customEnd}
        onUsageChange={load}
      />
      <ScenarioPanel
        topCustomers={dash?.top_customers /* falls through when dashboard hasn't hydrated top_customers */ || []}
        onUsageChange={load}
      />
    </div>
  );
}
