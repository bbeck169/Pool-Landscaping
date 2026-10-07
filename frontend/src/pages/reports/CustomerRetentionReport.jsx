import React, { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  LineChart, Line,
} from "recharts";
import {
  ArrowLeft, Users, UserMinus, TrendingUp, Info, Download, RefreshCw,
  AlertTriangle, Zap, X as CloseX, Crown, DollarSign, ChevronUp, ChevronDown,
} from "lucide-react";
import { api } from "@/api";
import { colors } from '@/theme';

/**
 * Phase 34g · Customer Retention Report (web-only).
 * Consumes GET /api/reports/customer-retention.
 */
function Card({ children, className = "", testId, style }) {
  return (
    <div
      className={`rounded-2xl p-5 ${className}`}
      style={{
        backgroundColor: colors.surface,
        border: `1px solid ${colors.border}`,
        ...(style || {}),
      }}
      data-testid={testId}
    >
      {children}
    </div>
  );
}

function KpiTile({ label, value, sub, tone, testId, icon: Icon, onClick, clickable = false }) {
  const toneColor =
    tone === "good" ? "#16A34A" :
    tone === "bad"  ? "#DC2626" :
    colors.onSurface;
  // CUSTOMER-RETENTION-ACCOUNT-CORRECTION · Feb-2026 — clickable
  // tiles for Gained + Lost → open the drill-down modal.  When
  // ``clickable`` is true the whole Card becomes a button with
  // keyboard affordance (role="button", tabIndex=0, Enter/Space
  // handler).  Non-clickable tiles keep the original div render.
  const body = (
    <>
      <div className="flex items-center justify-between">
        <div className="text-xs font-semibold uppercase tracking-wider" style={{ color: colors.muted }}>
          {label}
        </div>
        {Icon ? <Icon size={16} style={{ color: colors.muted }} /> : null}
      </div>
      <div className="text-3xl font-bold mt-2" style={{ color: toneColor }}>{value}</div>
      {sub ? (
        <div className="text-xs mt-1" style={{ color: colors.muted }}>{sub}</div>
      ) : null}
    </>
  );
  if (clickable) {
    return (
      <Card
        testId={testId}
        style={{ cursor: "pointer" }}
      >
        <div
          role="button"
          tabIndex={0}
          onClick={onClick}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              onClick?.();
            }
          }}
          data-testid={testId ? `${testId}-click` : undefined}
        >
          {body}
        </div>
      </Card>
    );
  }
  return <Card testId={testId}>{body}</Card>;
}

const PERIODS = [
  { key: "week",  label: "Week"  },
  { key: "month", label: "Month" },
  { key: "year",  label: "Year"  },
];


