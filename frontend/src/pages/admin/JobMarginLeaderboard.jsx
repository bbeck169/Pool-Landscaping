/**
 * Phase 50.D — Job Margin Leaderboard (admin).
 *
 * Ranks the most-profitable and least-profitable closed jobs in a window.
 * Wires to GET /api/reports/job-margin-leaderboard?days=60&limit=20.
 */
import React, { useEffect, useMemo, useState } from "react";
import { TrendingUp, RefreshCw, ChevronDown, ChevronUp } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";

const RANGE_OPTIONS = [30, 60, 90];

function fmtMoney(cents) {
  return `$${(Number(cents || 0) / 100).toFixed(2)}`;
}

function marginTone(pct) {
  if (pct >= 40) return { bg: "#DCFCE7", fg: "#166534", label: "green" };
  if (pct >= 20) return { bg: "#FEF3C7", fg: "#92400E", label: "yellow" };
  return { bg: "#FEE2E2", fg: "#991B1B", label: "red" };
}

export default function JobMarginLeaderboard() {
  const [days, setDays] = useState(60);
  const [limit, setLimit] = useState(20);
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [sortKey, setSortKey] = useState("margin_pct");
  const [sortDir, setSortDir] = useState("desc");

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.get(
        `/reports/job-margin-leaderboard?days=${days}&limit=${limit}`
      );
      setRows(res?.items || []);
    } catch (e) {
      setError(e?.message || "Failed to load leaderboard.");
      setRows([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [days, limit]);

  const sortedRows = useMemo(() => {
    const copy = [...rows];
    copy.sort((a, b) => {
      const av = a?.[sortKey] ?? 0;
      const bv = b?.[sortKey] ?? 0;
      if (typeof av === "string") {
        return sortDir === "asc"
          ? String(av).localeCompare(String(bv))
          : String(bv).localeCompare(String(av));
      }
      return sortDir === "asc" ? av - bv : bv - av;
    });
    return copy;
  }, [rows, sortKey, sortDir]);

  const toggle = (k) => {
    if (sortKey === k) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else { setSortKey(k); setSortDir(k === "customer" ? "asc" : "desc"); }
  };

  const SortIcon = ({ col }) => {
    if (sortKey !== col) return null;
    return sortDir === "asc"
      ? <ChevronUp size={12} style={{ display: "inline", verticalAlign: "middle" }} />
      : <ChevronDown size={12} style={{ display: "inline", verticalAlign: "middle" }} />;
  };

  return (
    <div className="p-4 md:p-8 max-w-6xl mx-auto" data-testid="margin-leaderboard-page">
      <div className="flex items-start md:items-center flex-col md:flex-row md:justify-between gap-3 mb-6">
        <div className="flex items-center gap-3">
          <div
            className="w-11 h-11 rounded-xl flex items-center justify-center"
            style={{ backgroundColor: colors.brandTertiary, color: colors.onBrandTertiary }}
          >
            <TrendingUp size={20} />
          </div>
          <div>
            <h1 className="text-2xl md:text-3xl font-bold" style={{ color: colors.onSurface }}>
              Job Margin Leaderboard
            </h1>
            <p className="text-sm mt-0.5" style={{ color: colors.muted }}>
              Most / least profitable closed jobs in the last {days} days.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <label className="text-xs font-semibold" style={{ color: colors.muted }}>Window</label>
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="text-sm px-2 py-1.5 rounded-md"
            style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
            data-testid="margin-leaderboard-window"
          >
            {RANGE_OPTIONS.map((r) => (
              <option key={r} value={r}>Last {r} days</option>
            ))}
          </select>
          <button
            type="button"
            onClick={load}
            className="inline-flex items-center gap-1 text-xs font-semibold px-2 py-1.5 rounded-md"
            style={{ border: `1px solid ${colors.border}`, color: colors.onSurface, background: colors.surface }}
            data-testid="margin-leaderboard-refresh"
          >
            <RefreshCw size={12} /> Refresh
          </button>
        </div>
      </div>

      {error ? (
        <div className="rounded-2xl p-3 text-sm mb-4"
             style={{ background: "#FEF2F2", border: "1px solid #FECACA", color: "#B91C1C" }}
             data-testid="margin-leaderboard-error">
          {error}
        </div>
      ) : null}

      {loading ? (
        <div className="rounded-2xl p-8 text-center text-sm"
             style={{ background: colors.surface, border: `1px solid ${colors.border}`, color: colors.muted }}>
          Loading…
        </div>
      ) : (
        <div className="rounded-2xl overflow-hidden"
             style={{ background: colors.surface, border: `1px solid ${colors.border}` }}>
          <div className="overflow-x-auto">
            <table className="w-full text-sm" data-testid="margin-leaderboard-table">
              <thead>
                <tr style={{ borderBottom: `1px solid ${colors.border}` }}>
                  <th className="text-left px-3 py-2.5 cursor-pointer select-none uppercase text-[11px] font-semibold"
                      style={{ color: colors.muted }}
                      onClick={() => toggle("customer")}
                      data-testid="margin-sort-customer">
                    Customer <SortIcon col="customer" />
                  </th>
                  <th className="text-left px-3 py-2.5 uppercase text-[11px] font-semibold" style={{ color: colors.muted }}>
                    Job
                  </th>
                  <th className="text-right px-3 py-2.5 cursor-pointer select-none uppercase text-[11px] font-semibold"
                      style={{ color: colors.muted }}
                      onClick={() => toggle("revenue_cents")}
                      data-testid="margin-sort-revenue">
                    Revenue <SortIcon col="revenue_cents" />
                  </th>
                  <th className="text-right px-3 py-2.5 cursor-pointer select-none uppercase text-[11px] font-semibold"
                      style={{ color: colors.muted }}
                      onClick={() => toggle("cost_cents")}
                      data-testid="margin-sort-cost">
                    Cost <SortIcon col="cost_cents" />
                  </th>
                  <th className="text-right px-3 py-2.5 cursor-pointer select-none uppercase text-[11px] font-semibold"
                      style={{ color: colors.muted }}
                      onClick={() => toggle("margin_cents")}
                      data-testid="margin-sort-margin">
                    Margin <SortIcon col="margin_cents" />
                  </th>
                  <th className="text-right px-3 py-2.5 cursor-pointer select-none uppercase text-[11px] font-semibold"
                      style={{ color: colors.muted }}
                      onClick={() => toggle("margin_pct")}
                      data-testid="margin-sort-pct">
                    Margin % <SortIcon col="margin_pct" />
                  </th>
                  <th className="text-right px-3 py-2.5 cursor-pointer select-none uppercase text-[11px] font-semibold"
                      style={{ color: colors.muted }}
                      onClick={() => toggle("service_date")}
                      data-testid="margin-sort-date">
                    Date <SortIcon col="service_date" />
                  </th>
                </tr>
              </thead>
              <tbody>
                {sortedRows.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="px-4 py-8 text-center text-sm"
                        style={{ color: colors.muted }}
                        data-testid="margin-leaderboard-empty">
                      No closed jobs with cost data in this window.
                    </td>
                  </tr>
                ) : (
                  sortedRows.map((r) => {
                    const tone = marginTone(Number(r.margin_pct || 0));
                    return (
                      <tr key={r.job_id}
                          data-testid={`margin-row-${r.job_id}`}
                          style={{ borderBottom: `1px solid ${colors.border}` }}>
                        <td className="px-3 py-2.5" style={{ color: colors.onSurface }}>
                          {r.customer || "—"}
                        </td>
                        <td className="px-3 py-2.5 text-xs" style={{ color: colors.muted }}>
                          {r.service_type || r.title || "—"}
                        </td>
                        <td className="px-3 py-2.5 text-right font-semibold" style={{ color: colors.onSurface }}>
                          {fmtMoney(r.revenue_cents)}
                        </td>
                        <td className="px-3 py-2.5 text-right" style={{ color: colors.onSurface }}>
                          {fmtMoney(r.cost_cents)}
                        </td>
                        <td className="px-3 py-2.5 text-right font-semibold" style={{ color: colors.onSurface }}>
                          {fmtMoney(r.margin_cents)}
                        </td>
                        <td className="px-3 py-2.5 text-right">
                          <span
                            className="inline-block px-2 py-0.5 rounded font-bold text-xs"
                            style={{ background: tone.bg, color: tone.fg }}
                            data-testid={`margin-pct-${r.job_id}`}
                            data-tone={tone.label}
                          >
                            {Number(r.margin_pct || 0).toFixed(1)}%
                          </span>
                        </td>
                        <td className="px-3 py-2.5 text-right text-xs" style={{ color: colors.muted }}>
                          {r.service_date || "—"}
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
