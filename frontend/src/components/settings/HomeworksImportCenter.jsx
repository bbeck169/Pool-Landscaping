/**
 * Queue Item 5 · Feb-2026 — Homeworks Import Center.
 *
 * A unified super_admin-only panel that lives on the Integrations
 * hub. Provides four buttons:
 *
 *   1. Import Inactive Customers     (existing Phase 1b importer)
 *   2. Import Active Customers       (existing Phase 1b-B importer)
 *   3. Delta Sync                    (queue-item-5 new importer)
 *   4. Import Income Items (Pricebook) — coming soon: returns 501
 *
 * Each button owns its own dry-run → confirm → poll lifecycle. The
 * confirm dialog surfaces the dry-run count + estimated duration so
 * super_admins have full visibility before triggering the run.
 *
 * NOTE: creating a "queued" run doc does NOT auto-launch the
 * background process (matches the existing operator-driven nohup
 * pattern). This UI's job is to expose dry-run + queue + status
 * polling; an operator still runs::
 *
 *     nohup python3 -m scripts.homeworks_run_delta_sync \\
 *         --tenant-id … --run-id … &
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  ImportIcon, Users, RefreshCw, Package, PlayCircle, X as XIcon,
  Loader2, CheckCircle2, AlertTriangle, ChevronRight, Zap,
} from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api";
import { colors } from "@/theme";

// The four buttons on the Import Center. Each row's `slug` matches
// the router prefix segment: /integrations/homeworks/imports/<slug>.
const IMPORTERS = [
  {
    key: "inactive-customers",
    slug: "inactive-customers",
    label: "Import Inactive Customers",
    hint: "One-time backfill of inactive + written-off customers, plus their historical jobs / invoices / payments / quotes.",
    Icon: Users,
    kind: "inactive_customers",
  },
  {
    key: "active-customers",
    slug: "active-customers",
    label: "Import Active Customers",
    hint: "Backfill active + pending customers. Skips notes, tags, and avatar photos per contract.",
    Icon: Users,
    kind: "active_customers",
  },
  {
    key: "delta-sync",
    slug: "delta-sync",
    label: "Delta Sync",
    hint: "Runs active + inactive back-to-back, picking up any customers created since the last successful sync.",
    Icon: RefreshCw,
    kind: "delta_sync",
  },
  {
    key: "income-items",
    slug: "income-items",
    label: "Import Income Items (Pricebook)",
    hint: "Pulls the Homeworks income-items catalog into the pricebook. Skips items already imported or colliding by name with an existing pricebook entry.",
    Icon: Package,
    kind: "pricebook",
  },
];

const POLL_INTERVAL_MS = 3000;

function humanCount(n) {
  return typeof n === "number" ? n.toLocaleString() : "—";
}

// Extract a headline number from a dry-run report (varies per importer).
function pickDryRunCount(report) {
  if (!report) return null;
  if (typeof report.total_customer_count === "number") return report.total_customer_count;
  if (typeof report.inactive_customer_count === "number") return report.inactive_customer_count;
  if (typeof report.total_item_count === "number") return report.total_item_count;
  return null;
}

// ═════════════════════════════════════════════════════════════════
// Confirm modal — shows dry-run summary, asks for final go/no-go.
// ═════════════════════════════════════════════════════════════════
function ConfirmRunModal({ importer, dryRun, onCancel, onConfirm, busy }) {
  if (!importer) return null;
  const count = pickDryRunCount(dryRun);
  const existing = dryRun?.existing_in_aquaterra_by_original_id;
  const est = dryRun?.estimated_duration_minutes;
  const fatal = dryRun?.fatal_error || dryRun?.reason;
  // Task 2 · Feb-2026 — surface the delta prominently so a super_admin
  // sees "N candidates · M already imported · X NEW" at a glance and
  // stops running no-op re-imports.
  const knownCount = typeof count === "number" ? count : null;
  const knownExisting = typeof existing === "number" ? existing : null;
  const newCount = (knownCount !== null && knownExisting !== null)
    ? Math.max(0, knownCount - knownExisting)
    : null;
  const isNoop = newCount === 0 && knownCount !== null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center px-4"
      style={{ background: "rgba(15,23,42,0.55)" }}
      onMouseDown={(e) => { if (e.target === e.currentTarget) onCancel(); }}
      data-testid="homeworks-import-confirm-modal"
    >
      <div
        className="w-full max-w-md rounded-2xl p-6 shadow-2xl"
        style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between mb-3">
          <div>
            <h2 className="text-lg font-bold" style={{ color: colors.onSurface }}>
              Confirm {importer.label.toLowerCase()}
            </h2>
            <p className="text-sm mt-1" style={{ color: colors.muted }}>
              Dry-run preview — review the counts before queuing the run.
            </p>
          </div>
          <button
            type="button"
            onClick={onCancel}
            className="p-1"
            style={{ color: colors.muted }}
            aria-label="Close"
            data-testid="homeworks-import-confirm-close"
          >
            <XIcon size={18} />
          </button>
        </div>

        {fatal ? (
          <div
            className="rounded-xl p-3 text-sm mb-3"
            style={{ backgroundColor: "#FEE2E2", color: "#991B1B",
                       border: "1px solid #FECACA" }}
            data-testid="homeworks-import-dryrun-error"
          >
            <div className="flex items-start gap-2">
              <AlertTriangle size={14} style={{ marginTop: 2 }} />
              <div>
                <div className="font-bold">Dry-run flagged an issue</div>
                <div className="text-xs mt-1">{fatal}</div>
              </div>
            </div>
          </div>
        ) : null}

        <div
          className="rounded-xl p-3 text-sm space-y-1.5"
          style={{
            backgroundColor: colors.surfaceSecondary,
            border: `1px solid ${colors.border}`,
          }}
          data-testid="homeworks-import-dryrun-summary"
        >
          <SummaryRow label="Records reported by Homeworks" value={humanCount(count)} />
          <SummaryRow label="Already imported (will be skipped)" value={humanCount(existing)} />
          <SummaryRow label="Estimated duration" value={est != null ? `${est} min` : "—"} />
        </div>

        {/* Task 2 · Feb-2026 — Delta headline. Makes "no new records"
            re-runs impossible to miss. */}
        {newCount !== null ? (
          <div
            className="rounded-xl p-3 mt-3 flex items-center gap-3"
            style={{
              backgroundColor: isNoop ? "#FEF3C7" : "#DCFCE7",
              border: `1px solid ${isNoop ? "#FDE68A" : "#86EFAC"}`,
            }}
            data-testid="homeworks-import-delta-headline"
          >
            <div
              className="text-2xl font-bold shrink-0"
              style={{ color: isNoop ? "#92400E" : "#166534" }}
              data-testid="homeworks-import-delta-count"
            >
              {humanCount(newCount)}
            </div>
            <div className="text-xs" style={{ color: isNoop ? "#92400E" : "#166534" }}>
              <b>{isNoop ? "No new records" : "new record" + (newCount === 1 ? "" : "s")}</b>{" "}
              to import.
              <div className="opacity-80 mt-0.5">
                {humanCount(count)} candidates · {humanCount(existing)}{" "}
                already in AquaTerra
              </div>
            </div>
          </div>
        ) : null}

        <p className="text-[11px] mt-3" style={{ color: colors.muted }}>
          A queued run document is created immediately. The processing
          launcher must be started separately (nohup or launch task).
        </p>

        <div className="mt-5 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="px-4 py-2 rounded-xl text-sm font-semibold"
            style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurface }}
            data-testid="homeworks-import-confirm-cancel"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={busy || !!fatal}
            className="px-4 py-2 rounded-xl text-sm font-bold text-white disabled:opacity-60"
            style={{ backgroundColor: colors.brandPrimary }}
            data-testid="homeworks-import-confirm-btn"
          >
            {busy ? "Queuing…" : "Queue the run"}
          </button>
        </div>
      </div>
    </div>
  );
}