// ═════════════════════════════════════════════════════════════════════
// CUSTOMER-RETENTION-ACCOUNT-CORRECTION · Feb-2026 — drill-down modal.
//
// One component for both Gained and Lost lists.  Server-side
// paginated (default 50, max 500 per G3).  Columns: Name, Date,
// MRR, Account Correction toggle.  Per-row toggle hits the same
// endpoint ``POST /customers/{cid}/account-correction`` the profile
// uses — on 200 we refetch the current page AND signal the parent
// to refetch the main report so the tiles recount.
//
// Pagination control: traditional page-N buttons (not infinite
// scroll) so Admin can jump far ahead on a 2K-row list without
// scroll-fatigue.  Keeps a11y simple + keyboard nav intact.
// ═════════════════════════════════════════════════════════════════════
function AccountCorrectionDrilldownModal({
  kind, period, start, end, onClose, onFlagToggled,
}) {
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [page, setPage] = useState(1);
  const [limit] = useState(50);
  const [loading, setLoading] = useState(true);
  const [sortBy, setSortBy] = useState("date");  // "name" | "date" | "mrr"
  const [sortDir, setSortDir] = useState("desc"); // "asc" | "desc"
  const [togglingId, setTogglingId] = useState(null);

  const fetchPage = (p) => {
    setLoading(true);
    const qs = new URLSearchParams({
      period, page: String(p), limit: String(limit),
    });
    if (start) qs.set("start", start);
    if (end)   qs.set("end", end);
    api.get(`/reports/customer-retention/${kind}-list?${qs.toString()}`)
      .then((r) => {
        setItems(r.items || []);
        setTotal(r.total || 0);
        setHasMore(!!r.has_more);
        setPage(r.page || p);
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => { fetchPage(1); }, [kind, period, start, end]); // eslint-disable-line react-hooks/exhaustive-deps -- fetchPage identity stable per-mount

  const sorted = useMemo(() => {
    const arr = [...items];
    arr.sort((a, b) => {
      const av = a[sortBy], bv = b[sortBy];
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      const cmp = typeof av === "number"
        ? av - bv
        : String(av).localeCompare(String(bv));
      return sortDir === "asc" ? cmp : -cmp;
    });
    return arr;
  }, [items, sortBy, sortDir]);

  const toggleSort = (col) => {
    if (sortBy === col) setSortDir((d) => d === "asc" ? "desc" : "asc");
    else { setSortBy(col); setSortDir(col === "name" ? "asc" : "desc"); }
  };

  const toggleRow = async (row) => {
    setTogglingId(row.customer_id);
    try {
      await api.post(`/customers/${row.customer_id}/account-correction`, {
        active: !row.account_correction,
        note: null,
      });
      // Optimistic: flip in-place so the user sees instant feedback.
      // The parent will refetch main totals; the modal's own list
      // reload is deferred to the next page nav (or close+reopen).
      setItems((xs) => xs.map((x) =>
        x.customer_id === row.customer_id
          ? { ...x, account_correction: !row.account_correction } : x,
      ));
      onFlagToggled?.();
    } catch { /* ignore — row stays as-is */ }
    finally { setTogglingId(null); }
  };

  const label = kind === "gained" ? "Gained customers" : "Lost customers";
  const SortIcon = ({ col }) =>
    sortBy !== col ? null
      : sortDir === "asc" ? <ChevronUp size={12} /> : <ChevronDown size={12} />;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: "rgba(0,0,0,0.55)" }}
      data-testid="retention-drilldown-modal"
      data-kind={kind}
    >
      <div
        className="w-full max-w-4xl rounded-2xl p-5 max-h-[85vh] flex flex-col"
        style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
      >
        <div className="flex items-start justify-between mb-3">
          <div>
            <div className="text-lg font-semibold" style={{ color: colors.onSurface }}>
              {label} <span style={{ color: colors.muted }}>({total.toLocaleString()})</span>
            </div>
            <div className="text-xs" style={{ color: colors.muted }}>
              {kind === "gained"
                ? "Customers created in the current period, excluding Account Corrections."
                : "Customers deactivated in the current period, excluding Account Corrections."}
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded hover:bg-white/5"
            data-testid="retention-drilldown-close-btn"
            aria-label="Close drill-down"
          >
            <CloseX size={18} style={{ color: colors.muted }} />
          </button>
        </div>

        <div className="overflow-auto flex-1" data-testid="retention-drilldown-table-wrap">
          <table className="w-full text-sm" data-testid="retention-drilldown-table">
            <thead>
              <tr style={{ borderBottom: `1px solid ${colors.border}` }}>
                <th
                  className="text-left py-2 px-2 cursor-pointer select-none"
                  onClick={() => toggleSort("name")}
                  data-testid="retention-drilldown-sort-name"
                >
                  <span className="inline-flex items-center gap-1">Name <SortIcon col="name" /></span>
                </th>
                <th
                  className="text-left py-2 px-2 cursor-pointer select-none"
                  onClick={() => toggleSort("date")}
                  data-testid="retention-drilldown-sort-date"
                >
                  <span className="inline-flex items-center gap-1">
                    {kind === "gained" ? "Added" : "Cancelled"} <SortIcon col="date" />
                  </span>
                </th>
                <th
                  className="text-right py-2 px-2 cursor-pointer select-none"
                  onClick={() => toggleSort("mrr")}
                  data-testid="retention-drilldown-sort-mrr"
                >
                  <span className="inline-flex items-center gap-1 justify-end w-full">MRR <SortIcon col="mrr" /></span>
                </th>
                <th className="text-right py-2 px-2">Action</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={4} className="py-4 text-center" style={{ color: colors.muted }}>Loading…</td></tr>
              ) : sorted.length === 0 ? (
                <tr><td colSpan={4} className="py-4 text-center" style={{ color: colors.muted }} data-testid="retention-drilldown-empty">No customers in this period.</td></tr>
              ) : sorted.map((row) => (
                <tr
                  key={row.customer_id}
                  data-testid={`retention-drilldown-row-${row.customer_id}`}
                  style={{ borderBottom: `1px solid ${colors.border}` }}
                >
                  <td className="py-2 px-2" data-testid={`retention-drilldown-row-${row.customer_id}-name`}>
                    {row.name}
                    {row.account_correction ? (
                      <span
                        className="ml-2 inline-flex items-center px-1.5 py-0.5 rounded-full text-[9px] font-semibold uppercase tracking-wider"
                        style={{ backgroundColor: "#F3F4F6", color: "#6B7280", border: "1px solid #D1D5DB" }}
                        data-testid={`retention-drilldown-row-${row.customer_id}-ac-pill`}
                      >
                        Account Correction
                      </span>
                    ) : null}
                  </td>
                  <td className="py-2 px-2" style={{ color: colors.muted }}>
                    {row.date ? String(row.date).slice(0, 10) : "—"}
                  </td>
                  <td className="py-2 px-2 text-right">
                    {row.mrr != null
                      ? `$${Number(row.mrr).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
                      : "—"}
                  </td>
                  <td className="py-2 px-2 text-right">
                    <button
                      onClick={() => toggleRow(row)}
                      disabled={togglingId === row.customer_id}
                      className="px-2 py-1 rounded border text-xs"
                      style={{
                        borderColor: colors.border,
                        color: colors.onSurface,
                        background: "transparent",
                        opacity: togglingId === row.customer_id ? 0.5 : 1,
                      }}
                      data-testid={`retention-drilldown-row-${row.customer_id}-toggle-btn`}
                    >
                      {row.account_correction ? "Un-flag" : "Mark correction"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {total > limit ? (
          <div className="flex items-center justify-between mt-3 text-xs" style={{ color: colors.muted }}>
            <span data-testid="retention-drilldown-page-info">
              Page {page} of {Math.ceil(total / limit)} — {total.toLocaleString()} total
            </span>
            <div className="flex gap-2">
              <button
                className="px-2 py-1 rounded border"
                disabled={page <= 1}
                onClick={() => fetchPage(page - 1)}
                data-testid="retention-drilldown-page-prev"
                style={{ borderColor: colors.border, opacity: page <= 1 ? 0.4 : 1 }}
              >Prev</button>
              <button
                className="px-2 py-1 rounded border"
                disabled={!hasMore}
                onClick={() => fetchPage(page + 1)}
                data-testid="retention-drilldown-page-next"
                style={{ borderColor: colors.border, opacity: !hasMore ? 0.4 : 1 }}
              >Next</button>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}


// Phase 39 · Algae-risk auto-flag panel. Data comes from
// GET /api/reports/algae-risk. "Schedule Shock" and "Dismiss" each
// resolve the flag; the row disappears optimistically so the office
// gets instant feedback and reloads happen in the background.
function AlgaeRiskPanel() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState({});   // per-customer action lock
  const [toast, setToast] = useState(null);

  const load = () => {
    setLoading(true);
    api.get("/reports/algae-risk")
      .then((r) => setRows(r?.items || []))
      .catch(() => setRows([]))
      .finally(() => setLoading(false));
  };
  useEffect(() => { load(); }, []);

  const act = async (customerId, kind) => {
    setBusy((b) => ({ ...b, [customerId]: kind }));
    const optimistic = rows.filter((r) => r.customer_id !== customerId);
    try {
      const path = kind === "shock"
        ? `/reports/algae-risk/${customerId}/schedule-shock`
        : `/reports/algae-risk/${customerId}/resolve`;
      const r = await api.post(path, {});
      setRows(optimistic);
      setToast({
        kind: "ok",
        text: kind === "shock"
          ? `Shock Treatment job scheduled (id ${String(r?.job_id || "").slice(0,8)}…). Flag resolved.`
          : `Flag dismissed for the selected customer.`,
      });
      setTimeout(() => setToast(null), 3200);
    } catch (e) {
      setToast({ kind: "err", text: e?.message || "Action failed." });
    } finally {
      setBusy((b) => { const n = { ...b }; delete n[customerId]; return n; });
    }
  };

  // Phase 39 hotfix — keep the panel mounted while a toast is pending so
  // the confirmation survives after the last flag is dismissed.
  if ((loading || rows.length === 0) && !toast) return null;
  if (rows.length === 0 && toast) {
    return (
      <div
        className="rounded-md p-3 mb-4 text-xs font-semibold"
        data-testid="algae-risk-toast"
        style={{
          background: toast.kind === "ok" ? "#D1FAE5" : "#FEE2E2",
          color: toast.kind === "ok" ? "#065F46" : "#B91C1C",
          border: "1px solid " + (toast.kind === "ok" ? "#10B981" : "#F87171"),
        }}
      >
        {toast.text}
      </div>
    );
  }

  return (
    <div
      className="rounded-2xl p-5 mb-4"
      data-testid="algae-risk-panel"
      style={{
        background: "#FEF3C7",
        border: `1px solid #F59E0B`,
      }}
    >
      <div className="flex items-center gap-2 mb-3">
        <AlertTriangle size={18} color="#B45309" />
        <div className="text-lg font-bold" style={{ color: "#B45309" }}>
          Algae Risk — {rows.length} customer{rows.length === 1 ? "" : "s"} flagged
        </div>
      </div>
      <div className="text-xs mb-3" style={{ color: "#B45309" }}>
        These customers' last two visits both showed free chlorine ≤ 0.5 ppm.
        Schedule a shock treatment now to protect the pool (and the account).
      </div>

      <div className="space-y-2">
        {rows.map((row) => {
          const cust = row.customer || {};
          const evi = row.evidence || [];
          const isBusy = !!busy[row.customer_id];
          return (
            <div
              key={row.id}
              data-testid={`algae-risk-row-${row.customer_id}`}
              className="flex flex-wrap items-center gap-3 p-3 rounded-lg"
              style={{ background: "#FFFBEB", border: "1px solid #FCD34D" }}
            >
              <div className="flex-1 min-w-[200px]">
                <div className="flex items-center gap-2">
                  {cust.is_vip
                    ? <Crown size={14} color="#B45309" />
                    : <Users size={14} color="#B45309" />}
                  <span className="text-sm font-bold" style={{ color: "#0F172A" }}>
                    {cust.name || "(unknown customer)"}
                  </span>
                </div>
                <div className="text-xs mt-1" style={{ color: "#6B7280" }}>
                  {cust.address || "—"}
                </div>
                <div className="flex flex-wrap gap-3 mt-1 text-[11px]" style={{ color: "#B45309" }}>
                  {evi.map((e, i) => (
                    <span key={i}>
                      Visit {i + 1}: <b>{e.chlorine ?? e.free_chlorine} ppm</b>{" "}
                      <span style={{ color: "#6B7280" }}>
                        ({String(e.date || "").slice(0, 10)})
                      </span>
                    </span>
                  ))}
                </div>
              </div>
              <button
                type="button"
                disabled={isBusy}
                onClick={() => act(row.customer_id, "shock")}
                data-testid={`algae-risk-schedule-shock-${row.customer_id}`}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-bold"
                style={{
                  background: "#059669", color: "#fff", border: 0,
                  cursor: isBusy ? "wait" : "pointer",
                  opacity: isBusy ? 0.6 : 1,
                }}
              >
                <Zap size={13} /> Schedule Shock
              </button>
              <button
                type="button"
                disabled={isBusy}
                onClick={() => act(row.customer_id, "dismiss")}
                data-testid={`algae-risk-dismiss-${row.customer_id}`}
                className="inline-flex items-center gap-1 px-2 py-1.5 rounded-md text-xs font-semibold"
                style={{
                  background: "transparent", color: "#6B7280",
                  border: `1px solid #E2E8F0`,
                  cursor: isBusy ? "wait" : "pointer",
                }}
              >
                <CloseX size={12} /> Dismiss
              </button>
            </div>
          );
        })}
      </div>
      {toast ? (
        <div
          className="mt-3 px-3 py-2 rounded-md text-xs font-semibold"
          style={{
            background: toast.kind === "ok" ? "#D1FAE5" : "#FEE2E2",
            color: toast.kind === "ok" ? "#065F46" : "#B91C1C",
          }}
          data-testid="algae-risk-toast"
        >
          {toast.text}
        </div>
      ) : null}
    </div>
  );
}

