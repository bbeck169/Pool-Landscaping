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
import { Waves, Download, ChevronDown, ChevronUp, RefreshCw, Send } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api";
import { useAuth } from "@/auth";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
  DialogDescription, DialogFooter,
} from "@/components/ui/dialog";
import { colors } from "@/theme";
// Feb-2026 · Pool-service drill-down phase — shared modal used by
// TC-A (bucket chip click), TC-B (per-tech row click) and TC-C
// (Auto-Friday email delivery row click). Loads jobs on open so
// the summary page stays light.
import PoolServiceDrilldownModal from "@/components/reports/PoolServiceDrilldownModal";

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
 * Feb-2026 · Service-name regrouping — CSV generator for the new
 * primary view. One row per {service_name × tech} pairing plus a
 * leading "Unassigned" row when the backend reports any. Keeps
 * ``toCsv`` above untouched so the legacy work_class-flavored CSV
 * is still available for consumers that haven't migrated.
 */
function serviceNameCsv(breakdown) {
  const header = ["Service Name", "Tech Name", "Count"];
  const rows = [];
  const unassignedCount = breakdown?.unassigned?.count || 0;
  if (unassignedCount > 0) {
    rows.push(["Unassigned", "—", unassignedCount]);
  }
  for (const b of (breakdown?.buckets || [])) {
    for (const t of (b.techs || [])) {
      rows.push([b.name, t.technician_name, t.count]);
    }
    // "Other" sub-breakdown — one summary row per service_name
    // under Other so an admin opening the CSV sees the same
    // grouping that the expandable UI reveals.
    if (b.name === "Other"
        && Array.isArray(b.other_breakdown)
        && b.other_breakdown.length > 0) {
      for (const sub of b.other_breakdown) {
        rows.push([
          `Other › ${sub.service_name}`,
          "—",
          sub.count,
        ]);
      }
    }
  }
  return [header, ...rows]
    .map((line) =>
      line.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(","),
    )
    .join("\n");
}

/**
 * Single shared tech-row renderer — one implementation used by both
 * the Maintenance and Repairs tables so the row markup is never
 * duplicated (brief rule §"Both sections share the same row-shape
 * renderer").  ``variant`` picks which counter to render bold in
 * the middle column + which data-testid suffix to stamp.
 *
 * Feb-2026 · Pool-service drill-down phase — the whole row is now
 * a <button> so admins can click into the per-tech modal (TC-B).
 * The row-level click is wired via ``onClick`` on the <tr>; we
 * use ``tabIndex=0`` + ``role=button`` + keyboard handlers so
 * keyboard-only users land the same affordance.
 */
