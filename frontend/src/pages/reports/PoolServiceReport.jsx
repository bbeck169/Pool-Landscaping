/**
 * Phase 46.4 · POOL-B — Pool Service Report (Admin).
 *
 * Table view of per-tech pools serviced / repairs completed / skipped
 * for a chosen week.  Wires to
 * `GET /api/reports/pool-service?date_from=...&date_to=...`.
 *
 * POOL-B (Feb-2026) — reads the new response shape:
 *   - ``summary.maintenance_visits``  → total pools serviced
 *   - ``summary.repair_visits``       → total repairs completed
 *   - ``summary.other_visits``        → completed jobs w/ unknown
 *                                       ``work_class`` (defensive)
 *   - ``by_technician[]``             → per-tech split rows with
 *     ``pools_serviced``, ``repairs_completed``, ``other``, ``skipped``.
 *
 * Landscape jobs are filtered at the backend (POOL-A) via
 * ``derive_industry_for_job(job, tenant, strict_mode=True) == "pool"``
 * — no client-side filter needed.
 *
 * Admin + super_admin only (backend also enforces).
 * CSV export runs client-side against the fetched rows so it always
 * matches what the admin is looking at.
 */
import React, { useEffect, useMemo, useState } from "react";
import { Waves, Download, ChevronDown, ChevronUp, RefreshCw } from "lucide-react";
import { api } from "@/api";
import { useAuth } from "@/auth";
import { colors } from "@/theme";

function mondayOf(dateStr) {
  const d = new Date(dateStr + "T00:00:00");
  const day = d.getDay(); // 0=Sun, 1=Mon…
  const diff = (day + 6) % 7; // days since Monday
  d.setDate(d.getDate() - diff);
  return d.toISOString().slice(0, 10);
}

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

function toCsv(rows) {
  const header = [
    "Tech Name", "Pools Serviced", "Repairs Completed",
    "Other", "Skipped", "Total Assigned",
  ];
  const body = rows.map((r) => [
    r.technician_name,
    r.pools_serviced,
    r.repairs_completed,
    r.other,
    r.skipped,
    (r.pools_serviced || 0) + (r.repairs_completed || 0)
      + (r.other || 0) + (r.skipped || 0),
  ]);
  return [header, ...body]
    .map((line) => line.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(","))
    .join("\n");
}

/**
 * Single shared tech-row renderer — one implementation used by both
 * the Maintenance and Repairs tables so the row markup is never
 * duplicated (brief rule §"Both sections share the same row-shape
 * renderer").  ``variant`` picks which counter to render bold in
 * the middle column + which data-testid suffix to stamp.
 */
function TechRow({ row, variant }) {
  const isRepair = variant === "repairs";
  const primary = isRepair ? row.repairs_completed : row.pools_serviced;
  const primaryTestId = isRepair
    ? `pool-report-tech-row-${row.technician_id || "unassigned"}-repairs`
    : `pool-report-tech-row-${row.technician_id || "unassigned"}-serviced`;
  return (
    <tr
      key={row.technician_id || row.technician_name}
      data-testid={`pool-service-row-${row.technician_id || "unassigned"}-${variant}`}
      style={{ borderBottom: `1px solid ${colors.border}` }}
    >
      <td className="px-4 py-2.5 font-semibold" style={{ color: colors.onSurface }}>
        {row.technician_name}
      </td>
      <td
        className="px-4 py-2.5 text-right font-semibold"
        style={{ color: colors.onSurface }}
        data-testid={primaryTestId}
      >
        {primary || 0}
      </td>
      <td
        className="px-4 py-2.5 text-right"
        style={{ color: (row.skipped || 0) > 0 ? "#B45309" : colors.onSurface }}
      >
        {row.skipped || 0}
      </td>
    </tr>
  );
}

function SectionEmpty({ label, testid }) {
  return (
    <tr>
      <td
        colSpan={3}
        className="px-4 py-8 text-center text-sm"
        style={{ color: colors.muted }}
        data-testid={testid}
      >
        {label}
      </td>
    </tr>
  );
}

