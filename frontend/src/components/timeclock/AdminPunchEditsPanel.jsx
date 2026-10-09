/**
 * Phase 12 · Feb-2026 — Admin Punch Edits panel.
 *
 * Admin-gated section inside the Landscaping Time Clock page. Allows
 * admin + super_admin (NOT owner, NOT manager, NOT tech) to add,
 * edit, soft-delete, and audit individual timeclock punches for any
 * team member — primary driver is payroll corrections.
 *
 * Data model note: a "punch" at the admin surface = a SHIFT (pair of
 * `in` + optional `out` rows). Backend exposes shift-shape JSON with
 * ``shift_id``, ``clock_in``, ``clock_out``, ``audit_log[]``.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  Clock, Edit, Trash2, Plus, ChevronDown, ChevronRight,
  RefreshCw, AlertCircle,
} from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api";
import { colors } from "@/theme";
import AdminPunchModal from "./AdminPunchModal";


const _ADMIN_ROLES = new Set(["admin", "super_admin"]);


function _todayISO(offset = 0) {
  const d = new Date();
  d.setDate(d.getDate() + offset);
  return d.toISOString().slice(0, 10);
}


function _fmtTs(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString([], {
      month: "short", day: "2-digit",
      hour: "2-digit", minute: "2-digit",
    });
  } catch {
    return iso;
  }
}


function _fmtDuration(ci, co) {
  if (!ci || !co) return "—";
  const a = new Date(ci).getTime();
  const b = new Date(co).getTime();
  if (!Number.isFinite(a) || !Number.isFinite(b)) return "—";
  const s = Math.max(0, Math.floor((b - a) / 1000));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return `${h}h ${String(m).padStart(2, "0")}m`;
}


export default function AdminPunchEditsPanel({ viewer, teamMembers }) {
  const role = String(viewer?.role || "").toLowerCase();
  if (!_ADMIN_ROLES.has(role)) return null;

  const [targetUserId, setTargetUserId] = useState(
    teamMembers?.[0]?.user_id || "",
  );
  const [range, setRange] = useState({
    start: _todayISO(-14),
    end: _todayISO(0),
  });
  const [includeDeleted, setIncludeDeleted] = useState(false);
  const [items, setItems] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [expanded, setExpanded] = useState(null);
  const [modal, setModal] = useState(null); // {mode: 'create'|'edit', row?: {...}}

  const load = useCallback(async () => {
    if (!targetUserId) {
      setItems([]);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const qs = new URLSearchParams({
        user_id: targetUserId,
        start: range.start,
        end: range.end,
      });
      if (includeDeleted) qs.append("include_deleted", "true");
      const data = await api.get(
        `/timeclock/admin/punches?${qs.toString()}`,
      );
      setItems(data?.items || []);
    } catch (e) {
      setError(e?.message || "Failed to load punches");
      setItems([]);
    } finally {
      setBusy(false);
    }
  }, [targetUserId, range.start, range.end, includeDeleted]);

  useEffect(() => { load(); }, [load]);

  const onSave = async (payload) => {
    try {
      if (modal?.mode === "edit") {
        await api.patch(
          `/timeclock/admin/punches/${modal.row.shift_id}`,
          payload,
        );
        toast.success("Punch updated");
      } else {
        await api.post("/timeclock/admin/punches", payload);
        toast.success("Punch created");
      }
      setModal(null);
      await load();
    } catch (e) {
      const msg = e?.message || "Save failed";
      toast.error(msg);
      // Re-raise so the modal can show the inline error too.
      throw e;
    }
  };

  const onDelete = async (row) => {
    const reason = window.prompt(
      "Reason for deleting this punch (min 3 chars)?",
      "duplicate / miss-punch",
    );
    if (!reason || reason.trim().length < 3) {
      toast.error("Reason is required (min 3 chars)");
      return;
    }
    const ok = window.confirm(
      `Soft-delete the shift from ${_fmtTs(row.clock_in)}? ` +
      "Punch stays in the audit log and can be viewed via " +
      "'Include deleted'.",
    );
    if (!ok) return;
    try {
      await api.delete(
        `/timeclock/admin/punches/${row.shift_id}?` +
        `reason=${encodeURIComponent(reason.trim())}`,
      );
      toast.success("Punch deleted");
      await load();
    } catch (e) {
      toast.error(e?.message || "Delete failed");
    }
  };

  const memberOptions = useMemo(
    () => (teamMembers || []).map((t) => ({
      value: t.user_id, label: t.name || t.user_id,
    })),
    [teamMembers],
  );

  return (
    <div
      className="rounded-2xl p-5 md:p-6 mt-4"
      style={{ background: colors.surface,
                border: `1px solid ${colors.border}` }}
      data-testid="admin-punch-edits-panel"
    >
      <div className="flex items-start md:items-center flex-col md:flex-row md:justify-between gap-3 mb-4">
        <div>
          <h2 className="text-base md:text-lg font-bold"
              style={{ color: colors.onSurface }}>
            Admin punch edits
          </h2>
          <p className="text-xs mt-0.5" style={{ color: colors.muted }}>
            Payroll corrections for any team member. All edits are
            audit-logged and admin/super_admin only.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setModal({ mode: "create" })}
          className="inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-2 rounded-md"
          style={{ background: colors.brand, color: "#fff",
                    border: 0 }}
          data-testid="admin-punch-add-btn"
        >
          <Plus size={14} /> Add Punch
        </button>
      </div>

      <div className="flex flex-wrap items-center gap-2 mb-3">
        <select
          value={targetUserId}
          onChange={(e) => setTargetUserId(e.target.value)}
          className="text-sm px-2 py-1.5 rounded-md"
          style={{ border: `1px solid ${colors.border}`,
                    background: "#FFFFFF", color: "#0F172A" }}
          data-testid="admin-punch-user-select"
        >
          <option value="">Select team member…</option>
          {memberOptions.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
        <input
          type="date"
          value={range.start}
          onChange={(e) => setRange((r) => ({ ...r, start: e.target.value }))}
          className="text-sm px-2 py-1.5 rounded-md"
          style={{ border: `1px solid ${colors.border}`,
                    background: "#FFFFFF", color: "#0F172A" }}
          data-testid="admin-punch-range-start"
        />
        <span className="text-xs" style={{ color: colors.muted }}>→</span>
        <input
          type="date"
          value={range.end}
          onChange={(e) => setRange((r) => ({ ...r, end: e.target.value }))}
          className="text-sm px-2 py-1.5 rounded-md"
          style={{ border: `1px solid ${colors.border}`,
                    background: "#FFFFFF", color: "#0F172A" }}
          data-testid="admin-punch-range-end"
        />
        <label className="inline-flex items-center gap-1.5 text-xs ml-2"
                style={{ color: colors.muted }}
                data-testid="admin-punch-include-deleted-label">
          <input
            type="checkbox"
            checked={includeDeleted}
            onChange={(e) => setIncludeDeleted(e.target.checked)}
            data-testid="admin-punch-include-deleted"
          /> Include deleted
        </label>
        <button
          type="button"
          onClick={load}
          disabled={busy}
          className="inline-flex items-center gap-1 text-xs px-2 py-1.5 rounded-md"
          style={{ background: colors.surfaceSecondary,
                    border: `1px solid ${colors.border}`,
                    color: colors.onSurface }}
          data-testid="admin-punch-refresh"
        >
          <RefreshCw size={12} /> Refresh
        </button>
      </div>

      {error ? (
        <div
          className="text-xs mb-3 px-2 py-1.5 rounded-md"
          style={{ background: "#FEF2F2", border: "1px solid #FECACA",
                    color: "#B91C1C" }}
          data-testid="admin-punch-error"
        >
          <AlertCircle size={12} className="inline mr-1" />
          {error}
        </div>
      ) : null}

      <div className="overflow-x-auto"
            data-testid="admin-punch-table-wrap">
        <table className="w-full text-xs"
                data-testid="admin-punch-table">
          <thead>
            <tr style={{ color: colors.muted }}>
              <th className="text-left py-1.5 px-2 font-semibold">Clock In</th>
              <th className="text-left py-1.5 px-2 font-semibold">Clock Out</th>
              <th className="text-left py-1.5 px-2 font-semibold">Duration</th>
              <th className="text-left py-1.5 px-2 font-semibold">Source</th>
              <th className="text-left py-1.5 px-2 font-semibold">Edited By</th>
              <th className="text-left py-1.5 px-2 font-semibold">Reason</th>
              <th className="text-right py-1.5 px-2 font-semibold">Actions</th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 && !busy ? (
              <tr>
                <td colSpan={7}
                    className="text-center py-6"
                    style={{ color: colors.muted }}
                    data-testid="admin-punch-empty">
                  No punches in this window.
                </td>
              </tr>
            ) : null}
            {items.map((row) => {
              const open = expanded === row.shift_id;
              const deleted = Boolean(row.deleted_at);
              return (
                <React.Fragment key={row.shift_id}>
                  <tr
                    style={{ borderTop: `1px solid ${colors.border}`,
                              opacity: deleted ? 0.5 : 1 }}
                    data-testid={`admin-punch-row-${row.shift_id}`}
                  >
                    <td className="py-2 px-2">
                      <button
                        type="button"
                        onClick={() => setExpanded(open ? null : row.shift_id)}
                        className="inline-flex items-center gap-1 text-xs"
                        style={{ color: colors.onSurface }}
                        data-testid={`admin-punch-expand-${row.shift_id}`}
                      >
                        {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                        <Clock size={12} /> {_fmtTs(row.clock_in)}
                      </button>
                    </td>
                    <td className="py-2 px-2">
                      {row.clock_out ? _fmtTs(row.clock_out) : (
                        <span className="text-[11px] font-bold px-1.5 py-0.5 rounded"
                              style={{ background: "#FEF9C3",
                                        color: "#854D0E" }}>
                          OPEN
                        </span>
                      )}
                    </td>
                    <td className="py-2 px-2 tabular-nums"
                        style={{ color: colors.onSurface }}>
                      {_fmtDuration(row.clock_in, row.clock_out)}
                    </td>
                    <td className="py-2 px-2"
                        style={{ color: colors.muted }}>
                      {row.source || "—"}
                    </td>
                    <td className="py-2 px-2"
                        style={{ color: colors.muted }}>
                      {row.edited_by ? row.edited_by.slice(0, 8) : "—"}
                    </td>
                    <td className="py-2 px-2"
                        style={{ color: colors.muted }}>
                      {row.edit_reason || "—"}
                    </td>
                    <td className="py-2 px-2 text-right">
                      {!deleted ? (
                        <div className="inline-flex items-center gap-1">
                          <button
                            type="button"
                            onClick={() => setModal({ mode: "edit", row })}
                            className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-md"
                            style={{ background: colors.surfaceSecondary,
                                      border: `1px solid ${colors.border}`,
                                      color: colors.onSurface }}
                            data-testid={`admin-punch-edit-${row.shift_id}`}
                          >
                            <Edit size={12} /> Edit
                          </button>
                          <button
                            type="button"
                            onClick={() => onDelete(row)}
                            className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-md"
                            style={{ background: "#FEF2F2",
                                      border: "1px solid #FECACA",
                                      color: "#B91C1C" }}
                            data-testid={`admin-punch-delete-${row.shift_id}`}
                          >
                            <Trash2 size={12} /> Delete
                          </button>
                        </div>
                      ) : (
                        <span className="text-[11px]"
                              style={{ color: "#B91C1C" }}>
                          deleted {_fmtTs(row.deleted_at)}
                        </span>
                      )}
                    </td>
                  </tr>
                  {open ? (
                    <tr style={{ background: colors.surfaceSecondary }}
                        data-testid={`admin-punch-audit-${row.shift_id}`}>
                      <td colSpan={7} className="py-3 px-4">
                        <div className="text-[11px] font-bold uppercase tracking-wider mb-1"
                              style={{ color: colors.muted }}>
                          Audit log ({row.audit_log?.length || 0})
                        </div>
                        <ul className="space-y-1">
                          {(row.audit_log || []).map((e, idx) => (
                            <li key={idx}
                                className="text-[11px]"
                                style={{ color: colors.onSurface }}
                                data-testid={`admin-punch-audit-entry-${row.shift_id}-${idx}`}>
                              <span className="font-semibold">
                                {e.action}
                              </span>{" "}
                              by {String(e.edited_by || "?").slice(0, 8)}{" "}
                              @ {_fmtTs(e.edited_at)} — {e.reason}
                              {e.changes ? (
                                <span className="ml-2"
                                      style={{ color: colors.muted }}>
                                  {Object.entries(e.changes).map(([k, v]) =>
                                    `${k}: ${v.from ?? "∅"} → ${v.to ?? "∅"}`,
                                  ).join(" · ")}
                                </span>
                              ) : null}
                            </li>
                          ))}
                        </ul>
                      </td>
                    </tr>
                  ) : null}
                </React.Fragment>
              );
            })}
          </tbody>
        </table>
      </div>

      {modal ? (
        <AdminPunchModal
          mode={modal.mode}
          row={modal.row}
          lockedUserId={modal.mode === "edit"
            ? modal.row?.user_id : targetUserId}
          teamMembers={teamMembers}
          onCancel={() => setModal(null)}
          onSave={onSave}
        />
      ) : null}
    </div>
  );
}
