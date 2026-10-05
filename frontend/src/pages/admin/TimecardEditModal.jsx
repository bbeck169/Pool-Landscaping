/**
 * TIMECARD-EDIT-UI atomic · Feb-2026.
 *
 * Admin / manager / owner / super_admin modal for editing a
 * time_entries row via PATCH /api/workforce/timesheets/{eid}.
 * Colocates:
 *   * TimecardEditModal    - dialog with 3 pickers + reason box
 *   * AuditHistoryPopover  - reverse-chronological edit log
 *   * canEditTimecards     - tiny role-gate helper (local, since
 *                            the app has no central <RoleGate>)
 *
 * UX contract:
 *   * Datetime inputs are <input type="datetime-local"> matching
 *     the house convention (JobTimersPage, FollowUpEditor, etc.).
 *     ISO strings are trimmed to YYYY-MM-DDTHH:MM for display and
 *     reconstructed on save using the row original tz offset.
 *   * Date picker is <input type="date"> sending YYYY-MM-DD.
 *   * Open shifts (clock_out_at === null) show the clock-out input
 *     DISABLED with a hint - any attempt to close via PATCH is
 *     refused by the backend (400) and we respect that contract.
 *   * Save button is disabled until at least one field is dirty.
 *     Only dirty fields are included in the PATCH body.
 *   * Reason box is capped at 500 chars client-side (matches
 *     backend _REASON_MAX_LEN). Live counter shown below.
 *   * Backend error detail is surfaced verbatim via sonner toast.
 */
import React, { useMemo, useState } from "react";
import { History } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api";
import {
  Dialog, DialogContent, DialogHeader, DialogFooter,
  DialogTitle, DialogDescription,
} from "@/components/ui/dialog";
import { Popover, PopoverTrigger, PopoverContent } from "@/components/ui/popover";
import { Textarea } from "@/components/ui/textarea";

// Local role-gate - centralized helper would be a cross-cutting
// refactor outside this atomic scope.  Mirrors the backend set
// enforced by utils.require_admin_or_manager.
export const EDITABLE_ROLES = new Set([
  "admin", "super_admin", "manager", "owner",
]);
export function canEditTimecards(user) {
  return !!(user && user.role && EDITABLE_ROLES.has(user.role));
}

const REASON_MAX = 500;

// --- ISO <-> input value helpers ----------------------------------
function toInputValue(iso) {
  // Trim ISO "2026-02-15T08:00:00+00:00" -> "2026-02-15T08:00".
  // Matches the convention in FollowUpEditor + JobTimersPage.
  if (!iso || typeof iso !== "string") return "";
  return iso.slice(0, 16);
}
function toDateValue(iso) {
  if (!iso || typeof iso !== "string") return "";
  return iso.slice(0, 10);
}
function extractTzOffset(iso) {
  if (!iso || typeof iso !== "string") return "+00:00";
  const m = iso.match(/([+-]\d{2}:\d{2}|Z)$/);
  if (!m) return "+00:00";
  return m[1] === "Z" ? "+00:00" : m[1];
}
function fromInputValue(local, originalIso) {
  // "YYYY-MM-DDTHH:MM" -> "YYYY-MM-DDTHH:MM:00<tz>" preserving the
  // row original offset.  If the row had no parseable offset we
  // fall back to +00:00 (UTC) - consistent with the backend seed.
  if (!local) return null;
  return `${local}:00${extractTzOffset(originalIso)}`;
}

// --- Audit history popover ----------------------------------------
function fmtTs(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString();
  } catch { return iso; }
}
function fmtDelta(k, v) {
  // Compact "{from} -> {to}" with ellipsis on long ISO strings.
  const trim = (s) => {
    if (s == null) return "-";
    const str = String(s);
    return str.length > 22 ? `${str.slice(0, 19)}...` : str;
  };
  return `${trim(v && v.from)} -> ${trim(v && v.to)}`;
}

