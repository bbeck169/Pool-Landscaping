/**
 * Feb-2026 · Admin Observability Bundle · F9 tile + F5 sentinel reset.
 *
 * At-a-glance surface for super_admins showing the current F3/F6/F2
 * data-integrity state. Fetches ``GET /admin/data-repair/status``
 * (see ``backend/routers/data_repair.py``) and renders one of two
 * pills:
 *
 *   • Red   "DATA INTEGRITY ATTENTION" — dangling_refs_total > 0
 *          OR log_only_mode_active === true
 *   • Green "OK"                       — otherwise
 *
 * Also exposes the F5 sentinel reset button (super_admin only). The
 * reset POSTs ``/admin/migrations/f5-leads-backfill/reset`` behind a
 * shadcn AlertDialog confirm (no type-to-confirm — matches sitewide
 * removal), then surfaces a sonner toast on success.
 *
 * Testids (E2E):
 *   admin-data-integrity-tile
 *   admin-data-integrity-pill
 *   admin-data-integrity-summary
 *   admin-f5-reset-btn
 *   admin-f5-reset-confirm
 *   admin-f5-reset-cancel
 *   admin-f5-reset-dialog
 */
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { api } from "@/api";
import { colors } from "@/theme";
import { AlertTriangle, CheckCircle2, RefreshCw, ShieldAlert } from "lucide-react";
import DashboardDrillDownModal from "@/components/dashboard/DashboardDrillDownModal";


function _isAttention(status) {
  if (!status) return false;
  const cs = status.current_state || {};
  const total = Number(cs.dangling_refs_total || 0);
  return total > 0 || cs.log_only_mode_active === true;
}


function StatCell({ label, value, tone, onClick, testid }) {
  const fg =
    tone === "danger" ? colors.error :
    tone === "warn"   ? colors.warning :
    tone === "ok"     ? colors.success :
                        colors.onSurface;
  const clickable = typeof onClick === "function";
  return (
    <div
      role={clickable ? "button" : undefined}
      tabIndex={clickable ? 0 : undefined}
      data-testid={testid}
      onClick={clickable ? onClick : undefined}
      onKeyDown={
        clickable
          ? (e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onClick();
              }
            }
          : undefined
      }
      className={clickable ? "cursor-pointer transition-transform hover:-translate-y-0.5 focus:outline-none focus:ring-2 focus:ring-blue-400" : ""}
      style={{
        backgroundColor: colors.surfaceSecondary,
        border: `1px solid ${colors.border}`,
        borderRadius: 8,
        padding: "8px 12px",
      }}
    >
      <div
        className="text-[10px] font-bold uppercase tracking-wider"
        style={{ color: colors.muted }}
      >
        {label}
      </div>
      <div className="text-sm font-semibold mt-0.5" style={{ color: fg }}>
        {value}
      </div>
    </div>
  );
}


