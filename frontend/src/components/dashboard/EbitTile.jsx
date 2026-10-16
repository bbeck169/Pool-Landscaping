/**
 * Phase 53e · Feb-2026 — EBIT dashboard tile.
 *
 * Compact exec summary rendered above the fold on the admin +
 * super_admin dashboard. Fetches current-month EBIT + trailing
 * 6-month trend in ONE round trip via ``/ebit/trend?months=6``,
 * so the tile stays snappy on cold-loads.
 *
 * Role gate: parent Dashboard component only mounts this tile when
 * ``user.role in {"super_admin", "admin"}``. Manager sees the full
 * EBIT report page but NOT this dashboard tile — matches Phase 53e
 * scope.
 */
import React, { useEffect, useState, useCallback } from "react";
import { Link, useNavigate } from "react-router-dom";
import { TrendingUp, TrendingDown, Minus, ArrowRight, AlertTriangle } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";

function fmtUSD(n) {
  const v = Number.isFinite(n) ? n : 0;
  const sign = v < 0 ? "-" : "";
  return `${sign}$${Math.abs(v).toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}

function pctDelta(cur, prev) {
  if (!prev || prev === 0) return null;
  return ((cur - prev) / Math.abs(prev)) * 100;
}

function monthEndISO(monthStr) {
  // "YYYY-MM" → { from: "YYYY-MM-01", to: "YYYY-MM-<lastday>" }
  const [y, m] = String(monthStr || "").split("-").map(Number);
  if (!y || !m) return null;
  const last = new Date(Date.UTC(y, m, 0)).getUTCDate();
  const mm = String(m).padStart(2, "0");
  const dd = String(last).padStart(2, "0");
  return { from: `${y}-${mm}-01`, to: `${y}-${mm}-${dd}` };
}

function monthLabel(monthStr) {
  const [y, m] = String(monthStr || "").split("-").map(Number);
  if (!y || !m) return monthStr || "";
  return new Date(Date.UTC(y, m - 1, 1))
    .toLocaleString("en-US", { month: "long", year: "numeric", timeZone: "UTC" });
}

function Sparkline({ series, testid, onPickMonth }) {
  // Compact SVG — same pattern as Phase 54g. Bars height ∝ |ebit|;
  // color green for positive, red for negative. Phase 53f · Feb-2026
  // — each bar is keyboard-focusable + click/Enter/Space triggers a
  // drill-down to /admin/reports/profit?from=&to= for that month.
  const w = 220, h = 44, pad = 2;
  if (!series || series.length === 0) {
    return <svg width={w} height={h} data-testid={testid}><rect width={w} height={h} fill="transparent" /></svg>;
  }
  const maxAbs = Math.max(...series.map((p) => Math.abs(p.ebit || 0)), 1);
  const bw = Math.max(2, (w - pad * 2) / series.length - 2);
  const zeroY = h / 2;
  const handleKey = (p) => (ev) => {
    if (!onPickMonth) return;
    if (ev.key === "Enter" || ev.key === " ") {
      ev.preventDefault();
      onPickMonth(p.month);
    }
  };
  return (
    <svg width={w} height={h} data-testid={testid}>
      <line x1={pad} x2={w - pad} y1={zeroY} y2={zeroY}
            stroke={colors.border} strokeWidth={1} />
      {series.map((p, i) => {
        const v = p.ebit || 0;
        const bh = ((h / 2) - pad) * (Math.abs(v) / maxAbs);
        const x = pad + i * (bw + 2);
        const y = v >= 0 ? zeroY - bh : zeroY;
        return (
          <g
            key={p.month}
            data-testid={`${testid}-bar-${i}`}
            role={onPickMonth ? "button" : undefined}
            tabIndex={onPickMonth ? 0 : undefined}
            aria-label={onPickMonth ? `Open EBIT report for ${monthLabel(p.month)}` : undefined}
            onClick={onPickMonth ? () => onPickMonth(p.month) : undefined}
            onKeyDown={onPickMonth ? handleKey(p) : undefined}
            style={onPickMonth ? { cursor: "pointer", outline: "none" } : undefined}
          >
            {/* Full-height hit target so the whole column is clickable
                even when the ebit bar is 0 pixels tall. */}
            <rect x={x} y={0} width={bw} height={h} fill="transparent" />
            <rect x={x} y={y} width={bw} height={bh}
                  fill={v >= 0 ? "#16A34A" : "#DC2626"} />
          </g>
        );
      })}
    </svg>
  );
}

export default function EbitTile() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const navigate = useNavigate();

  const onPickMonth = useCallback((monthStr) => {
    const range = monthEndISO(monthStr);
    if (!range) return;
    // Phase 53f · Feb-2026 — drill-down. Report page reads ``from``/
    // ``to`` from the URL on mount and pre-selects the custom range.
    navigate(`/admin/reports/profit?from=${range.from}&to=${range.to}`);
  }, [navigate]);

  const load = useCallback(() => {
    setError("");
    api.get("/ebit/trend?months=6&revenue_basis=cash")
      .then((body) => setData(body))
      .catch((e) => setError(e.message || "EBIT unavailable"));
  }, []);

  useEffect(() => { load(); }, [load]);

  const series = data?.series || [];
  const cur = series[series.length - 1];
  const prev = series[series.length - 2];
  // EBITDA-SOFT-ADD · Feb-2026 — headline metric is EBITDA, with
  // EBIT shown as a secondary chip. Each series bucket from
  // /ebit/trend carries BOTH fields post-TD-59; legacy payloads
  // (pre-TD-59 cache or test fixtures) are hydrated via the
  // ``ebit + depreciation`` fallback so the tile always shows a
  // number rather than $NaN.
  const _curEbitda = cur?.ebitda != null
    ? cur.ebitda
    : (Number(cur?.ebit || 0) + Number(cur?.depreciation || 0));
  const _prevEbitda = prev?.ebitda != null
    ? prev.ebitda
    : (Number(prev?.ebit || 0) + Number(prev?.depreciation || 0));
  const curEbitda = _curEbitda || 0;
  const curEbit = cur?.ebit || 0;
  const delta = pctDelta(curEbitda, _prevEbitda);
  const trendIcon = delta == null ? Minus : delta > 0 ? TrendingUp : delta < 0 ? TrendingDown : Minus;
  const TrendIcon = trendIcon;
  const deltaColor = delta == null || delta === 0 ? colors.muted
                                                   : delta > 0 ? "#16A34A" : "#DC2626";

  return (
    <div
      className="rounded-2xl p-5"
      style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
      data-testid="dashboard-ebit-tile"
    >
      <div className="flex items-center justify-between mb-2">
        <div className="text-xs uppercase font-semibold tracking-wide"
             style={{ color: colors.muted }}
             title="EBITDA: Earnings Before Interest, Taxes, Depreciation, and Amortization. A financial metric used to measure a company's overall operational profitability and core earning power."
             data-testid="dashboard-ebit-tile-label">
          Earnings Before Interest, Taxes, Depreciation &amp; Amortization
        </div>
        <Link
          to="/admin/reports/profit"
          className="inline-flex items-center gap-1 text-xs font-medium"
          style={{ color: colors.brandPrimary }}
          data-testid="dashboard-ebit-tile-report-link"
        >
          View report <ArrowRight size={12} />
        </Link>
      </div>

      {error ? (
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-sm" style={{ color: colors.error }}
               data-testid="dashboard-ebit-tile-error">
            <AlertTriangle size={16} /> EBITDA unavailable
          </div>
          <button
            onClick={load}
            className="text-xs underline"
            style={{ color: colors.brandPrimary }}
            data-testid="dashboard-ebit-tile-retry"
          >
            Retry
          </button>
        </div>
      ) : !data ? (
        <div className="text-sm" style={{ color: colors.muted }}
             data-testid="dashboard-ebit-tile-loading">
          Loading current-month EBITDA…
        </div>
      ) : (
        <>
          <div className="flex items-baseline gap-3 flex-wrap">
            <div className="text-3xl font-bold"
                 style={{ color: curEbitda >= 0 ? colors.onSurface : "#DC2626" }}
                 data-testid="dashboard-ebitda-tile-value">
              {fmtUSD(curEbitda)}
            </div>
            {/* EBITDA-SOFT-ADD · secondary EBIT chip. Kept visible
                 for operators who still track EBIT alongside EBITDA. */}
            <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full"
                   style={{ color: colors.muted,
                             backgroundColor: colors.surfaceSecondary }}
                   data-testid="dashboard-ebit-tile-value"
                   title="EBIT = EBITDA − Depreciation − Amortization">
              EBIT {fmtUSD(curEbit)}
            </span>
            {delta != null && (
              <span
                className="inline-flex items-center gap-1 text-xs font-semibold px-2 py-0.5 rounded-full"
                style={{ color: deltaColor,
                          backgroundColor: delta > 0 ? "#DCFCE7"
                                            : delta < 0 ? "#FEE2E2"
                                            : colors.surfaceSecondary }}
                data-testid="dashboard-ebit-tile-delta"
              >
                <TrendIcon size={12} />
                {Math.abs(delta).toFixed(1)}% vs last month
              </span>
            )}
            {delta == null && prev == null && (
              <span className="text-xs" style={{ color: colors.muted }}
                    data-testid="dashboard-ebit-tile-no-prior">
                (no prior-month data)
              </span>
            )}
          </div>

          <div className="mt-3">
            <Sparkline series={series} testid="dashboard-ebit-tile-sparkline" onPickMonth={onPickMonth} />
            <div className="text-[10px] mt-1" style={{ color: colors.muted }}>
              Last {series.length} months · cash-basis
            </div>
          </div>
        </>
      )}
    </div>
  );
}