export default function PoolServiceReport() {
  // Null-safe destructure — ``useAuth`` returns null when the
  // component renders without an ``AuthProvider`` wrapper (unit
  // tests that don't need to exercise role gating). Production
  // always has the provider, so this never degrades real UX.
  const auth = useAuth() || {};
  const role = auth.user?.role || "";
  const isAdmin = role === "admin" || role === "super_admin";
  const [week, setWeek] = useState(() => mondayOf(todayIso()));
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [history, setHistory] = useState([]);

  const load = async (ws) => {
    setLoading(true);
    setError(null);
    try {
      // POOL-B · Feb-2026 — response now includes ``summary`` (four
      // counts) + ``maintenance`` / ``repairs`` / ``other`` arrays of
      // tech rows.  Legacy ``rows`` still present for fallback.
      const start = new Date(ws + "T00:00:00");
      const end = new Date(start);
      end.setDate(end.getDate() + 6);
      const df = start.toISOString().slice(0, 10);
      const dt = end.toISOString().slice(0, 10);
      const res = await api.get(`/reports/pool-service?date_from=${df}&date_to=${dt}`);
      setData(res);
    } catch (e) {
      setError(e.message || "Failed to load");
      setData(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load(week);
  }, [week]);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const res = await api.get("/reports/pool-service/email-history?limit=10");
        if (alive) setHistory(res?.items || []);
      } catch { /* silent — history panel just stays empty */ }
    })();
    return () => { alive = false; };
  }, [week]);

  const maintenance = useMemo(
    () => data?.maintenance || [], [data],
  );
  const repairs = useMemo(
    () => data?.repairs || [], [data],
  );
  const summary = data?.summary || {
    maintenance_visits: 0,
    repair_visits: 0,
    other_visits: 0,
    total_pool_visits: 0,
  };
  const totalMaintenance = summary.maintenance_visits || 0;
  const totalRepairs = summary.repair_visits || 0;
  const totalOther = summary.other_visits || 0;
  const totalAll = totalMaintenance + totalRepairs + totalOther;
  // Feb-2026 · Inclusive-count fix — primary "Completed Jobs" count
  // reads the backend-authoritative ``total_completed_all`` so the
  // header number never silently diverges from the chip breakdown.
  // Falls back to the summed chips when an older backend response
  // omits the new field (defensive during rollout).
  const totalCompletedAll =
    typeof data?.total_completed_all === "number"
      ? data.total_completed_all
      : totalAll;
  // ``dropped_count`` is populated by the new backend field. Older
  // payloads treat it as 0 (nothing dropped) so the info line only
  // renders when the current backend is deployed AND something was
  // actually dropped.
  const droppedCount = typeof data?.dropped_count === "number"
    ? data.dropped_count
    : 0;

  const downloadCsv = () => {
    // Union of maintenance + repairs, deduped by technician_id so a
    // tech with both counts appears once.  Falls back to
    // ``by_technician`` when either array is missing.
    const byId = new Map();
    (data?.by_technician || []).forEach((r) =>
      byId.set(r.technician_id || `unassigned:${r.technician_name}`, r),
    );
    const rows = Array.from(byId.values());
    const csv = toCsv(rows);
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `pool-service-report_${data?.week_start || week}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="p-4 md:p-8 max-w-6xl mx-auto" data-testid="pool-service-report">
      <div className="flex items-start md:items-center flex-col md:flex-row md:justify-between gap-3 mb-6">
        <div className="flex items-center gap-3">
          <div
            className="w-11 h-11 rounded-xl flex items-center justify-center"
            style={{ backgroundColor: colors.brandTertiary, color: colors.onBrandTertiary }}
          >
            <Waves size={20} />
          </div>
          <div>
            <h1 className="text-2xl md:text-3xl font-bold" style={{ color: colors.onSurface }}>
              Pool Service Report
            </h1>
            <p className="text-sm mt-0.5" style={{ color: colors.muted }}>
              Per-tech counts of pools serviced vs repairs vs skipped for the selected week.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <label className="text-xs font-semibold" style={{ color: colors.muted }}>
            Week starting
          </label>
          <input
            type="date"
            value={week}
            onChange={(e) => setWeek(mondayOf(e.target.value))}
            className="text-sm px-2 py-1.5 rounded-md"
            style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
            data-testid="pool-service-week-picker"
          />
          <button
            type="button"
            onClick={() => load(week)}
            className="inline-flex items-center gap-1 text-xs font-semibold px-2 py-1.5 rounded-md"
            style={{ border: `1px solid ${colors.border}`, color: colors.onSurface, background: colors.surface }}
            data-testid="pool-service-refresh"
          >
            <RefreshCw size={12} /> Refresh
          </button>
          <button
            type="button"
            onClick={downloadCsv}
            disabled={totalAll === 0}
            className="inline-flex items-center gap-1 text-xs font-bold px-3 py-1.5 rounded-md"
            style={{
              background: totalAll > 0 ? colors.brand : colors.surfaceSecondary,
              color: totalAll > 0 ? "#fff" : colors.muted,
              border: `1px solid ${totalAll > 0 ? colors.brand : colors.border}`,
            }}
            data-testid="pool-service-csv"
          >
            <Download size={12} /> Export CSV
          </button>
        </div>
      </div>

      {loading ? (
        <div
          className="rounded-2xl p-8 text-center text-sm"
          style={{ background: colors.surface, border: `1px solid ${colors.border}`, color: colors.muted }}
        >
          Loading pool service data…
        </div>
      ) : error ? (
        <div
          className="rounded-2xl p-4 text-sm"
          style={{ background: "#FEF2F2", border: "1px solid #FECACA", color: "#B91C1C" }}
          data-testid="pool-service-error"
        >
          {error}
        </div>
      ) : (
        <>
          {/* Feb-2026 · Inclusive-count fix — primary "Completed Jobs"
              count sits above the breakdown chips so admins see the
              authoritative total first.  Reads ``total_completed_all``
              which includes service + repair + other completed pool
              jobs (the legacy ``total_completed`` chip below still
              reflects service-only for backward compat). */}
          <div
            className="rounded-2xl mb-3 px-4 py-4 flex flex-wrap items-baseline gap-x-4 gap-y-1"
            style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
            data-testid="pool-report-completed-primary"
          >
            <div className="flex items-baseline gap-2">
              <span className="text-xs font-semibold uppercase" style={{ color: colors.muted }}>
                Completed Jobs
              </span>
              <span
                className="text-3xl font-bold tabular-nums"
                style={{ color: colors.onSurface }}
                data-testid="pool-report-completed-all"
              >
                {totalCompletedAll}
              </span>
            </div>
            <span className="text-xs" style={{ color: colors.muted }}>
              Service, repair and other completed visits combined.
            </span>
            {isAdmin && droppedCount > 0 && (
              <span
                className="text-xs ml-auto inline-flex items-center gap-1 px-2 py-1 rounded-md font-semibold"
                style={{
                  background: "#FEF3C7", color: "#92400E",
                  border: "1px solid #FDE68A",
                }}
                data-testid="pool-report-dropped-count"
                title="Pool jobs in this window with a status outside completed/skipped (e.g. scheduled, in_progress). Not counted in any bucket."
              >
                {droppedCount} job{droppedCount === 1 ? "" : "s"} dropped (non-terminal status)
              </span>
            )}
          </div>

          {/* Summary strip — counts + total.  ``Other`` chip hidden
              when zero per brief §"Empty states". */}
          <div
            className="rounded-2xl mb-4 px-4 py-3 flex flex-wrap items-center gap-3 text-sm"
            style={{ background: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
            data-testid="pool-service-summary"
          >
            <span className="text-xs font-semibold uppercase" style={{ color: colors.muted }}>
              Week {data?.week_start} → {data?.week_end}
            </span>
            <span className="grow" />
            <Chip
              label="Maintenance"
              value={totalMaintenance}
              tone="brand"
              testid="pool-report-total-serviced"
            />
            <Chip
              label="Repairs"
              value={totalRepairs}
              tone="repair"
              testid="pool-report-total-repairs"
            />
            {totalOther > 0 && (
              <Chip
                label="Other"
                value={totalOther}
                tone="warn"
                testid="pool-report-total-other"
              />
            )}
            <Chip label="Total" value={totalAll} tone="neutral" testid="pool-report-total-all" />
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* ─── Maintenance Visits ────────────────────────── */}
            <div
              className="rounded-2xl overflow-hidden"
              style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
              data-testid="pool-service-maintenance-section"
            >
              <div
                className="px-4 py-3 text-xs font-semibold flex justify-between items-center"
                style={{ background: colors.surfaceSecondary, color: colors.muted, borderBottom: `1px solid ${colors.border}` }}
              >
                <span className="uppercase">Maintenance Visits</span>
                <span
                  className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-bold"
                  style={{ background: colors.brand, color: "#fff" }}
                >
                  {totalMaintenance}
                </span>
              </div>
              <table className="w-full text-sm" data-testid="pool-service-maintenance-table">
                <thead>
                  <tr style={{ borderBottom: `1px solid ${colors.border}` }}>
                    <th className="text-left px-4 py-2.5"
                        style={{ color: colors.muted, fontWeight: 600, fontSize: 11, textTransform: "uppercase" }}>
                      Tech Name
                    </th>
                    <th className="text-right px-4 py-2.5"
                        style={{ color: colors.muted, fontWeight: 600, fontSize: 11, textTransform: "uppercase" }}>
                      Pools Serviced
                    </th>
                    <th className="text-right px-4 py-2.5"
                        style={{ color: colors.muted, fontWeight: 600, fontSize: 11, textTransform: "uppercase" }}>
                      Skipped
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {maintenance.length === 0 ? (
                    <SectionEmpty
                      label="No maintenance visits in this period"
                      testid="pool-service-maintenance-empty"
                    />
                  ) : (
                    maintenance.map((r) => (
                      <TechRow
                        key={`m-${r.technician_id || r.technician_name}`}
                        row={r}
                        variant="maintenance"
                      />
                    ))
                  )}
                </tbody>
              </table>
            </div>

            {/* ─── Repairs Completed ─────────────────────────── */}
            <div
              className="rounded-2xl overflow-hidden"
              style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
              data-testid="pool-service-repairs-section"
            >
              <div
                className="px-4 py-3 text-xs font-semibold flex justify-between items-center"
                style={{ background: colors.surfaceSecondary, color: colors.muted, borderBottom: `1px solid ${colors.border}` }}
              >
                <span className="uppercase">Repairs Completed</span>
                <span
                  className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-bold"
                  style={{ background: "#B45309", color: "#fff" }}
                >
                  {totalRepairs}
                </span>
              </div>
              <table className="w-full text-sm" data-testid="pool-service-repairs-table">
                <thead>
                  <tr style={{ borderBottom: `1px solid ${colors.border}` }}>
                    <th className="text-left px-4 py-2.5"
                        style={{ color: colors.muted, fontWeight: 600, fontSize: 11, textTransform: "uppercase" }}>
                      Tech Name
                    </th>
                    <th className="text-right px-4 py-2.5"
                        style={{ color: colors.muted, fontWeight: 600, fontSize: 11, textTransform: "uppercase" }}>
                      Repairs
                    </th>
                    <th className="text-right px-4 py-2.5"
                        style={{ color: colors.muted, fontWeight: 600, fontSize: 11, textTransform: "uppercase" }}>
                      Skipped
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {repairs.length === 0 ? (
                    <SectionEmpty
                      label="No repairs completed in this period"
                      testid="pool-service-repairs-empty"
                    />
                  ) : (
                    repairs.map((r) => (
                      <TechRow
                        key={`r-${r.technician_id || r.technician_name}`}
                        row={r}
                        variant="repairs"
                      />
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {/* Phase 50.G — Auto-Friday email history */}
      <div
        className="rounded-2xl mt-6 overflow-hidden"
        style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
        data-testid="pool-service-email-history"
      >
        <div
          className="px-4 py-3 text-xs font-semibold flex justify-between items-center"
          style={{ background: colors.surfaceSecondary, color: colors.muted, borderBottom: `1px solid ${colors.border}` }}
        >
          <span>Auto-Friday email deliveries (last 10)</span>
          <span style={{ fontStyle: "italic" }}>Cron: Friday 17:00 UTC</span>
        </div>
        {history.length === 0 ? (
          <div className="px-4 py-6 text-center text-sm" style={{ color: colors.muted }}
               data-testid="pool-service-email-history-empty">
            No deliveries yet — the first cron run will appear here.
          </div>
        ) : (
          <table className="w-full text-sm" data-testid="pool-service-email-history-table">
            <thead>
              <tr style={{ borderBottom: `1px solid ${colors.border}` }}>
                <th className="text-left px-4 py-2 uppercase text-[11px] font-semibold" style={{ color: colors.muted }}>Sent at</th>
                <th className="text-left px-4 py-2 uppercase text-[11px] font-semibold" style={{ color: colors.muted }}>Week</th>
                <th className="text-left px-4 py-2 uppercase text-[11px] font-semibold" style={{ color: colors.muted }}>Recipients</th>
                <th className="text-left px-4 py-2 uppercase text-[11px] font-semibold" style={{ color: colors.muted }}>Status</th>
              </tr>
            </thead>
            <tbody>
              {history.map((h) => (
                <tr key={h.id} data-testid={`pool-service-email-history-row-${h.id}`}
                    style={{ borderBottom: `1px solid ${colors.border}` }}>
                  <td className="px-4 py-2" style={{ color: colors.onSurface }}>
                    {h.sent_at ? new Date(h.sent_at).toLocaleString() : "—"}
                  </td>
                  <td className="px-4 py-2 text-xs" style={{ color: colors.muted }}>
                    {h.week_start} → {h.week_end}
                  </td>
                  <td className="px-4 py-2 text-xs" style={{ color: colors.muted }}>
                    {(h.recipients || []).length} · {(h.total_completed || 0)} serviced
                  </td>
                  <td className="px-4 py-2">
                    {h.mocked ? (
                      <span className="inline-block px-2 py-0.5 rounded text-[10px] font-bold uppercase"
                            style={{ background: "#FEF3C7", color: "#92400E" }}
                            title={h.reason || "mocked"}>
                        MOCKED · {h.reason || "no reason"}
                      </span>
                    ) : (
                      <span className="inline-block px-2 py-0.5 rounded text-[10px] font-bold uppercase"
                            style={{ background: "#DCFCE7", color: "#166534" }}>
                        Sent
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

/**
 * Small labelled count chip used in the summary strip.
 * Kept private to this file — three tones (brand / repair / warn /
 * neutral) match the section colouring.
 */
function Chip({ label, value, tone, testid }) {
  const palette = {
    brand:   { bg: colors.brand, fg: "#fff" },
    repair:  { bg: "#B45309",     fg: "#fff" },
    warn:    { bg: "#FEF3C7",     fg: "#92400E" },
    neutral: { bg: colors.surface, fg: colors.onSurface, border: colors.border },
  };
  const p = palette[tone] || palette.neutral;
  return (
    <span
      data-testid={testid}
      className="inline-flex items-center gap-1 px-3 py-1 rounded-full text-xs font-bold"
      style={{
        background: p.bg,
        color: p.fg,
        border: p.border ? `1px solid ${p.border}` : "none",
      }}
    >
      <span style={{ opacity: 0.85 }}>{label}:</span>
      <span>{value}</span>
    </span>
  );
}