function SummaryRow({ label, value }) {
  return (
    <div className="flex items-center justify-between">
      <span style={{ color: colors.muted }}>{label}</span>
      <b style={{ color: colors.onSurface }}>{value}</b>
    </div>
  );
}

// ═════════════════════════════════════════════════════════════════
// One row per importer.
// ═════════════════════════════════════════════════════════════════
function ImporterRow({ importer, onLaunch }) {
  const { Icon } = importer;
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState(null); // { run_id, status, counters }

  // Poll active run — best effort.
  const poll = useCallback(async () => {
    try {
      const r = await api.get(
        `/integrations/homeworks/imports/${importer.slug}/active`,
      );
      const [top] = r?.active_runs || [];
      if (top) setStatus(top);
      else setStatus(null);
    } catch { /* silent — polling failures shouldn't spam toasts */ }
  }, [importer.slug]);

  useEffect(() => {
    if (importer.comingSoon) return undefined;
    poll();
    const t = setInterval(poll, POLL_INTERVAL_MS);
    return () => clearInterval(t);
  }, [poll, importer.comingSoon]);

  const launch = async () => {
    if (importer.comingSoon) return;
    setBusy(true);
    try {
      const dry = await api.post(
        `/integrations/homeworks/imports/${importer.slug}/dry-run`,
      );
      onLaunch(importer, dry);
    } catch (e) {
      toast.error(e?.message || "Dry-run failed");
    } finally { setBusy(false); }
  };

  const running = !!status && (status.status === "running" || status.status === "queued");

  return (
    <div
      className="rounded-xl p-4 flex items-center gap-3"
      style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
      data-testid={`homeworks-import-row-${importer.key}`}
    >
      <div
        className="rounded-lg p-2 shrink-0"
        style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurfaceSecondary }}
      >
        <Icon size={18} />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span
            className="font-bold text-sm"
            style={{ color: colors.onSurface }}
            data-testid={`homeworks-import-label-${importer.key}`}
          >
            {importer.label}
          </span>
          {importer.comingSoon ? (
            <span
              className="text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded"
              style={{ backgroundColor: "#FEF3C7", color: "#92400E" }}
              data-testid={`homeworks-import-badge-comingsoon-${importer.key}`}
            >
              Coming soon
            </span>
          ) : running ? (
            <span
              className="text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded inline-flex items-center gap-1"
              style={{ backgroundColor: "#DBEAFE", color: "#1E3A8A" }}
              data-testid={`homeworks-import-badge-running-${importer.key}`}
            >
              <Loader2 size={10} className="animate-spin" />
              {status.status}
            </span>
          ) : status?.status === "completed" ? (
            <span
              className="text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded inline-flex items-center gap-1"
              style={{ backgroundColor: "#DCFCE7", color: "#166534" }}
              data-testid={`homeworks-import-badge-done-${importer.key}`}
            >
              <CheckCircle2 size={10} /> Done
            </span>
          ) : null}
        </div>
        <p className="text-xs mt-0.5" style={{ color: colors.muted }}>
          {importer.hint}
        </p>
        {running && status?.counters ? (
          <div
            className="mt-2 text-[11px] font-semibold"
            style={{ color: colors.onSurfaceSecondary }}
            data-testid={`homeworks-import-progress-${importer.key}`}
          >
            Scanned {humanCount(status.counters.customers_scanned)} · Imported{" "}
            {humanCount(status.counters.customers_imported)} · Skipped{" "}
            {humanCount(status.counters.customers_skipped)}
          </div>
        ) : null}
      </div>
      <button
        type="button"
        onClick={launch}
        disabled={busy || running || importer.comingSoon}
        className="text-xs font-semibold px-3 py-2 rounded-lg inline-flex items-center gap-1.5 text-white disabled:opacity-50"
        style={{ backgroundColor: colors.brandPrimary }}
        data-testid={`homeworks-import-launch-${importer.key}`}
        title={importer.comingSoon ? "Coming next — Pricebook importer is scheduled after Delta Sync ships." : undefined}
      >
        {importer.comingSoon ? "Coming soon" : (running ? "Running…" : <><PlayCircle size={12} /> Dry-run</>)}
        {!importer.comingSoon && !running ? <ChevronRight size={12} /> : null}
      </button>
    </div>
  );
}

