/**
 * Task OO · Feb 2026 — Admin Service Reports list.
 * Exposes /service-reports/bulk-delete + /service-reports/bulk-update.
 * Locked-state: rows with evidence_invoice_id refuse hard delete.
 */
import React, { useEffect, useMemo, useState } from "react";
import { ClipboardList, RefreshCw, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api";
import { colors } from "@/theme";
import HardDeleteModal from "@/components/hard_delete/HardDeleteModal";
import {
  useBulkSelect, BulkSelectAll, BulkSelectRow,
  BulkActionBar, BulkConfirmModal, LockedPill,
} from "@/components/bulk-select/BulkSelectToolkit";

export default function AdminServiceReportsList() {
  const [rows, setRows] = useState(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [lockedFailures, setLockedFailures] = useState({});
  // HARD-DELETE · HD-B · Feb-2026 — per-row "Move to Trash" modal.
  const [trashTarget, setTrashTarget] = useState(null);
  const load = () => api.get("/service-reports")
    .then((r) => setRows(Array.isArray(r) ? r : (r?.reports || r?.items || [])))
    .catch(() => setRows([]));
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const visibleIds = useMemo(() => (rows || []).map((r) => r.id), [rows]);
  const { selected, selectedCount, allVisibleSelected, indeterminate,
             toggleAll, toggleOne, clear } = useBulkSelect(visibleIds);
  const applyFailures = (failed) => {
    if (!failed?.length) return;
    const map = {}; failed.forEach((f) => { map[f.id] = f.reason; });
    setLockedFailures(map); setTimeout(() => setLockedFailures({}), 10000);
  };
  const doBulkDelete = async () => {
    setBusy(true);
    try {
      const res = await api.post("/service-reports/bulk-delete", { ids: Array.from(selected) });
      applyFailures(res.failed);
      const okC = res.deleted_count || 0;
      const failC = (res.failed || []).length;
      if (failC === 0) toast.success(`${okC} report${okC === 1 ? "" : "s"} deleted`);
      else toast(`${okC} deleted · ${failC} locked`, {
        description: (res.failed || []).slice(0, 3).map((f) => f.reason).join(" · "),
      });
      clear(); setConfirmOpen(false); load();
    } catch (e) { toast.error(e?.message || "Bulk delete failed"); }
    finally { setBusy(false); }
  };
  const doBulkVisibility = async (state) => {
    try {
      const res = await api.post("/service-reports/bulk-update", {
        ids: Array.from(selected),
        patch: { is_customer_visible: state === "visible" },
      });
      applyFailures(res.failed);
      toast.success(`${res.updated_count || 0} → ${state}`);
      clear(); load();
    } catch (e) { toast.error(e?.message || "Visibility update failed"); }
  };
  return (
    <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-6" data-testid="admin-service-reports-page">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold" style={{ color: colors.onSurface }}>
            <ClipboardList size={20} className="inline mr-2" /> Service Reports
          </h1>
          <p className="text-xs mt-0.5" style={{ color: colors.muted }}>
            Bulk-manage submitted service reports. Reports referenced as invoice evidence stay locked.
          </p>
        </div>
        <button onClick={load}
                className="text-xs font-semibold px-3 py-2 rounded-lg inline-flex items-center gap-1.5"
                style={{ backgroundColor: colors.surfaceSecondary,
                          color: colors.onSurfaceSecondary,
                          border: `1px solid ${colors.border}` }}
                data-testid="admin-service-reports-refresh-btn">
          <RefreshCw size={12} /> Refresh
        </button>
      </div>
      <div className="rounded-2xl overflow-hidden"
           style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
        <table className="w-full text-sm" data-testid="admin-service-reports-table">
          <thead>
            <tr style={{ backgroundColor: colors.surfaceSecondary }}>
              <th className="px-3 py-2 w-8">
                <BulkSelectAll checked={allVisibleSelected} indeterminate={indeterminate}
                                 onChange={toggleAll} />
              </th>
              <th className="text-left px-3 py-2 font-semibold" style={{ color: colors.onSurfaceSecondary }}>Job / customer</th>
              <th className="text-left px-3 py-2 font-semibold hidden md:table-cell" style={{ color: colors.onSurfaceSecondary }}>Submitted</th>
              <th className="text-left px-3 py-2 font-semibold" style={{ color: colors.onSurfaceSecondary }}>Visibility</th>
              <th className="text-right px-3 py-2 font-semibold" style={{ color: colors.onSurfaceSecondary }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {(rows || []).length === 0 && rows !== null ? (
              <tr><td colSpan={5} className="px-3 py-6 text-center text-sm"
                       style={{ color: colors.muted }} data-testid="admin-service-reports-empty">
                No service reports yet.
              </td></tr>
            ) : null}
            {(rows || []).map((r) => (
              <tr key={r.id}
                  style={{ borderTop: `1px solid ${colors.divider}`,
                            backgroundColor: selected.has(r.id) ? "#EFF6FF" : "transparent" }}
                  data-testid={`admin-service-report-row-${r.id}`}>
                <td className="px-3 py-3">
                  <BulkSelectRow id={r.id} checked={selected.has(r.id)}
                                    onChange={() => toggleOne(r.id)} />
                </td>
                <td className="px-3 py-3 font-semibold" style={{ color: colors.onSurface }}>
                  {r.customer_name || r.job_title || `Job ${(r.job_id || "").slice(0, 8)}`}
                  {r.evidence_invoice_id ? (
                    <span className="ml-2 text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded"
                          style={{ background: "#DBEAFE", color: "#1E3A8A" }}>evidence</span>
                  ) : null}
                  {lockedFailures[r.id] ? (
                    <LockedPill reason={lockedFailures[r.id]}
                                  testid={`bulk-locked-pill-${r.id}`} />
                  ) : null}
                </td>
                <td className="px-3 py-3 hidden md:table-cell text-xs" style={{ color: colors.muted }}>
                  {(r.submitted_at || r.created_at || "").slice(0, 10)}
                </td>
                <td className="px-3 py-3 text-xs" style={{ color: colors.muted }}>
                  {r.is_customer_visible ? "Visible" : "Hidden"}
                </td>
                <td className="px-3 py-3 text-right">
                  <button
                    type="button"
                    onClick={() => setTrashTarget(r)}
                    data-testid={`asr-hard-delete-${r.id}`}
                    className="inline-flex items-center gap-1 px-2 py-1 rounded text-xs font-semibold"
                    style={{
                      background: "#FEF2F2",
                      color: "#B91C1C",
                      border: "1px solid #FECACA",
                    }}
                  >
                    <Trash2 size={12} /> Trash
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <BulkActionBar
        selectedCount={selectedCount}
        onClear={clear}
        actions={[
          { key: "visibility", label: "Change visibility",
            dropdown: [{ value: "visible", label: "Visible" }, { value: "hidden", label: "Hidden" }],
            onClick: (v) => doBulkVisibility(v) },
          { key: "delete", label: "Delete selected", tone: "danger",
            onClick: () => setConfirmOpen(true) },
        ]}
      />
      <BulkConfirmModal
        open={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        onConfirm={doBulkDelete}
        title={`Delete ${selectedCount} report${selectedCount === 1 ? "" : "s"}?`}
        description="Reports referenced by an invoice as evidence will show as locked and be skipped — archive them instead."
        confirmLabel={busy ? "Deleting…" : `Delete ${selectedCount}`}
        busy={busy}
      />
      {/* HARD-DELETE · HD-B · Feb-2026 — per-row "Move to Trash". */}
      {trashTarget ? (
        <HardDeleteModal
          open={!!trashTarget}
          entityType="service_report"
          entityId={trashTarget.id}
          entityLabel={
            trashTarget.customer_name || trashTarget.job_title || `Report ${(trashTarget.id || "").slice(0, 8)}`
          }
          testidPrefix={`asr-hard-delete-modal-${trashTarget.id}`}
          onClose={() => setTrashTarget(null)}
          onSuccess={() => {
            setTrashTarget(null);
            load();
          }}
          onBlocked={() => setTrashTarget(null)}
        />
      ) : null}
    </div>
  );
}