export default function DataIntegrityTile({ userRole }) {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [resetting, setResetting] = useState(false);
  // Phase K41 · Feb-2026 — drill-down modal state.
  const [drillClass, setDrillClass] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const r = await api.get("/admin/data-repair/status");
      setStatus(r);
    } catch (e) {
      setError(e?.message || "Failed to load data integrity status");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const attention = _isAttention(status);
  const cs = status?.current_state || {};
  const byClass = cs.dangling_refs_by_class || {};
  const total = Number(cs.dangling_refs_total || 0);

  const runReset = async () => {
    setResetting(true);
    try {
      const r = await api.post(
        "/admin/migrations/f5-leads-backfill/reset",
        {},
      );
      const deleted = Number(r?.deleted_count || 0);
      toast.success(
        deleted > 0
          ? `F5 sentinel cleared. The leads-backfill migration will re-arm on the next boot.`
          : `No F5 sentinel was present. Already re-armed.`,
        { duration: 5000 },
      );
      setConfirmOpen(false);
      // Refresh status so any downstream signals update.
      await load();
    } catch (e) {
      toast.error(e?.message || "F5 reset failed");
    } finally {
      setResetting(false);
    }
  };

  const canReset = userRole === "super_admin";

  return (
    <div
      className="rounded-2xl p-5 mb-4"
      style={{
        backgroundColor: colors.surface,
        border: `1px solid ${attention ? colors.error : colors.border}`,
        borderLeft: `4px solid ${attention ? colors.error : colors.success}`,
      }}
      data-testid="admin-data-integrity-tile"
    >
      <div className="flex items-start justify-between gap-3 mb-3 flex-wrap">
        <div className="flex items-center gap-2 min-w-0">
          <ShieldAlert
            size={20}
            color={attention ? colors.error : colors.success}
          />
          <div className="min-w-0">
            <div
              className="text-lg font-semibold"
              style={{ color: colors.onSurface }}
            >
              Data Integrity
            </div>
            <div className="text-xs" style={{ color: colors.muted }}>
              F3 boot check · F6 diagnostic dumps · F2 repair state
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span
            className="inline-flex items-center gap-1.5 text-[11px] font-bold px-2.5 py-1 rounded-full uppercase tracking-wider"
            style={{
              backgroundColor: attention ? "#FEE2E2" : "#DCFCE7",
              color: attention ? "#991B1B" : "#166534",
              border: `1px solid ${attention ? "#FCA5A5" : "#86EFAC"}`,
            }}
            data-testid="admin-data-integrity-pill"
            data-state={attention ? "attention" : "ok"}
          >
            {attention ? (
              <>
                <AlertTriangle size={12} />
                Data Integrity Attention
              </>
            ) : (
              <>
                <CheckCircle2 size={12} />
                OK
              </>
            )}
          </span>
          <button
            type="button"
            onClick={load}
            disabled={loading}
            className="text-xs font-semibold px-2 py-1 rounded-lg disabled:opacity-40"
            style={{
              backgroundColor: colors.surfaceSecondary,
              color: colors.onSurfaceSecondary,
              border: `1px solid ${colors.border}`,
            }}
            data-testid="admin-data-integrity-refresh"
            aria-label="Refresh data integrity status"
            title="Refresh"
          >
            <RefreshCw size={12} className={loading ? "animate-spin" : ""} />
          </button>
        </div>
      </div>

      {error ? (
        <div
          className="text-sm mt-1 mb-3 p-2 rounded-md"
          style={{ background: "#FEE2E2", color: "#991B1B" }}
          data-testid="admin-data-integrity-error"
        >
          {error}
        </div>
      ) : null}

      {status ? (
        <>
          <div
            className="grid grid-cols-2 sm:grid-cols-4 gap-2"
            data-testid="admin-data-integrity-summary"
          >
            <StatCell
              label="Dangling refs"
              value={total}
              tone={total > 0 ? "danger" : "ok"}
              onClick={total > 0 ? () => setDrillClass("orphaned_customer_refs") : undefined}
              testid="admin-data-integrity-drill-total"
            />
            <StatCell
              label="Customer / Tech / Crew"
              value={`${byClass.customer || 0} / ${byClass.technician || 0} / ${byClass.crew || 0}`}
              tone={total > 0 ? "danger" : undefined}
              onClick={() => setDrillClass("orphaned_customer_refs")}
              testid="admin-data-integrity-drill-byclass"
            />
            <StatCell
              label="Enforce mode"
              value={cs.enforce_mode === false ? "LOG-ONLY" : "ENFORCE"}
              tone={cs.log_only_mode_active ? "warn" : "ok"}
            />
            <StatCell
              label="Snapshot"
              value={
                cs.snapshot_source === "integrity_dump_file"
                  ? (String(cs.snapshot_at || "").slice(0, 19).replace("T", " · "))
                  : "No dump on disk"
              }
            />
          </div>

          {status.last_dry_run ? (
            <div
              className="text-xs mt-3 rounded-lg px-3 py-2"
              style={{
                backgroundColor: colors.surfaceSecondary,
                color: colors.onSurfaceSecondary,
                border: `1px solid ${colors.border}`,
              }}
              data-testid="admin-data-integrity-last-dry-run"
            >
              <span style={{ color: colors.muted }}>Last dry-run:</span>{" "}
              <b>{status.last_dry_run.total_would_change}</b> would change ·{" "}
              <b>{status.last_dry_run.total_flagged_no_action}</b> flagged ·{" "}
              {status.last_dry_run.scan_timestamp?.slice(0, 19).replace("T", " ")}
            </div>
          ) : null}

          {status.last_apply ? (
            <div
              className="text-xs mt-2 rounded-lg px-3 py-2"
              style={{
                backgroundColor: colors.surfaceSecondary,
                color: colors.onSurfaceSecondary,
                border: `1px solid ${colors.border}`,
              }}
              data-testid="admin-data-integrity-last-apply"
            >
              <span style={{ color: colors.muted }}>Last repair run:</span>{" "}
              <b>{status.last_apply.changes_applied ?? "—"}</b> changes ·{" "}
              run_id{" "}
              <code style={{ fontFamily: "monospace" }}>
                {String(status.last_apply.run_id || "").slice(0, 8)}
              </code>{" "}
              · {status.last_apply.run_timestamp?.slice(0, 19).replace("T", " ")}
            </div>
          ) : null}
        </>
      ) : loading ? (
        <div className="text-sm" style={{ color: colors.muted }}>
          Loading…
        </div>
      ) : null}

      {canReset ? (
        <div
          className="mt-4 flex flex-wrap items-center gap-3"
          data-testid="admin-f5-reset-row"
        >
          <div className="text-xs" style={{ color: colors.muted }}>
            Re-arm the F5 leads-backfill migration by clearing its
            sentinel row. Idempotent · audit-logged.
          </div>
          <button
            type="button"
            onClick={() => setConfirmOpen(true)}
            className="text-xs font-semibold px-3 py-1.5 rounded-lg"
            style={{
              backgroundColor: colors.brand,
              color: "#fff",
            }}
            data-testid="admin-f5-reset-btn"
          >
            Reset F5 sentinel
          </button>
        </div>
      ) : null}

      <AlertDialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <AlertDialogContent data-testid="admin-f5-reset-dialog">
          <AlertDialogHeader>
            <AlertDialogTitle>Reset F5 sentinel?</AlertDialogTitle>
            <AlertDialogDescription>
              This deletes the <code>f5_leads_backfill_v1</code> row
              from <code>migration_status</code>. The leads-backfill
              migration will re-run on the next backend boot or
              scheduled sweep. The action is idempotent and every
              call is logged to <code>audit_events</code> with your
              user id and timestamp.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel
              disabled={resetting}
              data-testid="admin-f5-reset-cancel"
            >
              Cancel
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={(e) => { e.preventDefault(); runReset(); }}
              disabled={resetting}
              data-testid="admin-f5-reset-confirm"
            >
              {resetting ? "Resetting…" : "Reset sentinel"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Phase K41 · Feb-2026 — drill-down modal for dangling refs. */}
      <DashboardDrillDownModal
        open={!!drillClass}
        onClose={() => setDrillClass(null)}
        variant="data-integrity"
        params={{ issueClass: drillClass || "orphaned_customer_refs" }}
      />
    </div>
  );
}
