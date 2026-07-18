/**
 * Phase 33 · Step 2 — Scenario Planner panel (web).
 *
 * Structured params + free-text prompt → POST /api/cfo/scenario.
 * Renders the returned 12-month delta chart, annual KPI tiles,
 * confidence badge, caveats, and a save-as-favorite pin. History
 * drawer reads GET /api/cfo/scenario/history?limit=20 (bare array).
 * Honest render — when `result.mocked===true`, we still draw the
 * zero-filled 12-month chart so the layout doesn't collapse, and
 * surface the `reason` string prominently above.
 */
import React, { useCallback, useEffect, useState } from 'react';
import {
  TrendingUp, TrendingDown, Send, ChevronDown, ChevronUp, Loader2,
  Star, StarOff, Sparkles, RotateCw,
} from "lucide-react";
import {
  LineChart, Line, XAxis, YAxis, Tooltip, Legend, CartesianGrid,
  ResponsiveContainer,
} from "recharts";
import { api } from "@/api";

const c = {
  brand: "#0EA5E9",
  border: "#E2E8F0", muted: "#64748B", onSurface: "#0F172A",
  surface: "#FFFFFF", surfaceAlt: "#F8FAFC",
  ok: "#059669", okBg: "#D1FAE5",
  warn: "#B45309", warnBg: "#FEF3C7",
  danger: "#B91C1C", dangerBg: "#FEE2E2",
  neutral: "#7C3AED",
};

const fmt = (n) =>
  typeof n === "number"
    ? n.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 0 })
    : "—";

const relTime = (iso) => {
  if (!iso) return "";
  const s = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60); if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60); if (h < 24) return `${h}h ago`;
  return new Date(iso).toLocaleDateString();
};

function MockedBadge({ reason }) {
  return (
    <span
      title={reason || "Mocked — LLM output unavailable"}
      className="ml-1 inline-flex items-center px-1.5 py-0.5 rounded text-[9px] font-bold uppercase"
      style={{ background: c.warnBg, color: c.warn }}
      data-testid="mocked-badge"
    >mocked</span>
  );
}

const CONF_COLOR = { high: c.ok, medium: c.warn, low: c.danger };

