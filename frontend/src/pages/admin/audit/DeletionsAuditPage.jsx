/**
 * Feb-2026 · Item 3 — Deletions audit page (super_admin only).
 *
 * Route: /admin/audit/deletions
 *
 * Table view of ``db.deletion_audit`` entries with:
 *   • Resource-type filter (all / invoice / payment)
 *   • Date-range filter (ISO strings, inclusive)
 *   • Per-row "Restore" button — typed-confirm required to reverse
 *     the soft-delete.
 *   • Snapshot inspector (expanded row) — read-only JSON view of
 *     the pre-delete state (surfaces stripe_reconciliation_note,
 *     deletion_reason).
 */
import React from "react";
import { toast } from "sonner";
import {
  ShieldCheck, RotateCcw, Search as SearchIcon, ChevronDown, ChevronRight,
  Loader2, AlertTriangle,
} from "lucide-react";

import { api } from "@/api";


const RESOURCE_TYPES = [
  { value: "", label: "All" },
  { value: "invoice", label: "Invoices" },
  { value: "payment", label: "Payments" },
];


export default function DeletionsAuditPage() {
  const [rows, setRows] = React.useState([]);
  const [count, setCount] = React.useState(0);
  const [loading, setLoading] = React.useState(true);
  const [resourceType, setResourceType] = React.useState("");
  const [startDate, setStartDate] = React.useState("");
  const [endDate, setEndDate] = React.useState("");
  const [expanded, setExpanded] = React.useState(() => new Set());
  const [restoreTarget, setRestoreTarget] = React.useState(null);
  const [_restoreTypedText, setRestoreTypedText] = React.useState("");
  const [restoreBusy, setRestoreBusy] = React.useState(false);

  const reload = React.useCallback(async () => {
    setLoading(true);
    const qs = new URLSearchParams();
    if (resourceType) qs.set("resource_type", resourceType);
    if (startDate) qs.set("start", startDate);
    if (endDate) qs.set("end", endDate);
    try {
      const r = await api.get(`/admin/audit/deletions${qs.toString() ? "?" + qs.toString() : ""}`);
      setRows(r?.rows || []);
      setCount(r?.count || 0);
    } catch (e) {
      toast.error(e?.message || "Failed to load audit log");
      setRows([]);
      setCount(0);
    } finally {
      setLoading(false);
    }
  }, [resourceType, startDate, endDate]);

  React.useEffect(() => { reload(); }, [reload]);

  const toggleExpanded = (id) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const openRestore = (row) => {
    setRestoreTarget(row);
    setRestoreTypedText("");
  };

  const runRestore = async () => {
    if (!restoreTarget) return;
    // Feb-2026 · Type-to-confirm friction removed app-wide. The
    // ``restoreTypedText`` state is kept for API back-compat but
    // ignored — a click on Restore inside the modal is the sole
    // gate (open modal → click Restore).
    setRestoreBusy(true);
    try {
      await api.post(
        `/admin/audit/deletions/${restoreTarget.id}/restore`, {},
      );
      toast.success(
        `${restoreTarget.resource_type === "payment" ? "Payment" : "Invoice"} restored`,
      );
      setRestoreTarget(null);
      setRestoreTypedText("");
      await reload();
    } catch (e) {
      toast.error(e?.message || "Restore failed");
    } finally {
      setRestoreBusy(false);
    }
  };

  return (
    <div className="p-4 md:p-8 max-w-7xl mx-auto space-y-4"
         data-testid="deletions-audit-page">
      <header className="flex items-start gap-3">
        <div
          className="w-11 h-11 rounded-2xl flex items-center justify-center shrink-0"
          style={{ background: "#0F172A", color: "#F8FAFC" }}
        >
          <ShieldCheck size={20} />
        </div>
        <div className="flex-1">
          <h1 className="text-2xl font-bold text-slate-900"
              data-testid="deletions-audit-title">
            Deletion audit
          </h1>
          <p className="text-sm text-slate-500">
            Every soft-delete of an invoice or payment is logged here
            with a snapshot of the pre-delete row. Only super_admin
            sees this surface. Restore reverses the delete + writes
            an audit entry.
          </p>
        </div>
      </header>

      {/* Filters */}
      <section className="rounded-2xl border border-slate-200 bg-white p-4">
        <div className="flex flex-wrap gap-3 items-end">
          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-1">
              Resource type
            </label>
            <select
              value={resourceType}
              onChange={(e) => setResourceType(e.target.value)}
              className="rounded-md border border-slate-300 px-3 py-2 text-sm"
              data-testid="deletions-audit-filter-type"
            >
              {RESOURCE_TYPES.map((rt) => (
                <option key={rt.value} value={rt.value}>{rt.label}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-1">
              Start date (ISO)
            </label>
            <input
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="rounded-md border border-slate-300 px-3 py-2 text-sm"
              data-testid="deletions-audit-filter-start"
            />
          </div>
          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-1">
              End date (ISO)
            </label>
            <input
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              className="rounded-md border border-slate-300 px-3 py-2 text-sm"
              data-testid="deletions-audit-filter-end"
            />
          </div>
          <button
            type="button"
            onClick={reload}
            disabled={loading}
            className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-semibold text-white disabled:opacity-60"
            style={{ backgroundColor: "#0F172A" }}
            data-testid="deletions-audit-refresh"
          >
            {loading ? <Loader2 size={14} className="animate-spin" /> : <SearchIcon size={14} />}
            Refresh
          </button>
          <div className="text-xs font-semibold text-slate-500 ml-auto"
               data-testid="deletions-audit-count">
            {count} entries
          </div>
        </div>
      </section>

      {/* Table */}
      <section className="rounded-2xl border border-slate-200 bg-white overflow-hidden">
        {loading ? (
          <div className="p-6 text-sm text-slate-500 flex items-center gap-2">
            <Loader2 size={14} className="animate-spin" /> Loading…
          </div>
        ) : rows.length === 0 ? (
          <div className="p-6 text-sm text-slate-500"
               data-testid="deletions-audit-empty">
            No deletions in this range.
          </div>
        ) : (
          <table className="w-full text-sm" data-testid="deletions-audit-table">
            <thead>
              <tr className="bg-slate-50 text-slate-600 text-xs">
                <th className="w-8"></th>
                <th className="text-left px-3 py-2 font-semibold">Timestamp</th>
                <th className="text-left px-3 py-2 font-semibold">Type</th>
                <th className="text-left px-3 py-2 font-semibold">Resource</th>
                <th className="text-left px-3 py-2 font-semibold">Action</th>
                <th className="text-left px-3 py-2 font-semibold">Actor</th>
                <th className="text-left px-3 py-2 font-semibold">Reason</th>
                <th className="text-right px-3 py-2 font-semibold">Restore</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <React.Fragment key={row.id}>
                  <tr
                    className="border-t border-slate-100"
                    data-testid={`deletions-audit-row-${row.id}`}
                  >
                    <td className="px-2 py-2">
                      <button
                        type="button"
                        onClick={() => toggleExpanded(row.id)}
                        aria-label="Toggle snapshot"
                        data-testid={`deletions-audit-expand-${row.id}`}
                      >
                        {expanded.has(row.id)
                          ? <ChevronDown size={14} />
                          : <ChevronRight size={14} />}
                      </button>
                    </td>
                    <td className="px-3 py-2 font-mono text-xs">
                      {row.timestamp}
                    </td>
                    <td className="px-3 py-2 text-xs font-semibold uppercase">
                      {row.resource_type}
                    </td>
                    <td className="px-3 py-2 font-mono text-xs">
                      {String(row.resource_id || "").slice(0, 8)}
                    </td>
                    <td className="px-3 py-2 text-xs">
                      {row.action}
                    </td>
                    <td className="px-3 py-2 text-xs text-slate-500">
                      {row.user_email || row.user_id || "—"}
                    </td>
                    <td className="px-3 py-2 text-xs text-slate-500">
                      {row.deletion_reason || "—"}
                    </td>
                    <td className="px-3 py-2 text-right">
                      {row.action === "delete" ? (
                        <button
                          type="button"
                          onClick={() => openRestore(row)}
                          className="inline-flex items-center gap-1.5 px-2 py-1 rounded-md text-xs font-semibold border border-slate-300"
                          data-testid={`deletions-audit-restore-btn-${row.id}`}
                        >
                          <RotateCcw size={12} /> Restore
                        </button>
                      ) : (
                        <span className="text-xs text-slate-400">(reverted)</span>
                      )}
                    </td>
                  </tr>
                  {expanded.has(row.id) ? (
                    <tr className="border-t border-slate-100 bg-slate-50">
                      <td colSpan={8} className="px-4 py-3">
                        {row.stripe_reconciliation_note ? (
                          <div
                            className="mb-3 p-2 rounded-md flex items-start gap-2 text-xs"
                            style={{ backgroundColor: "#FEF3C7", color: "#92400E",
                                       border: "1px solid #FDE68A" }}
                            data-testid={`deletions-audit-stripe-note-${row.id}`}
                          >
                            <AlertTriangle size={12} />
                            <div>
                              <b>Stripe reconciliation:</b>{" "}
                              {row.stripe_reconciliation_note}
                            </div>
                          </div>
                        ) : null}
                        <div className="text-xs font-semibold text-slate-700 mb-1">
                          Snapshot (pre-delete row):
                        </div>
                        <pre
                          className="text-[11px] rounded-md p-3 overflow-auto max-h-64"
                          style={{ backgroundColor: "#0F172A", color: "#E2E8F0" }}
                          data-testid={`deletions-audit-snapshot-${row.id}`}
                        >
                          {JSON.stringify(row.snapshot || {}, null, 2)}
                        </pre>
                      </td>
                    </tr>
                  ) : null}
                </React.Fragment>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {/* Restore typed-confirm modal */}
      {restoreTarget ? (
        <div
          className="fixed inset-0 z-[60] flex items-center justify-center p-4"
          style={{ background: "rgba(15,23,42,0.55)" }}
          onMouseDown={() => setRestoreTarget(null)}
          data-testid="deletions-audit-restore-modal"
        >
          <div
            onMouseDown={(e) => e.stopPropagation()}
            className="w-full max-w-md rounded-2xl overflow-hidden bg-white border border-slate-200"
          >
            <div className="px-5 py-4">
              <h3 className="text-lg font-bold text-slate-900">
                Restore this {restoreTarget.resource_type}?
              </h3>
              <p className="text-sm text-slate-500 mt-1">
                {restoreTarget.resource_type === "payment"
                  ? "Restores payment_status + amount_paid from the pre-delete snapshot."
                  : "Clears deleted_at + deleted_by. Any cascade payments recorded on this entry are also restored."}
              </p>
              <p className="text-sm text-slate-500 mt-3">
                {/* Feb-2026 · Type-to-confirm removed — click Restore
                    below to reverse the soft-delete. */}
                Click <b>Restore</b> below to reverse the soft-delete.
              </p>
            </div>
            <div className="px-5 py-3 flex items-center justify-end gap-2 border-t border-slate-200 bg-slate-50">
              <button
                type="button"
                onClick={() => setRestoreTarget(null)}
                className="px-3 py-2 rounded-lg text-sm font-semibold border border-slate-300 text-slate-700"
                data-testid="deletions-audit-restore-cancel"
              >Cancel</button>
              <button
                type="button"
                onClick={runRestore}
                disabled={restoreBusy}
                className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-bold text-white disabled:opacity-60"
                style={{ backgroundColor: "#0F172A" }}
                data-testid="deletions-audit-restore-confirm"
              >
                {restoreBusy ? <Loader2 size={14} className="animate-spin" /> : <RotateCcw size={14} />}
                {restoreBusy ? "Restoring…" : "Restore"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
