/**
 * Phase G5d · Feb-2026 — Driver Scorecard / Leaderboard page.
 */
import React from "react";
import { toast } from "sonner";
import { RefreshCw, Download, ExternalLink, X, TrendingUp } from "lucide-react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts";
import { api } from "@/api";
import { TOKEN_KEY, api_base } from "@/api";

const RANGE_OPTIONS = [
  { value: "this_week",     label: "This Week"    },
  { value: "last_week",     label: "Last Week"    },
  { value: "month_to_date", label: "Month to Date"},
  { value: "custom",        label: "Custom"       },
];

function _todayIso() {
  return new Date().toISOString().slice(0, 10);
}
function _sevenDaysAgoIso() {
  const d = new Date();
  d.setDate(d.getDate() - 7);
  return d.toISOString().slice(0, 10);
}

function _fmtMinutes(sec) {
  const s = Math.max(0, Math.round(sec || 0));
  const m = Math.round(s / 60);
  return `${m}m`;
}

function ScoreBadge({ score, testId }) {
  const c = score >= 80 ? { bg: "#DCFCE7", fg: "#065F46" }
          : score >= 60 ? { bg: "#FEF3C7", fg: "#92400E" }
          :               { bg: "#FEE2E2", fg: "#991B1B" };
  return (
    <span
      className="inline-block rounded-full px-2 py-0.5 text-xs font-semibold"
      style={{ background: c.bg, color: c.fg }}
      data-testid={testId}
    >
      {score}
    </span>
  );
}

function ScoreGauge({ score }) {
  const c = score >= 80 ? "#059669" : score >= 60 ? "#D97706" : "#DC2626";
  const _dash = `${score} ${100 - score}`;
  return (
    <div className="flex items-center justify-center"
         data-testid="scorecard-gauge">
      <svg width="180" height="120" viewBox="0 0 180 120">
        <circle cx="90" cy="90" r="70" fill="none" stroke="#F1F5F9"
                strokeWidth="14" strokeDasharray="220 440"
                transform="rotate(-90 90 90)" />
        <circle cx="90" cy="90" r="70" fill="none" stroke={c}
                strokeWidth="14"
                strokeDasharray={`${(score / 100) * 220} 440`}
                strokeLinecap="round"
                transform="rotate(-90 90 90)" />
        <text x="90" y="88" textAnchor="middle" fontSize="34"
              fontWeight="700" fill="#111">{score}</text>
        <text x="90" y="108" textAnchor="middle" fontSize="10"
              fill="#94A3B8">out of 100</text>
      </svg>
    </div>
  );
}