export default function ScenarioPanel({ topCustomers = [], onUsageChange }) {
  const [prompt, setPrompt] = useState("");
  const [hireTechs, setHireTechs] = useState(0);
  const [hourlyRate, setHourlyRate] = useState(20);
  const [priceChangePct, setPriceChangePct] = useState(0);
  const [churn, setChurn] = useState([]);       // array of customer ids
  const [current, setCurrent] = useState(null); // {id, result, tokens_used, favorite, prompt, structured, created_at}
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [quotaHit, setQuotaHit] = useState(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [history, setHistory] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(false);

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true);
    try {
      const rows = await api.get(`/cfo/scenario/history?limit=20`);
      const arr = Array.isArray(rows) ? rows : rows?.items || [];
      arr.sort((a, b) => {
        // favorites first
        if (!!b.favorite !== !!a.favorite) return b.favorite - a.favorite;
        return (new Date(b.created_at).getTime() || 0) - (new Date(a.created_at).getTime() || 0);
      });
      setHistory(arr);
    } catch (_) { /* silent */ }
    finally { setHistoryLoading(false); }
  }, []);
  useEffect(() => { if (historyOpen) loadHistory(); }, [historyOpen, loadHistory]);

  const submit = async (force = false) => {
    if (busy) return;
    const structured = {
      hire_techs: Number(hireTechs) || 0,
      avg_hourly_rate: Number(hourlyRate) || 0,
      price_change_pct: Number(priceChangePct) || 0,
      customer_churn: churn,
    };
    // Ensure prompt is non-empty even when the user only touched sliders.
    const body = { prompt: prompt.trim() || _synthesizePrompt(structured), structured };
    if (!body.prompt) { setErr("Give a prompt or move a slider off zero."); return; }
    setBusy(true); setErr(""); setQuotaHit(null); setCurrent(null);
    try {
      const path = `/cfo/scenario${force ? "?force=true" : ""}`;
      const r = await api.post(path, body);
      if (r?.error === "quota_exceeded") {
        setQuotaHit(r.usage || null);
        return;
      }
      setCurrent({
        id: r.history_id, result: r.result, tokens_used: r.tokens_used || 0,
        favorite: false, prompt: body.prompt, structured,
        created_at: new Date().toISOString(),
      });
      onUsageChange?.();
      if (historyOpen) loadHistory();
    } catch (e) {
      setErr(e?.message || "Scenario request failed.");
    } finally {
      setBusy(false);
    }
  };

  const toggleFavorite = async () => {
    if (!current?.id) return;
    const next = !current.favorite;
    try {
      await api.post(`/cfo/scenario/${current.id}/save-as-favorite?favorite=${next}`);
      setCurrent({ ...current, favorite: next });
      if (historyOpen) loadHistory();
    } catch (_) { /* silent */ }
  };

  const loadFromHistory = (row) => {
    setCurrent({
      id: row.id, result: row.result, tokens_used: row.tokens_used || 0,
      favorite: !!row.favorite, prompt: row.prompt, structured: row.structured || {},
      created_at: row.created_at, readonly: true,
    });
    setPrompt(row.prompt || "");
    const s = row.structured || {};
    setHireTechs(s.hire_techs ?? 0);
    setHourlyRate(s.avg_hourly_rate ?? 20);
    setPriceChangePct(s.price_change_pct ?? 0);
    setChurn(s.customer_churn || []);
  };

  const monthlyData = (current?.result?.monthly_delta || []).map((m) => ({
    month: `M${m.month}`,
    revenue_delta: m.revenue_delta,
    expense_delta: m.expense_delta,
    net_delta: m.net_delta,
  }));

  return (
    <div className="rounded-xl p-4 mb-6"
         style={{ background: c.surface, border: `1px solid ${c.border}` }}
         data-testid="cfo-scenario-panel">
      <div className="flex items-center gap-2 mb-3">
        <TrendingUp size={16} color={c.brand} />
        <div className="text-sm font-bold" style={{ color: c.onSurface }}>Scenario Planner</div>
        <div style={{ flex: 1 }} />
        <button
          onClick={() => setHistoryOpen((x) => !x)}
          className="inline-flex items-center gap-1 text-xs font-semibold"
          style={{ background: "transparent", border: 0, cursor: "pointer", color: c.muted }}
          data-testid="cfo-scenario-history-toggle"
        >
          {historyOpen ? <ChevronUp size={12} /> : <ChevronDown size={12} />} History
        </button>
      </div>

      {/* Inputs */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-3">
        <div>
          <label className="text-[10px] font-bold uppercase tracking-wider" style={{ color: c.muted }}>
            Hire techs
          </label>
          <input type="number" min={0} max={10} value={hireTechs}
                  onChange={(e) => setHireTechs(e.target.value)}
                  disabled={busy}
                  className="w-full px-2 py-1.5 rounded-md text-sm mt-1"
                  style={{ border: `1px solid ${c.border}`, background: c.surface }}
                  data-testid="cfo-scenario-hire-techs" />
        </div>
        <div>
          <label className="text-[10px] font-bold uppercase tracking-wider" style={{ color: c.muted }}>
            Avg hourly rate ($)
          </label>
          <input type="number" min={0} step={0.5} value={hourlyRate}
                  onChange={(e) => setHourlyRate(e.target.value)}
                  disabled={busy}
                  className="w-full px-2 py-1.5 rounded-md text-sm mt-1"
                  style={{ border: `1px solid ${c.border}`, background: c.surface }}
                  data-testid="cfo-scenario-hourly-rate" />
        </div>
        <div>
          <label className="text-[10px] font-bold uppercase tracking-wider" style={{ color: c.muted }}>
            Price change % ({priceChangePct >= 0 ? "+" : ""}{priceChangePct}%)
          </label>
          <input type="range" min={-20} max={50} value={priceChangePct}
                  onChange={(e) => setPriceChangePct(Number(e.target.value))}
                  disabled={busy}
                  className="w-full mt-2"
                  data-testid="cfo-scenario-price-change" />
        </div>
        <div>
          <label className="text-[10px] font-bold uppercase tracking-wider" style={{ color: c.muted }}>
            Customers to churn
          </label>
          {topCustomers.length === 0 ? (
            <div className="text-xs italic mt-1" style={{ color: c.muted }}
                  data-testid="cfo-scenario-churn-empty">
              No top customers loaded yet.
            </div>
          ) : (
            <select
              multiple
              value={churn}
              onChange={(e) => setChurn(Array.from(e.target.selectedOptions, (o) => o.value))}
              disabled={busy}
              className="w-full px-2 py-1 rounded-md text-xs mt-1"
              style={{ border: `1px solid ${c.border}`, background: c.surface, minHeight: 46 }}
              data-testid="cfo-scenario-churn"
            >
              {topCustomers.slice(0, 10).map((cust) => (
                <option key={cust.customer_id || cust.customer_name}
                        value={cust.customer_id || cust.customer_name}>
                  {cust.customer_name} ({fmt(cust.total)})
                </option>
              ))}
            </select>
          )}
        </div>
      </div>

      <textarea
        rows={2}
        value={prompt}
        onChange={(e) => setPrompt(e.target.value)}
        disabled={busy}
        placeholder="Optional free-text prompt (e.g. 'What if we win the HOA contract worth $8K/month?')"
        className="w-full px-3 py-2 rounded-md text-sm mb-2"
        style={{ border: `1px solid ${c.border}`, background: c.surface, resize: "vertical" }}
        data-testid="cfo-scenario-prompt"
      />

      <div className="flex items-center gap-2 mb-2">
        <div className="text-xs" style={{ color: c.muted }}>
          Claude will project a 12-month P&L delta.
        </div>
        <div style={{ flex: 1 }} />
        <button
          onClick={() => submit(false)}
          disabled={busy}
          className="inline-flex items-center gap-2 px-3 py-1.5 rounded-md text-sm font-bold"
          style={{ background: c.brand, color: "#fff", border: 0,
                    cursor: busy ? "wait" : "pointer",
                    opacity: busy ? 0.6 : 1 }}
          data-testid="cfo-scenario-submit"
        >
          {busy ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
          Run scenario
        </button>
      </div>

      {err ? (
        <div className="text-xs px-2 py-2 rounded mt-2"
             style={{ background: c.dangerBg, color: c.danger }}
             data-testid="cfo-scenario-error">{err}</div>
      ) : null}

      {quotaHit ? (
        <div className="text-xs px-3 py-2 rounded flex items-center gap-2 mt-2"
             style={{ background: c.warnBg, color: c.warn }}
             data-testid="cfo-scenario-quota-banner">
          <span style={{ flex: 1 }}>
            Daily quota reached ({quotaHit.request_count}/{quotaHit.quota}).
          </span>
          <button
            onClick={() => submit(true)}
            className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs font-bold"
            style={{ background: c.warn, color: "#fff", border: 0, cursor: "pointer" }}
            data-testid="cfo-scenario-force-submit"
          >
            <RotateCw size={12} /> Force submit
          </button>
        </div>
      ) : null}

      {/* Result area */}
      {busy ? (
        <div className="mt-3 p-4 rounded-lg flex items-center justify-center"
             style={{ background: c.surfaceAlt, border: `1px dashed ${c.border}` }}
             data-testid="cfo-scenario-loading">
          <Loader2 size={18} className="animate-spin" color={c.brand} />
          <span className="ml-2 text-xs" style={{ color: c.muted }}>Projecting 12 months…</span>
        </div>
      ) : current?.result ? (
        <div className="mt-3 space-y-3" data-testid="cfo-scenario-result">
          {/* Mocked banner */}
          {current.result.mocked ? (
            <div className="text-xs px-3 py-2 rounded flex items-center gap-2"
                 style={{ background: c.warnBg, color: c.warn }}
                 data-testid="cfo-scenario-mocked-reason">
              <Sparkles size={12} />
              LLM unavailable — {current.result.reason || "no reason"}. Chart below
              is a zero-filled placeholder so the layout stays honest.
              <MockedBadge reason={current.result.reason} />
            </div>
          ) : null}

          {/* Assumptions + prompt + favorite */}
          <div className="rounded-lg p-3"
               style={{ background: c.surfaceAlt, border: `1px solid ${c.border}` }}>
            <div className="flex items-center gap-2 mb-2">
              <div className="text-[11px] font-bold uppercase tracking-wider"
                   style={{ color: c.muted, flex: 1 }}>
                Assumptions · <span style={{ color: c.onSurface, textTransform: "none",
                                              fontWeight: 400 }}>{current.prompt}</span>
              </div>
              <button
                onClick={toggleFavorite}
                className="inline-flex items-center gap-1 text-xs font-bold"
                style={{ background: "transparent", border: 0, cursor: "pointer",
                          color: current.favorite ? c.warn : c.muted }}
                data-testid="cfo-scenario-favorite"
              >
                {current.favorite ? <Star size={14} fill={c.warn} /> : <StarOff size={14} />}
                {current.favorite ? "Favorited" : "Save"}
              </button>
            </div>
            <ul className="text-xs pl-4 list-disc" style={{ color: c.onSurface }}>
              {(current.result.assumptions || []).map((a, i) => (<li key={i}>{a}</li>))}
              {(current.result.assumptions || []).length === 0 ? (
                <li style={{ color: c.muted }}>No assumptions returned.</li>
              ) : null}
            </ul>
          </div>

          {/* Monthly delta chart */}
          <div className="rounded-lg p-3"
               style={{ background: c.surface, border: `1px solid ${c.border}` }}
               data-testid="cfo-scenario-monthly-chart">
            <div className="text-[11px] font-bold uppercase tracking-wider mb-2"
                 style={{ color: c.muted }}>Monthly Δ (12 months)</div>
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={monthlyData}>
                <CartesianGrid strokeDasharray="3 3" stroke={c.border} />
                <XAxis dataKey="month" tick={{ fontSize: 10 }} />
                <YAxis tick={{ fontSize: 10 }} />
                <Tooltip formatter={(v) => fmt(v)} />
                <Legend />
                <Line type="monotone" dataKey="revenue_delta" stroke={c.ok}      strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="expense_delta" stroke={c.danger}  strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="net_delta"     stroke={c.neutral} strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          </div>

          {/* Annual KPI tiles */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2"
               data-testid="cfo-scenario-annual">
            <Tile testid="cfo-scenario-annual-revenue"
                  label="Annual Δ Revenue" value={fmt(current.result.annual?.revenue_delta)} />
            <Tile testid="cfo-scenario-annual-expense"
                  label="Annual Δ Expense" value={fmt(current.result.annual?.expense_delta)} />
            <Tile testid="cfo-scenario-annual-net"
                  label="Annual Δ Net"
                  value={fmt(current.result.annual?.net_delta)}
                  emphasize
                  positive={(current.result.annual?.net_delta ?? 0) >= 0} />
            <Tile testid="cfo-scenario-annual-margin"
                  label="Δ Margin %"
                  value={typeof current.result.annual?.margin_delta_pct === "number"
                    ? `${current.result.annual.margin_delta_pct.toFixed(2)}%` : "—"} />
          </div>

          {/* Confidence + caveats */}
          <div className="flex items-center gap-3">
            <span
              className="px-2 py-1 rounded text-[10px] font-bold uppercase"
              style={{ background: CONF_COLOR[current.result.confidence] || c.muted,
                        color: "#fff" }}
              data-testid="cfo-scenario-confidence"
            >
              Confidence: {current.result.confidence || "unknown"}
            </span>
            <div className="text-[10px]" style={{ color: c.muted }}>
              {relTime(current.created_at)} · Tokens: {current.tokens_used}
              {current.readonly ? " · from history" : ""}
            </div>
          </div>
          {(current.result.caveats || []).length > 0 ? (
            <div className="rounded-lg p-3"
                 style={{ background: c.warnBg, border: `1px solid ${c.warn}` }}
                 data-testid="cfo-scenario-caveats">
              <div className="text-[11px] font-bold uppercase mb-1" style={{ color: c.warn }}>
                Caveats
              </div>
              <ul className="text-xs pl-4 list-disc" style={{ color: c.warn }}>
                {current.result.caveats.map((cv, i) => (<li key={i}>{cv}</li>))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : null}

      {/* History drawer */}
      {historyOpen ? (
        <div className="mt-4 border-t pt-3" style={{ borderColor: c.border }}
             data-testid="cfo-scenario-history-list">
          <div className="text-[10px] font-bold uppercase tracking-wider mb-2"
               style={{ color: c.muted }}>
            History (latest 20 · favorites first)
          </div>
          {historyLoading ? (
            <div className="flex items-center gap-2 text-xs" style={{ color: c.muted }}>
              <Loader2 size={12} className="animate-spin" /> Loading…
            </div>
          ) : history.length === 0 ? (
            <div className="text-xs" style={{ color: c.muted }}
                 data-testid="cfo-scenario-history-empty">
              No scenarios run yet.
            </div>
          ) : history.map((row) => (
            <button
              key={row.id}
              onClick={() => loadFromHistory(row)}
              className="w-full flex items-center gap-2 text-left px-2 py-2 rounded"
              style={{ background: "transparent", border: 0, cursor: "pointer",
                        borderBottom: `1px solid ${c.border}` }}
              data-testid="cfo-scenario-history-item"
            >
              {row.favorite
                ? <Star size={12} fill={c.warn} color={c.warn} />
                : <TrendingDown size={11} color={c.muted} />}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className="text-xs truncate" style={{ color: c.onSurface }}>
                  {row.prompt}
                </div>
                <div className="text-[10px]" style={{ color: c.muted }}>
                  {relTime(row.created_at)} · Δnet
                  {" "}{fmt(row.result?.annual?.net_delta)}
                  {" "}· {row.tokens_used || 0} tokens
                  {row.result?.mocked ? " · mocked" : ""}
                </div>
              </div>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function Tile({ testid, label, value, emphasize, positive }) {
  const c = {
    border: "#E2E8F0", muted: "#64748B", onSurface: "#0F172A",
    surface: "#FFFFFF",
    ok: "#059669", danger: "#B91C1C",
  };
  return (
    <div className="p-3 rounded-lg"
         style={{ background: c.surface, border: `1px solid ${c.border}` }}
         data-testid={testid}>
      <div className="text-[10px] font-bold uppercase tracking-wider"
           style={{ color: c.muted }}>{label}</div>
      <div className="text-lg font-bold mt-1"
           style={{ color: emphasize ? (positive ? c.ok : c.danger) : c.onSurface }}>
        {value}
      </div>
    </div>
  );
}

function _synthesizePrompt(s) {
  const parts = [];
  if (s.hire_techs) parts.push(`hire ${s.hire_techs} techs at $${s.avg_hourly_rate}/hr`);
  if (s.price_change_pct) parts.push(`change prices by ${s.price_change_pct}%`);
  if ((s.customer_churn || []).length) parts.push(`lose ${s.customer_churn.length} customers`);
  return parts.length ? `Scenario: ${parts.join("; ")}.` : "";
}