export function AuditHistoryPopover({ edits, testid }) {
  const list = Array.isArray(edits) ? edits : [];
  if (list.length === 0) return null;
  const ordered = [...list].reverse(); // newest first
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          className="ml-2 inline-flex items-center gap-1 text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded hover:opacity-80 transition"
          style={{ background: "#DBEAFE", color: "#1E3A8A" }}
          data-testid={testid || "timecard-audit-badge"}
          aria-label={`Edit history (${list.length} edit${list.length === 1 ? "" : "s"})`}
        >
          <History size={10} />
          Edited &middot; {list.length}
        </button>
      </PopoverTrigger>
      <PopoverContent
        className="w-80 max-h-80 overflow-y-auto p-3"
        data-testid="timecard-audit-popover"
      >
        <div className="text-xs font-semibold mb-2">Edit history</div>
        <ul className="space-y-2.5">
          {ordered.map((e, idx) => (
            <li
              key={e.edit_id || idx}
              className="text-xs border-l-2 border-slate-300 pl-2.5"
              data-testid={`timecard-audit-entry-${idx}`}
            >
              <div className="font-medium text-slate-800">
                {e.edited_by_name || e.edited_by || "Unknown"}{" "}
                <span className="font-normal text-slate-500">
                  ({e.edited_by_role || "-"})
                </span>
              </div>
              <div className="text-[11px] text-slate-500">{fmtTs(e.edited_at)}</div>
              <ul className="mt-1 space-y-0.5">
                {Object.entries(e.changes || {}).map(([k, v]) => (
                  <li key={k} className="text-[11px]">
                    <span className="font-mono text-slate-600">{k}:</span>{" "}
                    <span className="text-slate-800">{fmtDelta(k, v)}</span>
                  </li>
                ))}
              </ul>
              {e.reason ? (
                <div className="mt-1 text-[11px] italic text-slate-600">
                  {`"${e.reason}"`}
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      </PopoverContent>
    </Popover>
  );
}

// --- Edit modal ---------------------------------------------------
export function TimecardEditModal({ row, open, onClose, onUpdated }) {
  const initialCi = toInputValue(row && row.clock_in_at);
  const initialCo = toInputValue(row && row.clock_out_at);
  const initialDate = toDateValue(row && row.clock_in_at);
  const isOpenShift = !!row && !row.clock_out_at;

  const [ci, setCi] = useState(initialCi);
  const [co, setCo] = useState(initialCo);
  const [date, setDate] = useState(initialDate);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  const dirty = useMemo(() => {
    return (ci !== initialCi) || (co !== initialCo) ||
           (date !== initialDate) || !!reason;
  }, [ci, co, date, reason, initialCi, initialCo, initialDate]);

  const buildBody = () => {
    const body = {};
    if (ci !== initialCi) body.clock_in_at = fromInputValue(ci, row && row.clock_in_at);
    if (co !== initialCo && !isOpenShift) {
      body.clock_out_at = fromInputValue(co, row && row.clock_out_at);
    }
    if (date !== initialDate) body.date = date;
    if (reason) body.reason = reason;
    return body;
  };

  const save = async () => {
    if (!row || !dirty || busy) return;
    const body = buildBody();
    if (Object.keys(body).length === 0) return;
    setBusy(true);
    try {
      const updated = await api.patch(
        `/workforce/timesheets/${row.id}`, body,
      );
      toast.success("Timecard updated");
      if (onUpdated) onUpdated(updated);
      onClose && onClose();
    } catch (e) {
      // Surface backend detail verbatim - includes the exact
      // shift_duration_unreasonable / paid payroll / reason-too-
      // long messages so admin sees the authoritative reason.
      const detail = (e && (e.data && e.data.detail)) || (e && e.message) ||
                     "Edit failed";
      toast.error(String(detail));
    } finally {
      setBusy(false);
    }
  };

  if (!row) return null;

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) onClose && onClose(); }}>
      <DialogContent
        className="sm:max-w-md"
        data-testid="timecard-edit-modal"
      >
        <DialogHeader>
          <DialogTitle>Edit timecard</DialogTitle>
          <DialogDescription>
            {row.user_name || "Technician"}{" "}
            {row.job_title ? `- ${row.job_title}` : ""}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3 py-2">
          <label className="block">
            <span className="block text-xs font-semibold text-slate-700 mb-1">
              Date
            </span>
            <input
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
              className="w-full text-sm px-3 py-2 rounded-lg border border-slate-300"
              data-testid="timecard-edit-date"
            />
          </label>

          <label className="block">
            <span className="block text-xs font-semibold text-slate-700 mb-1">
              Clock-in
            </span>
            <input
              type="datetime-local"
              value={ci}
              onChange={(e) => setCi(e.target.value)}
              className="w-full text-sm px-3 py-2 rounded-lg border border-slate-300"
              data-testid="timecard-edit-clock-in"
            />
          </label>

          <label className="block">
            <span className="block text-xs font-semibold text-slate-700 mb-1">
              Clock-out{isOpenShift ? " (shift is open)" : ""}
            </span>
            <input
              type="datetime-local"
              value={co}
              onChange={(e) => setCo(e.target.value)}
              disabled={isOpenShift}
              className="w-full text-sm px-3 py-2 rounded-lg border border-slate-300 disabled:bg-slate-100 disabled:text-slate-400"
              data-testid="timecard-edit-clock-out"
            />
            {isOpenShift ? (
              <span className="block text-[11px] text-slate-500 mt-1">
                Open shifts must be closed via the clock-out flow, not this editor.
              </span>
            ) : null}
          </label>

          <label className="block">
            <span className="block text-xs font-semibold text-slate-700 mb-1">
              Reason (optional)
            </span>
            <Textarea
              value={reason}
              onChange={(e) => setReason(e.target.value.slice(0, REASON_MAX))}
              maxLength={REASON_MAX}
              placeholder="e.g. tech forgot to clock out"
              className="w-full text-sm"
              rows={2}
              data-testid="timecard-edit-reason"
            />
            <div
              className="text-[11px] text-slate-500 mt-0.5"
              data-testid="timecard-edit-reason-counter"
            >
              {reason.length}/{REASON_MAX}
            </div>
          </label>
        </div>

        <DialogFooter className="gap-2">
          <button
            type="button"
            onClick={() => onClose && onClose()}
            className="text-xs font-semibold px-3 py-2 rounded-lg border border-slate-300 bg-white hover:bg-slate-50"
            data-testid="timecard-edit-cancel"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={save}
            disabled={!dirty || busy}
            className="text-xs font-semibold px-3 py-2 rounded-lg bg-slate-900 text-white hover:bg-slate-800 disabled:bg-slate-300 disabled:cursor-not-allowed"
            data-testid="timecard-edit-save"
          >
            {busy ? "Saving..." : "Save changes"}
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default TimecardEditModal;