export default function CustomerRetentionReport() {
  const nav = useNavigate();
  const [period, setPeriod] = useState("month");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  // CUSTOMER-RETENTION-ACCOUNT-CORRECTION · Feb-2026 — drill-down
  // modal state.  ``drilldownKind`` is ``"gained" | "lost" | null``
  // so one modal component renders both lists off the same shell.
  const [drilldownKind, setDrilldownKind] = useState(null);

  const load = () => {
    setLoading(true);
    setError(null);
    const qs = new URLSearchParams({ period });
    if (start) qs.set("start", start);
    if (end)   qs.set("end",   end);
    api.get(`/reports/customer-retention?${qs.toString()}`)
      .then((r) => setData(r))
      .catch((e) => setError(e.message || "Failed to load"))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, [period]); // eslint-disable-line react-hooks/exhaustive-deps -- Phase 41.3 mount-only + explicit param deps

  const yoy = data?.yoy;
  const totals = data?.totals;
  const buckets = data?.buckets || []; // eslint-disable-line react-hooks/exhaustive-deps -- Phase 41.3: derived value stable-by-reference; downstream useMemo already tracks the real source deps

  const csv = useMemo(() => {
    const rows = [["label", "start", "end", "gained", "lost", "net"]];
    for (const b of buckets) rows.push([b.label, b.start, b.end, b.gained, b.lost, b.net]);
    return rows.map((r) => r.join(",")).join("\n");
  }, [buckets]); // eslint-disable-line react-hooks/exhaustive-deps -- Phase 41.3: memoized deps are stable by value; wrapping the source in its own useMemo would obscure the read

  const downloadCsv = () => {
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `customer-retention-${period}-${data?.start}-${data?.end}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const _netToneColor = totals && totals.net >= 0 ? "#16A34A" : "#DC2626";
  const yoyNetPct = yoy?.net_pct_change;

  return (
    <div className="max-w-7xl mx-auto p-6" data-testid="retention-report-page">
      {/* Phase 39 · Algae-risk auto-flag panel — surfaces the small set of
          customers whose last two chlorine readings both came in ≤ 0.5 ppm.
          Sits above the retention analytics so the office sees the urgent
          items first. */}
      <AlgaeRiskPanel />

      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <button
            className="inline-flex items-center gap-1 text-sm mb-2"
            onClick={() => nav("/reports")}
            style={{ color: colors.muted, background: "none", border: 0, cursor: "pointer" }}
          >
            <ArrowLeft size={14} /> Reports Hub
          </button>
          <h1 className="text-3xl font-bold" style={{ color: colors.onSurface }}>Customer Retention</h1>
          <div className="text-sm mt-1" style={{ color: colors.muted }}>
            Gained vs lost customers over time, with YoY comparison.
          </div>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-semibold"
          style={{ background: colors.brand, color: "#fff", border: 0, cursor: loading ? "wait" : "pointer" }}
          data-testid="retention-refresh"
        >
          <RefreshCw size={13} className={loading ? "animate-spin" : ""} /> Refresh
        </button>
      </div>

      {/* Period selector */}
      <div className="flex flex-wrap items-center gap-2 mb-4">
        <div className="inline-flex rounded-full p-1"
             style={{ background: colors.surfaceSecondary, border: `1px solid ${colors.border}` }}>
          {PERIODS.map((p) => (
            <button
              key={p.key}
              onClick={() => setPeriod(p.key)}
              className="px-3 py-1 rounded-full text-sm font-semibold"
              style={{
                background: period === p.key ? colors.brand : "transparent",
                color: period === p.key ? "#fff" : colors.onSurfaceSecondary,
                border: 0, cursor: "pointer",
              }}
              data-testid={`retention-period-${p.key}`}
            >
              {p.label}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2 text-xs" style={{ color: colors.muted }}>
          <label>from
            <input type="date" value={start} onChange={(e) => setStart(e.target.value)}
                   className="ml-1 px-2 py-1 rounded-md text-xs"
                   style={{ background: colors.surface, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                   data-testid="retention-start-input" />
          </label>
          <label>to
            <input type="date" value={end} onChange={(e) => setEnd(e.target.value)}
                   className="ml-1 px-2 py-1 rounded-md text-xs"
                   style={{ background: colors.surface, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                   data-testid="retention-end-input" />
          </label>
          <button onClick={load} className="px-2 py-1 rounded-md text-xs font-semibold"
                  style={{ background: colors.surface, border: `1px solid ${colors.border}`, color: colors.onSurface, cursor: "pointer" }}
                  data-testid="retention-apply-range">
            Apply
          </button>
        </div>
      </div>

      {yoy?.mocked ? (
        <div
          className="rounded-lg px-3 py-2 mb-4 text-sm inline-flex items-center gap-2"
          style={{ background: "#FEF3C7", color: "#92400E", border: "1px solid #F59E0B" }}
          data-testid="retention-yoy-mocked-note"
        >
          <Info size={14} /> YoY comparison unavailable — {yoy.reason || "insufficient history"}.
        </div>
      ) : null}

      {/* KPI tiles */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 mb-6">
        <KpiTile
          label="Gained"
          value={totals ? totals.gained.toLocaleString() : "—"}
          sub={yoy && !yoy.mocked && yoy.gained_pct_change !== null
            ? `${yoy.gained_pct_change >= 0 ? "+" : ""}${yoy.gained_pct_change}% YoY`
            : null}
          tone="good"
          icon={Users}
          testId="retention-kpi-gained"
          clickable
          onClick={() => setDrilldownKind("gained")}
        />
        <KpiTile
          label="Lost"
          value={totals ? totals.lost.toLocaleString() : "—"}
          sub={yoy && !yoy.mocked && yoy.lost_pct_change !== null
            ? `${yoy.lost_pct_change >= 0 ? "+" : ""}${yoy.lost_pct_change}% YoY`
            : null}
          tone="bad"
          icon={UserMinus}
          testId="retention-kpi-lost"
          clickable
          onClick={() => setDrilldownKind("lost")}
        />
        <KpiTile
          label="Net change"
          value={totals ? `${totals.net >= 0 ? "+" : ""}${totals.net.toLocaleString()}` : "—"}
          sub={period === "week" ? "Weekly total" : period === "year" ? "Annual total" : "Monthly total"}
          tone={totals && totals.net >= 0 ? "good" : "bad"}
          icon={TrendingUp}
          testId="retention-kpi-net"
        />
        {/* CUSTOMER-RETENTION-ACCOUNT-CORRECTION · Feb-2026 — new
            MRR tiles.  Sum each gained/lost customer's CURRENT
            billing_plans snapshot (dollar amount per month).  See
            inline docstring on ``_customer_mrr_from_plans`` in
            ``backend/routers/reports.py`` for the normalization
            semantics (weekly ×4.333 / monthly ×1 / quarterly ×1/3). */}
        <KpiTile
          label="Recurring revenue gained"
          value={totals && totals.recurring_revenue_gained != null
            ? `$${Number(totals.recurring_revenue_gained).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
            : "—"}
          sub="Current MRR snapshot"
          tone="good"
          icon={DollarSign}
          testId="retention-kpi-mrr-gained"
        />
        <KpiTile
          label="Recurring revenue lost"
          value={totals && totals.recurring_revenue_lost != null
            ? `$${Number(totals.recurring_revenue_lost).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
            : "—"}
          sub="Current MRR snapshot"
          tone="bad"
          icon={DollarSign}
          testId="retention-kpi-mrr-lost"
        />
        <KpiTile
          label="YoY net change"
          value={yoyNetPct == null ? "—" : `${yoyNetPct >= 0 ? "+" : ""}${yoyNetPct}%`}
          sub={yoy?.previous_totals
            ? `Prev period net: ${yoy.previous_totals.net >= 0 ? "+" : ""}${yoy.previous_totals.net}`
            : "No prior-year data"}
          tone={yoyNetPct == null ? undefined : (yoyNetPct >= 0 ? "good" : "bad")}
          icon={TrendingUp}
          testId="retention-kpi-yoy"
        />
      </div>

      {/* Bar chart */}
      <Card className="mb-4" testId="retention-bar-chart">
        <div className="text-sm font-semibold mb-3" style={{ color: colors.onSurface }}>
          Gained vs Lost per {period}
        </div>
        {buckets.length === 0 ? (
          <div className="text-sm py-8 text-center" style={{ color: colors.muted }}>
            No retention events yet in the selected period.
          </div>
        ) : (
          <div style={{ width: "100%", height: 260 }}>
            <ResponsiveContainer>
              <BarChart data={buckets}>
                <CartesianGrid strokeDasharray="3 3" stroke={colors.border} />
                <XAxis dataKey="label" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} />
                <Tooltip />
                <Legend />
                <Bar dataKey="gained" fill="#16A34A" name="Gained" />
                <Bar dataKey="lost"   fill="#DC2626" name="Lost" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </Card>

      {/* Line chart */}
      <Card className="mb-4" testId="retention-line-chart">
        <div className="text-sm font-semibold mb-3" style={{ color: colors.onSurface }}>
          Net change over time
        </div>
        {buckets.length === 0 ? (
          <div className="text-sm py-8 text-center" style={{ color: colors.muted }}>
            No net-change data.
          </div>
        ) : (
          <div style={{ width: "100%", height: 240 }}>
            <ResponsiveContainer>
              <LineChart data={buckets}>
                <CartesianGrid strokeDasharray="3 3" stroke={colors.border} />
                <XAxis dataKey="label" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} />
                <Tooltip />
                <Line type="monotone" dataKey="net" stroke={colors.brand} strokeWidth={2} dot={false} name="Net" />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </Card>

      {/* Table + CSV */}
      <Card>
        <div className="flex items-center justify-between mb-3">
          <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>
            Breakdown
          </div>
          <button
            onClick={downloadCsv}
            disabled={buckets.length === 0}
            className="inline-flex items-center gap-1 px-3 py-1.5 rounded-md text-xs font-semibold"
            style={{
              background: colors.surface,
              border: `1px solid ${colors.border}`,
              color: colors.onSurface,
              cursor: buckets.length === 0 ? "not-allowed" : "pointer",
              opacity: buckets.length === 0 ? 0.4 : 1,
            }}
            data-testid="retention-csv-export"
          >
            <Download size={13} /> Export CSV
          </button>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="retention-table">
            <thead>
              <tr style={{ color: colors.muted, borderBottom: `1px solid ${colors.border}` }}>
                <th className="text-left py-2 pr-3">Period</th>
                <th className="text-right py-2 pr-3">Gained</th>
                <th className="text-right py-2 pr-3">Lost</th>
                <th className="text-right py-2">Net</th>
              </tr>
            </thead>
            <tbody>
              {buckets.length === 0 ? (
                <tr><td colSpan={4} className="py-6 text-center" style={{ color: colors.muted }}>No data.</td></tr>
              ) : buckets.map((b) => (
                <tr key={b.label} data-testid="retention-table-row"
                    style={{ borderBottom: `1px solid ${colors.border}` }}>
                  <td className="py-2 pr-3" style={{ color: colors.onSurface }}>{b.label}</td>
                  <td className="py-2 pr-3 text-right" style={{ color: "#16A34A" }}>+{b.gained}</td>
                  <td className="py-2 pr-3 text-right" style={{ color: "#DC2626" }}>−{b.lost}</td>
                  <td className="py-2 text-right font-semibold"
                      style={{ color: b.net >= 0 ? "#16A34A" : "#DC2626" }}>
                    {b.net >= 0 ? "+" : ""}{b.net}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {error ? (
        <div className="mt-4 text-sm" style={{ color: "#DC2626" }} data-testid="retention-error">
          {error}
        </div>
      ) : null}

      {/* CUSTOMER-RETENTION-ACCOUNT-CORRECTION · Feb-2026 — drill-down modal */}
      {drilldownKind ? (
        <AccountCorrectionDrilldownModal
          kind={drilldownKind}
          period={period}
          start={start}
          end={end}
          onClose={() => setDrilldownKind(null)}
          onFlagToggled={load}
        />
      ) : null}
    </div>
  );
}