function TechRow({ row, variant, onDrilldown }) {
  const isRepair = variant === "repairs";
  const isOther  = variant === "other";
  const primary = isRepair
    ? row.repairs_completed
    : isOther ? row.other : row.pools_serviced;
  const primaryTestId = isRepair
    ? `pool-report-tech-row-${row.technician_id || "unassigned"}-repairs`
    : isOther
      ? `pool-report-tech-row-${row.technician_id || "unassigned"}-other`
      : `pool-report-tech-row-${row.technician_id || "unassigned"}-serviced`;
  const handleClick = () => {
    onDrilldown && onDrilldown({
      techId: row.technician_id || "unassigned",
      techName: row.technician_name,
    });
  };
  const handleKey = (ev) => {
    if (ev.key === "Enter" || ev.key === " ") {
      ev.preventDefault();
      handleClick();
    }
  };
  return (
    <tr
      key={row.technician_id || row.technician_name}
      data-testid={`pool-service-row-${row.technician_id || "unassigned"}-${variant}`}
      onClick={handleClick}
      onKeyDown={handleKey}
      role="button"
      tabIndex={0}
      style={{
        borderBottom: `1px solid ${colors.border}`,
        cursor: "pointer",
      }}
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

  // Feb-2026 · Pool-service drill-down phase — the modal is a
  // single component with three variants (bucket / tech /
  // delivery). ``drilldown`` carries the variant + its inputs;
  // ``null`` closes.
  const [drilldown, setDrilldown] = useState(null);
  // Mini-fix B · Feb-2026 — admin-triggered Friday email.
  // Safety follow-up (Feb-2026): the Send-Now flow now uses a
  // custom confirm dialog with an explicit "Dry run (preview
  // only)" checkbox DEFAULTING to CHECKED. An admin must
  // explicitly uncheck the box to send real emails — and the
  // confirm copy switches to a loud ⚠ when they do.
  const [sendDialogOpen, setSendDialogOpen] = useState(false);
  const [sendDryRun, setSendDryRun] = useState(true);
  const [sendingNow, setSendingNow] = useState(false);
  const reloadHistory = async () => {
    try {
      const res = await api.get(
        "/reports/pool-service/email-history?limit=10",
      );
      setHistory(res?.items || []);
    } catch { /* silent — handled by the next page refresh */ }
  };
  const openSendDialog = () => {
    // Always reset dry_run to TRUE every time the dialog opens
    // so a prior-session un-check doesn't leak into a fresh
    // flow.
    setSendDryRun(true);
    setSendDialogOpen(true);
  };
  const executeSendNow = async () => {
    setSendDialogOpen(false);
    setSendingNow(true);
    try {
      const res = await api.post(
        "/reports/pool-service/email-history/run-now",
        { week_ref: week, dry_run: sendDryRun },
      );
      const forced = res?.dry_run_forced_by_env;
      const effective = res?.dry_run;
      let stub;
      if (effective && forced) {
        stub = `Dry run (forced by preview environment) · ${res?.recipient_count ?? 0} recipient${res?.recipient_count === 1 ? "" : "s"} would receive the email.`;
      } else if (effective) {
        stub = `Dry run · ${res?.recipient_count ?? 0} recipient${res?.recipient_count === 1 ? "" : "s"} would receive the email.`;
      } else if (res?.mocked) {
        stub = `Delivery mocked (${res?.reason || "unknown"}).`;
      } else {
        stub = `Delivered to ${res?.recipient_count ?? 0} recipient${res?.recipient_count === 1 ? "" : "s"}.`;
      }
      toast.success(`Pool Service email · ${stub}`);
      await reloadHistory();
    } catch (e) {
      toast.error(`Could not send: ${e?.message || "unknown error"}`);
    } finally {
      setSendingNow(false);
    }
  };

  const maintenance = useMemo(
    () => data?.maintenance || [], [data],
  );
  const repairs = useMemo(
    () => data?.repairs || [], [data],
  );
  const otherRows = useMemo(
    () => data?.other || [], [data],
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
  // Feb-2026 · Pool-service drill-down phase — compute the
  // "Unassigned" aggregate from the per-tech rows. The backend
  // appends an explicit ``{technician_id: null, technician_name:
  // "Unassigned"}`` row when non-zero so admins see the gap
  // without silently losing jobs. The chip + the Unassigned-
  // section drill-in use this.
  const unassignedRow = useMemo(() => {
    const rows = data?.by_technician || [];
    return rows.find((r) => !r.technician_id) || null;
  }, [data]);
  const unassignedTotal = unassignedRow
    ? ((unassignedRow.pools_serviced || 0)
       + (unassignedRow.repairs_completed || 0)
       + (unassignedRow.other || 0))
    : 0;
  const reconciliation = data?.reconciliation || null;
  const otherLabel = data?.other_label || "Other";
  // Feb-2026 · Service-name regrouping — the primary row grouping
  // on this page is now driven off ``service_name_breakdown`` from
  // the backend. The pre-existing per-tech ``work_class`` tables
  // below stay rendered for admins who prefer that view; the new
  // section is the first the admin sees after the summary chips.
  const serviceNameBreakdown = data?.service_name_breakdown || null;
  const serviceNameDelta =
    typeof serviceNameBreakdown?.reconciliation_delta === "number"
      ? serviceNameBreakdown.reconciliation_delta
      : null;
  // ``shouldShowReconciliationBanner`` gates the old
  // "could-not-be-attributed" yellow banner. Post-regrouping, the
  // service-name section accounts for every pool job in the window
  // via Unassigned (missing / soft-deleted tech), so when
  // ``reconciliation_delta === 0`` the banner MUST hide — the
  // report is self-consistent. Legacy ``reconciliation.matches``
  // check remains as a defensive fallback for backends that pre-
  // date the service-name regrouping (older preview envs mid-roll).
  const shouldShowReconciliationBanner = (() => {
    if (serviceNameDelta !== null) return serviceNameDelta !== 0;
    return reconciliation && !reconciliation.matches;
  })();

  const downloadCsv = () => {
    // Feb-2026 · Service-name regrouping — prefer the new primary
    // grouping when the backend returns ``service_name_breakdown``;
    // fall through to the legacy per-tech export on older backends.
    if (serviceNameBreakdown
        && Array.isArray(serviceNameBreakdown.buckets)) {
      const csv = serviceNameCsv(serviceNameBreakdown);
      const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `pool-service-report_${data?.week_start || week}.csv`;
      a.click();
      URL.revokeObjectURL(url);
      return;
    }
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

          {/* Feb-2026 · Pool-service drill-down phase —
              reconciliation banner. Backend emits a passive
              ``reconciliation`` diagnostic (never raises); the
              banner surfaces when ``matches=false`` so admins
              know the per-tech rows don't sum to the actual
              pool-job volume for the week. ``delta`` is signed:
              positive = jobs missing from the rendered buckets;
              negative = double-counting (should never happen in
              practice but surfaced defensively).
              Fix 2 · Feb-2026 — the banner now includes the
              first-N dropped jobs (``dropped_sample``) so admins
              can click "View details" to inspect without
              opening logs. */}
          {shouldShowReconciliationBanner && (
            <ReconciliationBanner
              reconciliation={reconciliation}
              serviceNameBreakdown={serviceNameBreakdown}
            />
          )}

          {/* Summary strip — counts + total. All chips are now
              clickable (open the TC-A drill-down modal). The
              ``Other`` chip is always clickable when non-zero —
              label follows the server-published ``other_label``
              so a future rename doesn't require a FE deploy. */}
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
              label="Service"
              value={totalMaintenance}
              tone="brand"
              testid="pool-report-total-serviced"
              onClick={() => setDrilldown({ variant: "bucket", bucket: "maintenance" })}
            />
            <Chip
              label="Repair"
              value={totalRepairs}
              tone="repair"
              testid="pool-report-total-repairs"
              onClick={() => setDrilldown({ variant: "bucket", bucket: "repairs" })}
            />
            {totalOther > 0 && (
              <Chip
                label={otherLabel}
                value={totalOther}
                tone="warn"
                testid="pool-report-total-other"
                onClick={() => setDrilldown({ variant: "bucket", bucket: "other" })}
              />
            )}
            {/* TD-63 · Q3=1 — chip row carries WORK-CLASS vocabulary
                (Service / Repair / Other).  The BY SERVICE NAME
                section below intentionally keeps the semantic names
                (Weekly Pool Cleaning / Maintenance / Chemical / …)
                because those are a different dimension (service_type
                taxonomy, not work_class). */}
            {unassignedTotal > 0 && (
              <Chip
                label="Unassigned"
                value={unassignedTotal}
                tone="warn"
                testid="pool-report-total-unassigned"
                onClick={() => setDrilldown({ variant: "bucket", bucket: "unassigned" })}
              />
            )}
            <Chip label="Total" value={totalAll} tone="neutral" testid="pool-report-total-all" />
          </div>

          {/* ─── Feb-2026 · Service-name regrouping — primary view ──
              Groups the window's pool jobs by SERVICE NAME (the
              job's ``service_type``) with an Unassigned row at the
              top (jobs with missing / soft-deleted tech) and an
              expandable "Other" row that reveals the per-service-
              name sub-breakdown. The pre-existing per-tech
              maintenance / repairs tables below stay rendered as a
              secondary view for admins who prefer the work_class
              split. */}
          {serviceNameBreakdown && (
            <ServiceNameBreakdownSection
              breakdown={serviceNameBreakdown}
            />
          )}

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
                        onDrilldown={(p) => setDrilldown({ variant: "tech", ...p })}
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
                        onDrilldown={(p) => setDrilldown({ variant: "tech", ...p })}
                      />
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* Feb-2026 · Pool-service drill-down phase — "Other job
              types" section. Previously the "Other" bucket was
              only visible via the summary chip, which hid per-
              tech attribution and caused the "silent 21-job gap"
              bug (ethan@54 maintenance + 0 visible rows for the
              21 ``other``-typed jobs → total 75 ≠ 54+0). Now the
              bucket renders a dedicated table so admins see
              who's producing non-``work_class`` jobs AND can
              click into the drill-down for exact job list. */}
          {otherRows.length > 0 && (
            <div
              className="rounded-2xl overflow-hidden mt-4"
              style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
              data-testid="pool-service-other-section"
            >
              <div
                className="px-4 py-3 text-xs font-semibold flex justify-between items-center"
                style={{ background: colors.surfaceSecondary, color: colors.muted, borderBottom: `1px solid ${colors.border}` }}
              >
                <span className="uppercase">{otherLabel}</span>
                <span
                  className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-bold"
                  style={{ background: "#FEF3C7", color: "#92400E" }}
                >
                  {totalOther}
                </span>
              </div>
              <table className="w-full text-sm" data-testid="pool-service-other-table">
                <thead>
                  <tr style={{ borderBottom: `1px solid ${colors.border}` }}>
                    <th className="text-left px-4 py-2.5"
                        style={{ color: colors.muted, fontWeight: 600, fontSize: 11, textTransform: "uppercase" }}>
                      Tech Name
                    </th>
                    <th className="text-right px-4 py-2.5"
                        style={{ color: colors.muted, fontWeight: 600, fontSize: 11, textTransform: "uppercase" }}>
                      {otherLabel}
                    </th>
                    <th className="text-right px-4 py-2.5"
                        style={{ color: colors.muted, fontWeight: 600, fontSize: 11, textTransform: "uppercase" }}>
                      Skipped
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {otherRows.map((r) => (
                    <TechRow
                      key={`o-${r.technician_id || r.technician_name}`}
                      row={r}
                      variant="other"
                      onDrilldown={(p) => setDrilldown({ variant: "tech", ...p })}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          )}
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
          <div className="flex items-center gap-3">
            <span style={{ fontStyle: "italic" }}>Cron: Friday 17:00 UTC</span>
            {isAdmin && (
              <button
                type="button"
                onClick={openSendDialog}
                disabled={sendingNow}
                className="inline-flex items-center gap-1 text-[11px] font-bold uppercase px-2.5 py-1 rounded-md"
                style={{
                  background: sendingNow ? colors.surfaceSecondary : colors.brand,
                  color: sendingNow ? colors.muted : "#fff",
                  border: `1px solid ${sendingNow ? colors.border : colors.brand}`,
                  cursor: sendingNow ? "not-allowed" : "pointer",
                }}
                data-testid="pool-service-send-now"
                title="Trigger the Friday email now for the selected week. Creates a new delivery entry."
              >
                <Send size={11} />
                {sendingNow ? "Sending…" : "Send now"}
              </button>
            )}
          </div>
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
                    onClick={() => setDrilldown({
                      variant: "delivery",
                      deliveryId: h.id,
                      deliveryTitle: `Delivery · ${h.week_start} → ${h.week_end}`,
                    })}
                    role="button"
                    tabIndex={0}
                    onKeyDown={(ev) => {
                      if (ev.key === "Enter" || ev.key === " ") {
                        ev.preventDefault();
                        setDrilldown({
                          variant: "delivery",
                          deliveryId: h.id,
                          deliveryTitle: `Delivery · ${h.week_start} → ${h.week_end}`,
                        });
                      }
                    }}
                    style={{
                      borderBottom: `1px solid ${colors.border}`,
                      cursor: "pointer",
                    }}>
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

      {/* Feb-2026 · Pool-service drill-down phase — shared modal.
          Three variants (bucket / tech / delivery). ``drilldown``
          state is set by the chip, row, and email-history row
          click handlers above; the modal reads the variant and
          fetches on open. ``onClose`` nulls out the state. */}
      {drilldown && (
        <PoolServiceDrilldownModal
          variant={drilldown.variant}
          open={!!drilldown}
          onClose={() => setDrilldown(null)}
          dateFrom={data?.week_start || week}
          dateTo={data?.week_end
            || (() => {
              const s = new Date(week + "T00:00:00");
              s.setDate(s.getDate() + 6);
              return s.toISOString().slice(0, 10);
            })()}
          bucket={drilldown.bucket}
          techId={drilldown.techId}
          techName={drilldown.techName}
          deliveryId={drilldown.deliveryId}
          deliveryTitle={drilldown.deliveryTitle}
        />
      )}

      {/* Safety · Feb-2026 — Send-now confirm dialog with the
          explicit dry-run checkbox. DEFAULT CHECKED so an
          accidental Enter press on an empty dialog can't blast
          real emails. The non-dry-run copy switches to a loud ⚠
          + a destructive-tone CTA. */}
      <Dialog open={sendDialogOpen} onOpenChange={setSendDialogOpen}>
        <DialogContent data-testid="pool-service-send-dialog">
          <DialogHeader>
            <DialogTitle>Send the Pool Service email for week {week}?</DialogTitle>
            <DialogDescription>
              This will create a new delivery entry.{" "}
              {sendDryRun
                ? "The payload will be snapshotted but NO email will be sent."
                : "Admins currently in the recipient list will receive the email."}
            </DialogDescription>
          </DialogHeader>
          <label
            className="flex items-start gap-2 py-2 cursor-pointer select-none"
            style={{ color: colors.onSurface }}
          >
            <input
              type="checkbox"
              checked={sendDryRun}
              onChange={(e) => setSendDryRun(e.target.checked)}
              data-testid="pool-service-send-dry-run-toggle"
              className="mt-0.5"
            />
            <span className="text-sm">
              <strong>Dry run (preview only)</strong>
              <span className="block text-xs" style={{ color: colors.muted }}>
                Builds the payload + snapshots the delivery but skips the
                mailer. Unchecking sends REAL emails.
              </span>
            </span>
          </label>
          {!sendDryRun && (
            <div
              className="rounded-md px-3 py-2 text-sm"
              style={{
                background: "#FEE2E2", color: "#991B1B",
                border: "1px solid #FCA5A5",
              }}
              data-testid="pool-service-send-real-warning"
            >
              <strong>⚠ This will send REAL emails to the recipient list.</strong>{" "}
              Preview environments force dry run regardless — only
              production will actually mail.
            </div>
          )}
          <DialogFooter className="mt-2">
            <button
              type="button"
              onClick={() => setSendDialogOpen(false)}
              className="px-3 py-1.5 rounded-md text-sm"
              style={{
                background: colors.surface,
                color: colors.onSurface,
                border: `1px solid ${colors.border}`,
              }}
              data-testid="pool-service-send-cancel"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={executeSendNow}
              className="px-3 py-1.5 rounded-md text-sm font-semibold"
              style={{
                background: sendDryRun ? colors.brand : "#B91C1C",
                color: "#fff",
                border: `1px solid ${sendDryRun ? colors.brand : "#B91C1C"}`,
              }}
              data-testid="pool-service-send-confirm"
            >
              {sendDryRun ? "Run dry run" : "Send REAL emails"}
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

/**
 * Feb-2026 · Service-name regrouping — primary view component.
 *
 * Renders:
 *   • "Unassigned" row AT TOP (amber accent) when the backend
 *     reports non-zero unassigned.count.
 *   • One row per known service-name bucket (currently
 *     "Weekly Pool Cleaning" + "Maintenance") — count on the right.
 *   • "Other" row with a chevron — click to expand the per-service-
 *     name sub-breakdown. Sorted by count desc, service_name asc.
 *
 * Reads the backend's ``service_name_breakdown`` payload verbatim;
 * no FE-side bucket computation so a backend bucket-list change
 * never requires a FE deploy.
 */
function ServiceNameBreakdownSection({ breakdown }) {
  const [otherExpanded, setOtherExpanded] = React.useState(false);
  const unassignedCount = breakdown?.unassigned?.count || 0;
  const buckets = Array.isArray(breakdown?.buckets)
    ? breakdown.buckets : [];
  return (
    <div
      className="rounded-2xl mb-4 overflow-hidden"
      style={{
        background: colors.surface,
        border: `1px solid ${colors.border}`,
      }}
      data-testid="pool-report-service-name-section"
    >
      <div
        className="px-4 py-3 text-xs font-semibold flex items-center justify-between"
        style={{
          background: colors.surfaceSecondary,
          color: colors.muted,
          borderBottom: `1px solid ${colors.border}`,
        }}
      >
        <span className="uppercase">
          By service name
        </span>
        <span
          className="text-[11px]"
          style={{ color: colors.muted }}
          data-testid="pool-report-service-name-total"
        >
          {breakdown?.total_pool_jobs || 0} pool jobs this window
        </span>
      </div>
      <ul className="divide-y" style={{ borderColor: colors.border }}>
        {unassignedCount > 0 && (
          <li
            className="flex items-center justify-between px-4 py-3"
            style={{
              background: "#FEF3C7",
              borderLeft: "4px solid #F59E0B",
            }}
            data-testid="pool-report-service-name-unassigned-row"
          >
            <div className="flex items-center gap-2">
              <span
                className="text-xs font-bold uppercase px-2 py-0.5 rounded-full"
                style={{
                  background: "#F59E0B",
                  color: "#78350F",
                }}
              >
                Unassigned
              </span>
              <span
                className="text-sm"
                style={{ color: "#92400E" }}
              >
                Jobs with no active tech attributed
              </span>
            </div>
            <span
              className="text-base font-bold tabular-nums"
              style={{ color: "#92400E" }}
              data-testid="pool-report-service-name-unassigned-count"
            >
              {unassignedCount}
            </span>
          </li>
        )}
        {buckets.map((b) => {
          const isOther = b.name === "Other";
          const breakdownRows = Array.isArray(b.other_breakdown)
            ? b.other_breakdown : [];
          return (
            <li
              key={b.name}
              className="px-4 py-2.5"
              data-testid={`pool-report-service-name-row-${b.name
                .toLowerCase().replace(/\s+/g, "-")}`}
            >
              <button
                type="button"
                onClick={isOther
                  ? () => setOtherExpanded((v) => !v)
                  : undefined}
                disabled={!isOther}
                className="w-full flex items-center justify-between"
                style={{
                  background: "transparent",
                  padding: 0,
                  cursor: isOther ? "pointer" : "default",
                  color: colors.onSurface,
                }}
                data-testid={isOther
                  ? "pool-report-service-name-other-toggle"
                  : undefined}
                aria-expanded={isOther ? otherExpanded : undefined}
              >
                <span className="flex items-center gap-2">
                  {isOther ? (
                    otherExpanded
                      ? <ChevronUp size={14} />
                      : <ChevronDown size={14} />
                  ) : (
                    <span style={{ width: 14 }} />
                  )}
                  <span className="text-sm font-semibold">
                    {b.name}
                  </span>
                </span>
                <span className="text-sm font-bold tabular-nums">
                  {b.count}
                </span>
              </button>
              {isOther && otherExpanded && breakdownRows.length > 0 && (
                <ul
                  className="mt-2 ml-6 space-y-1"
                  data-testid="pool-report-service-name-other-breakdown"
                >
                  {breakdownRows.map((sub) => (
                    <li
                      key={sub.service_name}
                      className="flex items-center justify-between text-xs"
                      style={{ color: colors.muted }}
                      data-testid={`pool-report-service-name-other-sub-${
                        sub.service_name.toLowerCase()
                          .replace(/\s+/g, "-")
                      }`}
                    >
                      <span>{sub.service_name}</span>
                      <span className="tabular-nums font-semibold">
                        {sub.count}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
              {isOther && otherExpanded && breakdownRows.length === 0 && (
                <div
                  className="mt-2 ml-6 text-xs italic"
                  style={{ color: colors.muted }}
                  data-testid="pool-report-service-name-other-empty"
                >
                  No per-service-name breakdown available.
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}


/**
 * Feb-2026 · Fix 2 — Reconciliation banner with inline dropped-
 * jobs sample. Keeps the (compact) collapsed shape by default
 * and expands a small inline list when the admin clicks "View
 * details". Lives at module scope so vitest can mount it in
 * isolation + the main page body stays readable.
 */
function ReconciliationBanner({ reconciliation, serviceNameBreakdown }) {
  const [expanded, setExpanded] = React.useState(false);
  const sample = Array.isArray(reconciliation?.dropped_sample)
    ? reconciliation.dropped_sample : [];
  const droppedCount = reconciliation?.dropped_count || 0;
  // Feb-2026 · Service-name regrouping — when the backend returns
  // the new ``service_name_breakdown`` section, prefer its signed
  // ``reconciliation_delta`` (post-regrouping Unassigned captures
  // every missing / soft-deleted-tech job) over the legacy
  // ``reconciliation.delta``.  Falls back verbatim on older
  // backends.
  const svcDelta =
    typeof serviceNameBreakdown?.reconciliation_delta === "number"
      ? serviceNameBreakdown.reconciliation_delta
      : null;
  const effectiveDelta = svcDelta !== null
    ? svcDelta
    : (reconciliation?.delta || 0);
  const effectiveCounted = svcDelta !== null
    ? ((serviceNameBreakdown?.total_pool_jobs || 0) - svcDelta)
    : (reconciliation?.counted_total || 0);
  const effectiveActual = svcDelta !== null
    ? (serviceNameBreakdown?.total_pool_jobs || 0)
    : (reconciliation?.actual_total || 0);
  return (
    <div
      className="rounded-2xl mb-3 px-4 py-3 text-sm"
      style={{
        background: "#FEF3C7", color: "#92400E",
        border: "1px solid #FDE68A",
      }}
      data-testid="pool-report-reconciliation-banner"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <strong>Reconciliation off by{" "}
          <span data-testid="pool-report-reconciliation-delta">
            {effectiveDelta}
          </span>:
        </strong>
        <span>
          rendered rows sum to{" "}
          <span data-testid="pool-report-reconciliation-counted">
            {effectiveCounted}
          </span>{" "}
          but the window has{" "}
          <span data-testid="pool-report-reconciliation-actual">
            {effectiveActual}
          </span>{" "}
          pool jobs
          {droppedCount > 0 && (
            <>
              {" "}·{" "}
              <span data-testid="pool-report-reconciliation-dropped-count">
                {droppedCount}
              </span>{" "}
              could not be attributed
            </>
          )}
          .
        </span>
        {sample.length > 0 && (
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="underline text-xs font-semibold"
            style={{ color: "#92400E", background: "transparent",
                       padding: 0, cursor: "pointer" }}
            data-testid="pool-report-reconciliation-toggle"
          >
            {expanded ? "Hide details" : "View details"}
          </button>
        )}
      </div>
      {expanded && sample.length > 0 && (
        <ul
          className="mt-2 ml-4 list-disc text-xs"
          data-testid="pool-report-reconciliation-sample-list"
        >
          {sample.map((s) => (
            <li
              key={s.job_id}
              data-testid={`pool-report-reconciliation-sample-row-${s.job_id}`}
            >
              <a
                href={`/jobs/${encodeURIComponent(s.job_id)}`}
                target="_blank"
                rel="noopener noreferrer"
                className="underline"
                style={{ color: "#92400E" }}
              >
                {s.customer_name || s.job_id}
              </a>
              {" · "}
              <span>{s.scheduled_date || "—"}</span>
              {" · "}
              <span>{s.reason}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}


/**
 * Small labelled count chip used in the summary strip.
 * Kept private to this file — three tones (brand / repair / warn /
 * neutral) match the section colouring.
 *
 * Feb-2026 · Pool-service drill-down phase — accepts an optional
 * ``onClick`` prop. When provided, the chip renders as a <button>
 * so it is keyboard-focusable and announces itself as a control
 * (TC-A — the admin can click a bucket chip to see the per-job
 * list). Chips without ``onClick`` (currently just the "Total"
 * chip) remain plain <span> labels.
 */
function Chip({ label, value, tone, testid, onClick }) {
  const palette = {
    brand:   { bg: colors.brand, fg: "#fff" },
    repair:  { bg: "#B45309",     fg: "#fff" },
    warn:    { bg: "#FEF3C7",     fg: "#92400E" },
    neutral: { bg: colors.surface, fg: colors.onSurface, border: colors.border },
  };
  const p = palette[tone] || palette.neutral;
  const inner = (
    <>
      <span style={{ opacity: 0.85 }}>{label}:</span>
      <span>{value}</span>
    </>
  );
  const style = {
    background: p.bg,
    color: p.fg,
    border: p.border ? `1px solid ${p.border}` : "none",
  };
  const common = "inline-flex items-center gap-1 px-3 py-1 rounded-full text-xs font-bold";
  if (onClick) {
    return (
      <button
        type="button"
        data-testid={testid}
        onClick={onClick}
        className={common}
        style={{ ...style, cursor: "pointer" }}
      >
        {inner}
      </button>
    );
  }
  return (
    <span
      data-testid={testid}
      className={common}
      style={style}
    >
      {inner}
    </span>
  );
}
