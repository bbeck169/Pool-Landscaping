/**
 * Phase 11 · Feb-2026 — Recurring labor costs admin page.
 *
 * ``/admin/recurring-labor-costs`` route. ``AdminOnly`` wrapper +
 * server-side ``require_admin`` + explicit role-set guard on the
 * recurring_labor_costs router cover the role matrix (admin /
 * super_admin / owner write; manager read-only; tech / customer
 * 403).
 *
 * Page shape:
 *   * Header + "New" button → opens the create modal.
 *   * Table of entries (label / monthly / start / end / status /
 *     action menu).
 *   * Row click or Edit affordance → opens the edit modal with
 *     fields pre-populated.
 *   * Inactivate action = soft delete (DELETE /{id}) with a
 *     confirmation prompt.
 *   * Decimal input reuses the Phase 10 chemistry-decimals
 *     primitive at ``@/components/common/DecimalInput``.
 */
import React, { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { api } from "@/api";
import DecimalInput from "@/components/common/DecimalInput";
import { colors } from "@/theme";


function _money(v) {
  const n = Number.parseFloat(v);
  if (!Number.isFinite(n)) return "—";
  return `$${n.toLocaleString(undefined, {
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  })}`;
}


function RecurringLaborCostModal({ initial, onClose, onSaved }) {
  const isEdit = !!initial?.id;
  const [label, setLabel] = useState(initial?.label || "");
  const [monthly, setMonthly] = useState(
    initial?.monthly_amount ? String(initial.monthly_amount) : "");
  const [startDate, setStartDate] = useState(initial?.start_date || "");
  const [endDate, setEndDate] = useState(initial?.end_date || "");
  const [status, setStatus] = useState(initial?.status || "active");
  const [notes, setNotes] = useState(initial?.notes || "");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true);
    try {
      const _fmtMoney = (v) => {
        if (v === "" || v == null) return undefined;
        const n = typeof v === "number" ? v : Number.parseFloat(v);
        if (!Number.isFinite(n)) return undefined;
        return n.toFixed(2);
      };
      const payload = {
        label: label.trim(),
        monthly_amount: _fmtMoney(monthly),
        start_date: startDate || undefined,
        end_date: endDate || null,
        status,
        notes: notes.trim() || null,
      };
      if (isEdit) {
        await api.patch(`/recurring-labor-costs/${initial.id}`, payload);
      } else {
        await api.post("/recurring-labor-costs", payload);
      }
      toast.success(isEdit ? "Entry updated" : "Entry created");
      onSaved?.();
    } catch (e) {
      toast.error(e?.message || "Save failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ backgroundColor: "rgba(0,0,0,0.5)" }}
      role="dialog"
      aria-modal="true"
      data-testid="recurring-labor-cost-modal"
    >
      <div
        className="rounded-xl w-full max-w-md p-5 overflow-y-auto"
        style={{
          backgroundColor: colors.surface,
          border: `1px solid ${colors.border}`,
          maxHeight: "90vh",
        }}
      >
        <div className="text-lg font-semibold mb-4"
             style={{ color: colors.onSurface }}>
          {isEdit ? "Edit recurring labor cost" : "New recurring labor cost"}
        </div>
        <div className="space-y-3">
          <div>
            <label className="block text-sm font-medium mb-1"
                   style={{ color: colors.onSurface }}>Label</label>
            <input
              type="text"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="e.g. Office Manager — Jane Smith"
              className="w-full px-3 py-2 rounded-md border text-sm"
              style={{ borderColor: colors.border,
                       backgroundColor: colors.background,
                       color: colors.onSurface }}
              data-testid="rlc-label-input"
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1"
                   style={{ color: colors.onSurface }}>
              Monthly amount ($/mo)
            </label>
            <DecimalInput
              value={monthly}
              onChange={setMonthly}
              placeholder="4500.00"
              className="w-full px-3 py-2 rounded-md border text-sm"
              style={{ borderColor: colors.border,
                       backgroundColor: colors.background,
                       color: colors.onSurface }}
              data-testid="rlc-monthly-input"
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-sm font-medium mb-1"
                     style={{ color: colors.onSurface }}>Start date</label>
              <input
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
                className="w-full px-3 py-2 rounded-md border text-sm"
                style={{ borderColor: colors.border,
                         backgroundColor: colors.background,
                         color: colors.onSurface }}
                data-testid="rlc-start-date-input"
              />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1"
                     style={{ color: colors.onSurface }}>
                End date <span className="text-xs"
                                 style={{ color: colors.muted }}>(optional)</span>
              </label>
              <input
                type="date"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
                className="w-full px-3 py-2 rounded-md border text-sm"
                style={{ borderColor: colors.border,
                         backgroundColor: colors.background,
                         color: colors.onSurface }}
                data-testid="rlc-end-date-input"
              />
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium mb-1"
                   style={{ color: colors.onSurface }}>Status</label>
            <select
              value={status}
              onChange={(e) => setStatus(e.target.value)}
              className="w-full px-3 py-2 rounded-md border text-sm"
              style={{ borderColor: colors.border,
                       backgroundColor: colors.background,
                       color: colors.onSurface }}
              data-testid="rlc-status-select"
            >
              <option value="active">Active</option>
              <option value="inactive">Inactive</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium mb-1"
                   style={{ color: colors.onSurface }}>Notes</label>
            <textarea
              rows={2}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              className="w-full px-3 py-2 rounded-md border text-sm"
              style={{ borderColor: colors.border,
                       backgroundColor: colors.background,
                       color: colors.onSurface }}
              data-testid="rlc-notes-input"
            />
          </div>
        </div>
        <div className="flex justify-end gap-2 mt-5">
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="px-3 py-2 rounded-md text-sm"
            style={{ backgroundColor: "transparent", color: colors.muted,
                     border: `1px solid ${colors.border}` }}
            data-testid="rlc-modal-cancel-btn"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={busy}
            className="px-3 py-2 rounded-md text-sm font-semibold"
            style={{ backgroundColor: colors.brandPrimary,
                     color: colors.onBrandPrimary || "#FFFFFF",
                     opacity: busy ? 0.6 : 1 }}
            data-testid="rlc-modal-save-btn"
          >
            {busy ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}


export default function RecurringLaborCostsPage() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editTarget, setEditTarget] = useState(null);
  const [showNew, setShowNew] = useState(false);

  const refresh = async () => {
    setLoading(true);
    try {
      const r = await api.get("/recurring-labor-costs?include_inactive=true");
      setRows(Array.isArray(r) ? r : []);
    } catch (e) {
      toast.error(e?.message || "Failed to load entries");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const inactivate = async (row) => {
    const ok = window.confirm(
      `Mark "${row.label}" inactive? It will stop contributing to future `
      + `EBIT windows but prior consumed snapshots are unaffected.`);
    if (!ok) return;
    try {
      await api.delete(`/recurring-labor-costs/${row.id}`);
      toast.success("Entry inactivated");
      refresh();
    } catch (e) {
      toast.error(e?.message || "Failed to inactivate");
    }
  };

  const activeCount = useMemo(
    () => rows.filter((r) => r.status === "active").length,
    [rows],
  );

  return (
    <div className="p-6" data-testid="recurring-labor-costs-page">
      <div className="flex items-center justify-between mb-4">
        <div>
          <div className="text-2xl font-bold"
               style={{ color: colors.onSurface }}>
            Recurring labor costs
          </div>
          <div className="text-sm mt-1" style={{ color: colors.muted }}>
            Salaried / contracted / fixed-monthly labor. Prorates
            into each EBIT window by average month length
            (30.4375 days).
          </div>
        </div>
        <button
          type="button"
          onClick={() => setShowNew(true)}
          className="px-3 py-2 rounded-md text-sm font-semibold"
          style={{ backgroundColor: colors.brandPrimary,
                   color: colors.onBrandPrimary || "#FFFFFF" }}
          data-testid="rlc-new-btn"
        >
          + New
        </button>
      </div>

      <div className="text-xs mb-3" style={{ color: colors.muted }}>
        {loading ? "Loading…" : `${activeCount} active · ${rows.length} total`}
      </div>

      {!loading && rows.length === 0 ? (
        <div
          className="rounded-md p-6 text-center text-sm"
          style={{ backgroundColor: colors.surface,
                   border: `1px dashed ${colors.border}`,
                   color: colors.muted }}
          data-testid="rlc-empty-state"
        >
          No recurring labor costs yet. Click “+ New” to add one.
        </div>
      ) : (
        <div
          className="rounded-md overflow-hidden"
          style={{ border: `1px solid ${colors.border}` }}
        >
          <table className="w-full text-sm">
            <thead>
              <tr style={{ backgroundColor: colors.background }}>
                <th className="text-left px-3 py-2"
                    style={{ color: colors.muted }}>Label</th>
                <th className="text-right px-3 py-2"
                    style={{ color: colors.muted }}>Monthly</th>
                <th className="text-left px-3 py-2"
                    style={{ color: colors.muted }}>Start</th>
                <th className="text-left px-3 py-2"
                    style={{ color: colors.muted }}>End</th>
                <th className="text-left px-3 py-2"
                    style={{ color: colors.muted }}>Status</th>
                <th className="text-right px-3 py-2"
                    style={{ color: colors.muted }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr
                  key={r.id}
                  style={{
                    borderTop: `1px solid ${colors.border}`,
                    opacity: r.status === "inactive" ? 0.55 : 1,
                  }}
                  data-testid={`rlc-row-${r.id}`}
                >
                  <td className="px-3 py-2"
                      style={{ color: colors.onSurface }}>{r.label}</td>
                  <td className="px-3 py-2 text-right tabular-nums"
                      style={{ color: colors.onSurface }}>
                    {_money(r.monthly_amount)}
                  </td>
                  <td className="px-3 py-2"
                      style={{ color: colors.onSurface }}>{r.start_date}</td>
                  <td className="px-3 py-2"
                      style={{ color: colors.onSurface }}>
                    {r.end_date || <span style={{ color: colors.muted }}>ongoing</span>}
                  </td>
                  <td className="px-3 py-2 capitalize"
                      style={{ color: r.status === "active"
                               ? colors.brandPrimary : colors.muted }}>
                    {r.status}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <button
                      type="button"
                      onClick={() => setEditTarget(r)}
                      className="px-2 py-1 rounded text-xs mr-2"
                      style={{ color: colors.brandPrimary,
                               border: `1px solid ${colors.border}` }}
                      data-testid={`rlc-row-edit-btn-${r.id}`}
                    >
                      Edit
                    </button>
                    {r.status === "active" ? (
                      <button
                        type="button"
                        onClick={() => inactivate(r)}
                        className="px-2 py-1 rounded text-xs"
                        style={{ color: "#DC2626",
                                 border: `1px solid ${colors.border}` }}
                        data-testid={`rlc-row-inactivate-btn-${r.id}`}
                      >
                        Inactivate
                      </button>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showNew ? (
        <RecurringLaborCostModal
          initial={null}
          onClose={() => setShowNew(false)}
          onSaved={() => { setShowNew(false); refresh(); }}
        />
      ) : null}
      {editTarget ? (
        <RecurringLaborCostModal
          initial={editTarget}
          onClose={() => setEditTarget(null)}
          onSaved={() => { setEditTarget(null); refresh(); }}
        />
      ) : null}
    </div>
  );
}