// ═════════════════════════════════════════════════════════════════
// Main panel component (exported).
// ═════════════════════════════════════════════════════════════════
export default function HomeworksImportCenter() {
  const [modal, setModal] = useState(null); // { importer, dryRun }
  const [busy, setBusy] = useState(false);
  const [queuedCount, setQueuedCount] = useState(0);
  const [tickBusy, setTickBusy] = useState(false);

  const refreshQueued = useCallback(async () => {
    let total = 0;
    for (const imp of IMPORTERS) {
      try {
        const r = await api.get(
          `/integrations/homeworks/imports/${imp.slug}/active`,
        );
        total += ((r?.active_runs || []).filter(
          (x) => x.status === "queued")).length;
      } catch { /* silent */ }
    }
    setQueuedCount(total);
  }, []);
  useEffect(() => {
    refreshQueued();
    const t = setInterval(refreshQueued, POLL_INTERVAL_MS);
    return () => clearInterval(t);
  }, [refreshQueued]);

  const runNow = async () => {
    setTickBusy(true);
    try {
      const r = await api.post("/integrations/homeworks/imports/dispatcher/tick");
      if (r?.cooldown) {
        toast.info(`Dispatcher just ran — retry in ${r.retry_in_s}s`);
      } else {
        const s = r?.summary || {};
        toast.success(
          `Dispatcher tick: started ${s.started || 0}, skipped ${s.skipped_concurrency || 0}`,
        );
        refreshQueued();
      }
    } catch (e) { toast.error(e?.message || "Manual tick failed"); }
    finally { setTickBusy(false); }
  };

  const onLaunch = (importer, dryRun) => setModal({ importer, dryRun });
  const cancel = () => { if (!busy) setModal(null); };
  const confirm = async () => {
    if (!modal?.importer) return;
    setBusy(true);
    try {
      const r = await api.post(
        `/integrations/homeworks/imports/${modal.importer.slug}/run`,
      );
      toast.success(
        `Run queued (id ${String(r?.run_id || "").slice(0, 8)}). Launch the operator process to begin processing.`,
      );
      setModal(null);
    } catch (e) {
      const msg = e?.message || "";
      if (msg.includes("dry_run_required_within_15_minutes_before_run")) {
        toast.error("Dry-run expired — please re-run before queuing.");
      } else if (msg.includes("not_implemented")) {
        toast.error("This importer isn't implemented yet — coming next.");
      } else {
        toast.error(msg || "Failed to queue run");
      }
    } finally { setBusy(false); }
  };

  return (
    <div
      className="rounded-2xl p-4 space-y-3"
      style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
      data-testid="homeworks-import-center"
    >
      <div className="flex items-center gap-2 mb-1">
        <ImportIcon size={16} style={{ color: colors.onSurface }} />
        <div className="font-bold text-base flex-1" style={{ color: colors.onSurface }}>
          Homeworks Import Center
        </div>
        {/* Task 5 · Feb-2026 — Manual "Run now" trigger. Only
            surfaces when the tenant has queued runs waiting. */}
        {queuedCount > 0 ? (
          <button
            type="button"
            onClick={runNow}
            disabled={tickBusy}
            className="text-xs font-semibold px-3 py-1.5 rounded-lg inline-flex items-center gap-1.5 text-white disabled:opacity-60"
            style={{ backgroundColor: colors.brandSecondary }}
            data-testid="homeworks-import-run-now-btn"
            title={`Runs the dispatcher immediately instead of waiting up to 30s. ${queuedCount} run${queuedCount === 1 ? "" : "s"} queued.`}
          >
            <Zap size={12} />
            {tickBusy ? "Running…" : `Run now (${queuedCount})`}
          </button>
        ) : null}
      </div>
      <p className="text-xs" style={{ color: colors.muted }}>
        Super-admin only. Each button opens a dry-run preview before
        queuing anything. Runs stream progress in place via polling.
      </p>

      <div className="space-y-2">
        {IMPORTERS.map((imp) => (
          <ImporterRow key={imp.key} importer={imp} onLaunch={onLaunch} />
        ))}
      </div>

      <ConfirmRunModal
        importer={modal?.importer}
        dryRun={modal?.dryRun}
        onCancel={cancel}
        onConfirm={confirm}
        busy={busy}
      />
    </div>
  );
}