function DetailDrawer({ userId, range, onClose }) {
  const [detail, setDetail] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  React.useEffect(() => {
    if (!userId) return;
    setLoading(true);
    api.get(`/admin/gps/scorecard/user/${userId}?range=${range}`)
      .then(setDetail)
      .catch((e) => toast.error("Load failed", { description: e?.message }))
      .finally(() => setLoading(false));
  }, [userId, range]);
  if (!userId) return null;
  const row = detail?.row;
  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-end sm:items-center justify-center p-4"
         data-testid="scorecard-detail-drawer" onClick={onClose}>
      <div className="bg-white rounded-lg shadow-xl max-w-xl w-full p-6"
           onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-lg font-semibold"
              data-testid="scorecard-detail-name">
            {row?.user_name || "Technician"}
          </h3>
          <button type="button" onClick={onClose} aria-label="Close"
                  data-testid="scorecard-detail-close"><X size={18} /></button>
        </div>
        {loading || !row ? (
          <div className="text-sm text-zinc-500">Loading…</div>
        ) : (
          <>
            <ScoreGauge score={row.score} />
            <div className="mt-4 mb-2 flex items-center gap-1 text-xs text-zinc-600">
              <TrendingUp size={12} /> Last 8 weeks
            </div>
            <div style={{ width: "100%", height: 140 }}
                 data-testid="scorecard-trend-chart">
              <ResponsiveContainer>
                <LineChart data={detail.trend || []}>
                  <CartesianGrid stroke="#E2E8F0" strokeDasharray="3 3" />
                  <XAxis dataKey="week_start" tick={{ fontSize: 10 }}
                          tickFormatter={(d) => (d || "").slice(5, 10)} />
                  <YAxis domain={[0, 100]} tick={{ fontSize: 10 }} />
                  <Tooltip formatter={(v) => `${v}`} />
                  <Line type="monotone" dataKey="score" stroke="#0EA5E9"
                        strokeWidth={2} dot={{ r: 3 }} />
                </LineChart>
              </ResponsiveContainer>
            </div>
            <table className="mt-4 w-full text-sm"
                    data-testid="scorecard-detail-metrics">
              <tbody className="divide-y divide-zinc-100">
                {[
                  ["Stops", row.metrics.stops_count],
                  ["Avg stop (min)", Math.round((row.metrics.avg_stop_duration_s || 0) / 60)],
                  ["Total stopped (min)", Math.round((row.metrics.total_stopped_time_s || 0) / 60)],
                  ["Total driving (min)", Math.round((row.metrics.total_driving_time_s || 0) / 60)],
                  ["Unique jobs", row.metrics.unique_jobs_attributed],
                  ["Unique customers", row.metrics.unique_customers_attributed],
                  ["On-time %", row.metrics.on_time_arrival_rate == null
                    ? "—" : `${Math.round(row.metrics.on_time_arrival_rate * 100)}%`],
                  ["Estimated miles", row.metrics.estimated_miles],
                  ["Days active", row.metrics.days_active],
                  ["Attribution coverage",
                    `${Math.round((row.metrics.attribution_coverage || 0) * 100)}%`],
                  ["Idle penalty", row.metrics.idle_penalty],
                ].map(([k, v]) => (
                  <tr key={k}>
                    <td className="py-1 text-zinc-500">{k}</td>
                    <td className="py-1 text-right font-mono">{v}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="pt-4">
              <a href={`/admin/reports/driver-activity?user_id=${row.user_id}`}
                 className="inline-flex items-center gap-1 text-sky-600 hover:underline text-sm"
                 data-testid="scorecard-detail-view-activity">
                <ExternalLink size={12} /> View driver activity for this tech
              </a>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export default function DriverScorecardPage() {
  const [range, setRange] = React.useState("this_week");
  const [department, setDepartment] = React.useState("");
  // G5d polish · Feb-2026 — Custom range state (dates in YYYY-MM-DD).
  const [customFrom, setCustomFrom] = React.useState(_sevenDaysAgoIso);
  const [customTo, setCustomTo] = React.useState(_todayIso);
  const [board, setBoard] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [forbidden, setForbidden] = React.useState(false);
  const [drawerUid, setDrawerUid] = React.useState(null);

  const customInvalid = range === "custom"
    && customFrom && customTo && customFrom > customTo;

  const load = React.useCallback(async () => {
    if (range === "custom") {
      if (!customFrom || !customTo || customFrom > customTo) {
        // Skip request when the range is invalid — inline error tells why.
        return;
      }
    }
    setLoading(true);
    try {
      const qs = new URLSearchParams({ range });
      if (department) qs.set("department", department);
      if (range === "custom") {
        qs.set("from", `${customFrom}T00:00:00Z`);
        qs.set("to",   `${customTo}T23:59:59Z`);
      }
      const r = await api.get(`/admin/gps/scorecard/leaderboard?${qs}`);
      setBoard(r); setForbidden(false);
    } catch (e) {
      if ((e?.message || "").includes("403")) setForbidden(true);
      else toast.error("Load failed", { description: e?.message });
    } finally { setLoading(false); }
  }, [range, department, customFrom, customTo]);

  React.useEffect(() => { load(); }, [load]);

  const exportCsv = () => {
    if (range === "custom" && (!customFrom || !customTo
                                || customFrom > customTo)) {
      toast.error("Fix the custom date range first");
      return;
    }
    const qs = new URLSearchParams({ range });
    if (department) qs.set("department", department);
    if (range === "custom") {
      qs.set("from", `${customFrom}T00:00:00Z`);
      qs.set("to",   `${customTo}T23:59:59Z`);
    }
    const token = localStorage.getItem(TOKEN_KEY) || "";
    // Trigger download via fetch (needs auth header — can't use plain <a>).
    fetch(`${api_base()}/admin/gps/scorecard/export.csv?${qs}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((r) => r.blob())
      .then((blob) => {
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `driver_scorecard_${range}.csv`;
        document.body.appendChild(a); a.click(); a.remove();
        URL.revokeObjectURL(url);
      })
      .catch((e) => toast.error("Export failed", { description: e?.message }));
  };

  if (forbidden) {
    return (
      <div className="p-6" data-testid="scorecard-forbidden">
        <h1 className="text-2xl font-semibold text-zinc-900">Access denied</h1>
        <p className="text-sm text-zinc-500 mt-2">
          You don't have permission to view the driver scorecard.
        </p>
      </div>
    );
  }

  const rows = board?.rows || [];
  const departments = Array.from(new Set(rows.map((r) => r.department)
                                            .filter(Boolean))).sort();

  return (
    <div className="p-6 space-y-4" data-testid="scorecard-page">
      <header className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-zinc-900"
              data-testid="scorecard-title">Driver Scorecard</h1>
          <p className="text-sm text-zinc-500 mt-1">
            Composite ranking derived from stops, pings, and job
            attribution. Score 80+ green · 60-79 yellow · &lt;60 red.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select value={range} onChange={(e) => setRange(e.target.value)}
            className="px-3 py-1.5 border border-zinc-200 rounded text-sm"
            data-testid="scorecard-range">
            {RANGE_OPTIONS.map((o) =>
              <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
          {range === "custom" && (
            <div className="flex items-center gap-1"
                 data-testid="scorecard-custom-range">
              <input type="date" value={customFrom}
                onChange={(e) => setCustomFrom(e.target.value)}
                className="px-2 py-1.5 border border-zinc-200 rounded text-sm"
                data-testid="scorecard-custom-from" />
              <span className="text-xs text-zinc-500">→</span>
              <input type="date" value={customTo}
                onChange={(e) => setCustomTo(e.target.value)}
                className="px-2 py-1.5 border border-zinc-200 rounded text-sm"
                data-testid="scorecard-custom-to" />
            </div>
          )}
          <select value={department}
            onChange={(e) => setDepartment(e.target.value)}
            className="px-3 py-1.5 border border-zinc-200 rounded text-sm"
            data-testid="scorecard-department">
            <option value="">All departments</option>
            {departments.map((d) => <option key={d} value={d}>{d}</option>)}
          </select>
          <button type="button" onClick={load}
            className="inline-flex items-center gap-1 px-3 py-1.5 border border-zinc-200 rounded text-sm hover:bg-zinc-50"
            data-testid="scorecard-refresh">
            <RefreshCw size={14} /> Refresh
          </button>
          <button type="button" onClick={exportCsv}
            className="inline-flex items-center gap-1 px-3 py-1.5 rounded bg-sky-600 text-white text-sm"
            data-testid="scorecard-export">
            <Download size={14} /> Export CSV
          </button>
        </div>
      </header>

      {customInvalid && (
        <div className="rounded-md px-3 py-2 text-sm"
             style={{ background: "#FEE2E2", color: "#991B1B" }}
             data-testid="scorecard-custom-error">
          The <strong>from</strong> date must be on or before the {" "}
          <strong>to</strong> date.
        </div>
      )}

      <div className="bg-white border border-zinc-200 rounded-lg shadow-sm overflow-hidden"
           data-testid="scorecard-table">
        {loading ? (
          <div className="p-6 text-sm text-zinc-500">Loading…</div>
        ) : rows.length === 0 ? (
          <div className="p-6 text-sm text-zinc-500"
               data-testid="scorecard-empty">
            No technicians match this range / department.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-zinc-50 text-zinc-500 text-xs">
              <tr>
                <th className="text-left px-4 py-2">Rank</th>
                <th className="text-left px-4 py-2">Tech</th>
                <th className="text-left px-4 py-2">Dept</th>
                <th className="text-left px-4 py-2">Score</th>
                <th className="text-right px-4 py-2">Stops</th>
                <th className="text-right px-4 py-2">Avg stop min</th>
                <th className="text-right px-4 py-2">Jobs</th>
                <th className="text-right px-4 py-2">Customers</th>
                <th className="text-right px-4 py-2">On-time %</th>
                <th className="text-right px-4 py-2">Miles</th>
                <th className="text-right px-4 py-2">Days</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.user_id}
                    onClick={() => setDrawerUid(r.user_id)}
                    className="border-t border-zinc-100 hover:bg-zinc-50 cursor-pointer"
                    data-testid={`scorecard-row-${r.user_id}`}>
                  <td className="px-4 py-2 font-mono">{r.rank}</td>
                  <td className="px-4 py-2 font-medium">{r.user_name}</td>
                  <td className="px-4 py-2 text-xs text-zinc-500">
                    {r.department || "—"}
                  </td>
                  <td className="px-4 py-2">
                    <ScoreBadge score={r.score}
                      testId={`scorecard-score-${r.user_id}`} />
                  </td>
                  <td className="px-4 py-2 text-right">{r.metrics.stops_count}</td>
                  <td className="px-4 py-2 text-right">
                    {Math.round((r.metrics.avg_stop_duration_s || 0) / 60)}
                  </td>
                  <td className="px-4 py-2 text-right">
                    {r.metrics.unique_jobs_attributed}
                  </td>
                  <td className="px-4 py-2 text-right">
                    {r.metrics.unique_customers_attributed}
                  </td>
                  <td className="px-4 py-2 text-right">
                    {r.metrics.on_time_arrival_rate == null
                      ? "—"
                      : `${Math.round(r.metrics.on_time_arrival_rate * 100)}%`}
                  </td>
                  <td className="px-4 py-2 text-right font-mono">
                    {r.metrics.estimated_miles}
                  </td>
                  <td className="px-4 py-2 text-right">{r.metrics.days_active}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {drawerUid && (
        <DetailDrawer userId={drawerUid} range={range}
          onClose={() => setDrawerUid(null)} />
      )}
    </div>
  );
}
