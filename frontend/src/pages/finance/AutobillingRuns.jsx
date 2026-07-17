/**
 * Phase 56.17-followup — Autobilling Runs Audit UI.
 *
 * Admin-only surface at /admin/autobilling-runs. Consumes the
 * `GET /api/autobilling-runs?plan_id=&status=&since=` endpoint that
 * shipped in 56.17.
 *
 * Columns: plan name, schedule (human-readable), anchor date,
 * status (colored pill), message, timestamp. Filters: plan
 * dropdown, status multi-select, and a "since" date. Sortable by
 * every column. CSV export via client-side blob (same pattern as
 * the training leaderboard export in AdminTraining.jsx).
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, Download, Repeat } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import { PageHeader } from "@/components/ui-kit";

const SCHEDULE_LABELS = {
  first_friday: "1st Friday of the month",
  second_friday: "2nd Friday of the month",
  third_friday: "3rd Friday of the month",
  fourth_friday: "4th Friday of the month",
  first_of_month: "1st of the month",
};

const STATUS_STYLES = {
  fired: { bg: "#DCFCE7", fg: "#166534", label: "Fired" },
  manual: { bg: "#DBEAFE", fg: "#1E40AF", label: "Manual" },
  skipped: { bg: "#F1F5F9", fg: "#475569", label: "Skipped" },
  error: { bg: "#FEE2E2", fg: "#991B1B", label: "Error" },
  late_missed: { bg: "#FEF3C7", fg: "#92400E", label: "Late missed" },
};

function fmtTs(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString(undefined, {
      year: "numeric", month: "short", day: "numeric",
      hour: "2-digit", minute: "2-digit",
    });
  } catch { return String(iso); }
}

function StatusPill({ status }) {
  const s = STATUS_STYLES[status] || { bg: "#F1F5F9", fg: "#475569", label: status || "—" };
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wide"
      style={{ backgroundColor: s.bg, color: s.fg }}
      data-testid={`autobilling-runs-status-${status}`}
    >
      {s.label}
    </span>
  );
}

export default function AutobillingRuns() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [planFilter, setPlanFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState(""); // "" = all
  const [since, setSince] = useState("");
  const [sort, setSort] = useState({ key: "ts", dir: "desc" });

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const qs = new URLSearchParams();
      if (planFilter) qs.set("plan_id", planFilter);
      if (statusFilter) qs.set("status", statusFilter);
      if (since) qs.set("since", since);
      const r = await api.get(`/autobilling-runs${qs.toString() ? `?${qs}` : ""}`);
      setRows(Array.isArray(r) ? r : []);
    } catch (e) {
      setError(e?.message || "Failed to load audit log.");
    } finally {
      setLoading(false);
    }
  }, [planFilter, statusFilter, since]);

  useEffect(() => { load(); }, [load]);

  const planOptions = useMemo(() => {
    const seen = new Map();
    for (const r of rows) {
      if (r.plan_id && !seen.has(r.plan_id)) {
        seen.set(r.plan_id, r.plan_name || r.plan_id);
      }
    }
    return Array.from(seen, ([id, label]) => ({ id, label }));
  }, [rows]);

  const sorted = useMemo(() => {
    const s = [...rows];
    s.sort((a, b) => {
      const av = a[sort.key];
      const bv = b[sort.key];
      const an = av == null ? "" : String(av).toLowerCase();
      const bn = bv == null ? "" : String(bv).toLowerCase();
      if (an < bn) return sort.dir === "asc" ? -1 : 1;
      if (an > bn) return sort.dir === "asc" ? 1 : -1;
      return 0;
    });
    return s;
  }, [rows, sort]);

  const bump = (key) => setSort((s) =>
    s.key === key ? { key, dir: s.dir === "asc" ? "desc" : "asc" } : { key, dir: "desc" }
  );

  const exportCsv = () => {
    const header = ["Timestamp", "Plan", "Schedule", "Anchor date", "Current month", "Status", "Message", "Invoice"];
    const body = sorted.map((r) => [
      r.ts, r.plan_name || r.plan_id || "",
      SCHEDULE_LABELS[r.run_schedule] || r.run_schedule || "",
      r.anchor_date || "", r.current_month || "", r.status || "",
      r.message || "", r.invoice_id || "",
    ]);
    const esc = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
    const csv = [header, ...body].map((row) => row.map(esc).join(",")).join("\r\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `autobilling-runs-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1500);
  };

  const COLS = [
    { k: "ts", label: "Timestamp" },
    { k: "plan_name", label: "Plan" },
    { k: "run_schedule", label: "Schedule" },
    { k: "anchor_date", label: "Anchor" },
    { k: "status", label: "Status" },
    { k: "message", label: "Message" },
  ];

  return (
    <div className="max-w-6xl mx-auto py-6 px-4 space-y-4" data-testid="autobilling-runs-page">
      <Link to="/auto-billing" className="inline-flex items-center gap-1 text-xs font-bold"
            style={{ color: colors.brand, textDecoration: "none" }}>
        <ArrowLeft size={12} /> Auto-billing
      </Link>

      <PageHeader
        icon={Repeat}
        title="Autobilling runs"
        subtitle="Audit log of every billing plan fire attempt — scheduled, manual, skipped, error, and late-missed. Rows are tenant-scoped."
      />

      {/* Filters */}
      <div className="flex flex-wrap gap-3 items-end">
        <div>
          <div className="text-[10px] uppercase font-bold mb-1"
               style={{ color: colors.muted, letterSpacing: 0.4 }}>Plan</div>
          <select
            value={planFilter}
            onChange={(e) => setPlanFilter(e.target.value)}
            className="text-sm px-2 py-2 rounded-md min-w-[180px]"
            style={{ border: `1px solid ${colors.border}` }}
            data-testid="autobilling-runs-filter-plan"
          >
            <option value="">All plans</option>
            {planOptions.map((p) => (
              <option key={p.id} value={p.id}>{p.label}</option>
            ))}
          </select>
        </div>

        <div>
          <div className="text-[10px] uppercase font-bold mb-1"
               style={{ color: colors.muted, letterSpacing: 0.4 }}>Status</div>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="text-sm px-2 py-2 rounded-md min-w-[140px]"
            style={{ border: `1px solid ${colors.border}` }}
            data-testid="autobilling-runs-filter-status"
          >
            <option value="">All statuses</option>
            {Object.keys(STATUS_STYLES).map((s) => (
              <option key={s} value={s}>{STATUS_STYLES[s].label}</option>
            ))}
          </select>
        </div>

        <div>
          <div className="text-[10px] uppercase font-bold mb-1"
               style={{ color: colors.muted, letterSpacing: 0.4 }}>Since</div>
          <input
            type="date"
            value={since}
            onChange={(e) => setSince(e.target.value)}
            className="text-sm px-2 py-2 rounded-md"
            style={{ border: `1px solid ${colors.border}` }}
            data-testid="autobilling-runs-filter-since"
          />
        </div>

        <div className="flex-1" />

        <button
          type="button"
          onClick={exportCsv}
          disabled={sorted.length === 0}
          className="inline-flex items-center gap-1 text-xs font-bold px-3 py-2 rounded-md"
          style={{ background: colors.brand, color: "#fff", border: 0,
                   opacity: sorted.length === 0 ? 0.5 : 1,
                   cursor: sorted.length === 0 ? "not-allowed" : "pointer" }}
          data-testid="autobilling-runs-csv-export"
        >
          <Download size={12} /> Export CSV
        </button>
      </div>

      {loading ? (
        <div className="text-sm" style={{ color: colors.muted }}>Loading…</div>
      ) : error ? (
        <div className="text-sm" style={{ color: "#DC2626" }}
             data-testid="autobilling-runs-error">{error}</div>
      ) : (
        <div
          className="rounded-lg overflow-hidden"
          style={{ background: "#fff", border: `1px solid ${colors.border}` }}
        >
          <table className="w-full text-xs" data-testid="autobilling-runs-table">
            <thead style={{ background: colors.surfaceAlt }}>
              <tr>
                {COLS.map((c) => (
                  <th
                    key={c.k}
                    className="text-left px-3 py-2 cursor-pointer select-none"
                    style={{ color: colors.muted }}
                    onClick={() => bump(c.k)}
                    data-testid={`autobilling-runs-col-${c.k}`}
                  >
                    {c.label}
                    {sort.key === c.k ? (sort.dir === "asc" ? " ↑" : " ↓") : ""}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sorted.length === 0 ? (
                <tr>
                  <td colSpan={COLS.length} className="px-3 py-6 text-center"
                      style={{ color: colors.muted }}
                      data-testid="autobilling-runs-empty">
                    No autobilling runs yet. Runs appear here when the daily
                    scheduler fires a plan or an admin uses "Run now".
                  </td>
                </tr>
              ) : sorted.map((r) => (
                <tr key={r.id} data-testid={`autobilling-runs-row-${r.id}`}>
                  <td className="px-3 py-2" style={{ color: colors.onSurface }}>{fmtTs(r.ts)}</td>
                  <td className="px-3 py-2 font-bold" style={{ color: colors.onSurface }}>
                    {r.plan_name || r.plan_id || "—"}
                  </td>
                  <td className="px-3 py-2" style={{ color: colors.muted }}>
                    {SCHEDULE_LABELS[r.run_schedule] || r.run_schedule || "—"}
                  </td>
                  <td className="px-3 py-2" style={{ color: colors.muted }}>{r.anchor_date || "—"}</td>
                  <td className="px-3 py-2"><StatusPill status={r.status} /></td>
                  <td className="px-3 py-2" style={{ color: colors.muted }}>{r.message || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
