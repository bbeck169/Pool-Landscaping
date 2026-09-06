/**
 * Phase K63 · Feb-2026 — Lead Alerts recipient CRUD.
 *
 * Admin-only page mounted at ``/settings/notifications/lead-alerts``
 * that lets tenant admins manage the list of humans who receive
 * an email + SMS ping when the public widget forms create a new
 * lead.
 *
 * Contract (matches ``routers/tenant_lead_notifications.py``):
 *   GET  /api/tenants/{tid}/settings/lead-notifications
 *   PUT  /api/tenants/{tid}/settings/lead-notifications
 *
 * Behaviour highlights:
 *   * Lazy-migrates any legacy P18 recipient (flat email / phone
 *     arrays) into the rich shape the first time an admin opens
 *     the page. The GET endpoint does the migration, this UI just
 *     renders whatever comes back.
 *   * Row-level validation — an "SMS on" toggle requires a valid
 *     E.164 phone; an "Email on" toggle requires a valid email.
 *     Invalid rows disable the Save button + surface a red banner.
 *   * Success + error toasts. Add / Remove / Save all cause a
 *     re-fetch so the ids on new rows come from the server.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, Bell, Save, Trash2, UserPlus, X } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";


const _E164 = /^\+[1-9]\d{9,14}$/;
const _EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;


function _normalizePhoneForDisplay(v) {
  if (!v) return "";
  const digits = String(v).replace(/\D/g, "");
  if (digits.length === 10) return `+1${digits}`;
  if (digits.length === 11 && digits.startsWith("1")) return `+${digits}`;
  return v.startsWith("+") ? v : v;
}


// ─── K63.polish · Feb-2026 — last-notified chip helpers ────────────
//
// The dispatch log is fetched once on mount + on every save. We
// bucket each recipient's most-recent row into one of five states
// and pick a chip label + tone. Kept as a pure function so vitest
// can drive it without React.

function _rel(fromISO, nowMs = Date.now()) {
  if (!fromISO) return "";
  const then = Date.parse(fromISO);
  if (Number.isNaN(then)) return "";
  const secs = Math.max(0, Math.round((nowMs - then) / 1000));
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.round(hrs / 24);
  return `${days} day${days === 1 ? "" : "s"} ago`;
}

// Exported for vitest ↓
export function pickChip(latestRow, nowMs = Date.now()) {
  if (!latestRow) {
    return { label: "No sends yet", tone: "muted", testid: "chip-none" };
  }
  const age = nowMs - Date.parse(latestRow.created_at || "");
  if (latestRow.status === "failed") {
    return {
      label: `Last attempt failed ${_rel(latestRow.created_at, nowMs)}`,
      tone: "danger",
      testid: "chip-failed",
    };
  }
  const days = age / 86400000;
  if (days > 14) {
    return {
      label: "Silent 14+ days",
      tone: "warning",
      testid: "chip-stale",
    };
  }
  if (days >= 1) {
    return {
      label: `Last: ${_rel(latestRow.created_at, nowMs)}`,
      tone: "neutral",
      testid: "chip-neutral",
    };
  }
  return {
    label: `Last: ${_rel(latestRow.created_at, nowMs)}`,
    tone: "success",
    testid: "chip-recent",
  };
}

// Map tone → colour tokens sourced from ``theme.js``.
function _chipStyle(tone) {
  switch (tone) {
    case "success": return { bg: "#DCFCE7", fg: "#166534" };
    case "warning": return { bg: "#FEF3C7", fg: "#92400E" };
    case "danger":  return { bg: "#FEE2E2", fg: "#991B1B" };
    case "neutral": return { bg: colors.brandTertiary, fg: colors.onBrandTertiary };
    case "muted":   /* fallthrough */
    default:        return { bg: colors.surfaceSecondary, fg: colors.onSurfaceSecondary };
  }
}


export default function LeadAlertsSettings() {
  const nav = useNavigate();
  const [tenantId, setTenantId] = useState(null);
  const [rows, setRows] = useState([]);
  const [initialSnapshot, setInitialSnapshot] = useState("[]");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState("");
  const [error, setError] = useState("");
  // K63.polish — dispatch log, keyed by lower-cased email / raw phone.
  const [logIndex, setLogIndex] = useState({});
  const [modalRecipient, setModalRecipient] = useState(null);
  const [modalRows, setModalRows] = useState([]);
  const [modalLoading, setModalLoading] = useState(false);

  const loadDispatchLog = useCallback(async () => {
    try {
      const r = await api.get("/admin/notification-dispatch-log?limit=200");
      const items = Array.isArray(r?.items) ? r.items : [];
      // Group newest-first-per-recipient. The API already returns
      // newest-first so the first row we see per key wins.
      const idx = {};
      for (const row of items) {
        const key = (row.recipient || "").toLowerCase();
        if (!key) continue;
        if (!idx[key]) idx[key] = row;
      }
      setLogIndex(idx);
    } catch {
      // K63.polish — silent fail keeps the settings UI usable
      // even if the observability endpoint is unavailable. Chips
      // simply fall through to "No sends yet".
      setLogIndex({});
    }
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const t = await api.get("/tenants/current");
      setTenantId(t?.id || null);
      if (t?.id) {
        const r = await api.get(`/tenants/${t.id}/settings/lead-notifications`);
        const items = (r?.recipients || []).map((x) => ({ ...x }));
        setRows(items);
        setInitialSnapshot(JSON.stringify(items));
      }
    } catch (e) {
      setError(e?.message || "Failed to load recipients");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { loadDispatchLog(); }, [loadDispatchLog]);

  const dirty = useMemo(() => JSON.stringify(rows) !== initialSnapshot, [rows, initialSnapshot]);

  // K63 · Feb-2026 — per-row validation. A row is only invalid
  // when the operator has opted a channel in but the target for
  // that channel is malformed or empty. Empty rows without any
  // opt-in are allowed — save strips them via the API validator.
  const rowErrors = useMemo(() => rows.map((r) => {
    const errs = [];
    if (r.email && !_EMAIL.test(r.email.trim().toLowerCase())) {
      errs.push("Invalid email format");
    }
    if (r.phone && !_E164.test(_normalizePhoneForDisplay(r.phone))) {
      errs.push("Invalid phone (use E.164 like +16028874400)");
    }
    if (r.sms_opt_in && !r.phone) errs.push("SMS on requires a phone");
    if (r.email_opt_in && !r.email) errs.push("Email on requires an email");
    if (!r.email && !r.phone && (r.sms_opt_in || r.email_opt_in)) {
      errs.push("Add an email or phone number");
    }
    return errs;
  }), [rows]);

  const canSave = dirty && !saving && rowErrors.every((e) => e.length === 0);

  const patchRow = (idx, patch) => {
    setRows((rs) => rs.map((r, i) => (i === idx ? { ...r, ...patch } : r)));
  };

  const addRow = () => {
    setRows((rs) => [
      ...rs,
      { id: null, name: "", email: "", phone: "",
        sms_opt_in: false, email_opt_in: false },
    ]);
  };

  const removeRow = (idx) => {
    setRows((rs) => rs.filter((_, i) => i !== idx));
  };

  // K63.polish · click a recipient's chip → fetch that recipient's
  // last 20 dispatch rows and open the drill-down modal.
  const openModal = async (recipient) => {
    if (!recipient) return;
    setModalRecipient(recipient);
    setModalLoading(true);
    setModalRows([]);
    try {
      const q = new URLSearchParams({ recipient, limit: "20" });
      const r = await api.get(`/admin/notification-dispatch-log?${q}`);
      setModalRows(Array.isArray(r?.items) ? r.items : []);
    } catch {
      setModalRows([]);
    } finally {
      setModalLoading(false);
    }
  };

  const closeModal = () => {
    setModalRecipient(null);
    setModalRows([]);
  };

  // K63.polish · resolve the chip for a given recipient row —
  // prefers the email key (channel-agnostic) if opt-in, else phone.
  const chipFor = (r) => {
    const email = (r.email || "").trim().toLowerCase();
    const phone = (r.phone || "").trim();
    const rowE = email ? logIndex[email] : null;
    const rowP = phone ? logIndex[phone.toLowerCase()] : null;
    // Pick whichever ROW is newer.
    let latest = null;
    for (const cand of [rowE, rowP]) {
      if (!cand) continue;
      if (!latest || (cand.created_at || "") > (latest.created_at || "")) {
        latest = cand;
      }
    }
    return { chip: pickChip(latest), latestTarget: (rowE || rowP || {}).recipient };
  };

  const save = async () => {
    if (!tenantId || !canSave) return;
    setSaving(true);
    setError("");
    try {
      const payload = {
        recipients: rows.map((r) => ({
          id: r.id || null,
          name: (r.name || "").trim(),
          email: (r.email || "").trim().toLowerCase(),
          phone: _normalizePhoneForDisplay((r.phone || "").trim()),
          sms_opt_in: !!r.sms_opt_in,
          email_opt_in: !!r.email_opt_in,
        })),
      };
      const r = await api.put(`/tenants/${tenantId}/settings/lead-notifications`, payload);
      const items = (r?.recipients || []).map((x) => ({ ...x }));
      setRows(items);
      setInitialSnapshot(JSON.stringify(items));
      setToast("Recipients saved");
      setTimeout(() => setToast(""), 2500);
      // K63.polish · refresh the chip data after any recipient
      // change so a freshly-added row starts with "No sends yet"
      // and a rename immediately reflects the correct key.
      loadDispatchLog();
    } catch (e) {
      setError(e?.message || "Failed to save recipients");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="max-w-4xl mx-auto p-6" data-testid="lead-alerts-settings-page">
      <div className="flex items-center gap-3 mb-4">
        <button
          onClick={() => nav("/settings/notifications")}
          className="text-sm inline-flex items-center gap-1 text-slate-600 hover:text-slate-900"
          data-testid="lead-alerts-back"
        >
          <ArrowLeft size={14} /> Back to Notifications
        </button>
      </div>

      <div className="mb-6">
        <h1 className="text-2xl font-semibold flex items-center gap-2"
             style={{ color: colors.onSurface }}>
          <Bell size={20} className="opacity-70" /> Lead Alerts
        </h1>
        <p className="text-sm mt-1" style={{ color: colors.onSurfaceSecondary }}>
          Configure who receives an email and/or SMS notification
          when the public widget forms create a new lead. Empty
          list → notifications are a no-op (leads still save).
        </p>
      </div>

      {error ? (
        <div className="mb-4 p-3 rounded text-sm"
              style={{ backgroundColor: (colors.errorMuted || "#fee"),
                       color: colors.error, border: `1px solid ${colors.error}` }}
              data-testid="lead-alerts-error">
          {error}
        </div>
      ) : null}

      <div className="rounded-lg border overflow-hidden"
            style={{ borderColor: colors.border, backgroundColor: colors.surface }}>
        <table className="w-full text-sm" data-testid="lead-alerts-table">
          <thead style={{ backgroundColor: colors.surfaceSecondary }}>
            <tr>
              <th className="text-left px-3 py-2 font-semibold"
                    style={{ color: colors.onSurfaceSecondary }}>Name</th>
              <th className="text-left px-3 py-2 font-semibold"
                    style={{ color: colors.onSurfaceSecondary }}>Email</th>
              <th className="text-left px-3 py-2 font-semibold"
                    style={{ color: colors.onSurfaceSecondary }}>Phone</th>
              <th className="text-center px-3 py-2 font-semibold"
                    style={{ color: colors.onSurfaceSecondary }}>Email on</th>
              <th className="text-center px-3 py-2 font-semibold"
                    style={{ color: colors.onSurfaceSecondary }}>SMS on</th>
              <th className="text-left px-3 py-2 font-semibold"
                    style={{ color: colors.onSurfaceSecondary }}>Last activity</th>
              <th className="px-3 py-2"></th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={7} className="px-3 py-6 text-center text-xs"
                       style={{ color: colors.onSurfaceSecondary }}
                       data-testid="lead-alerts-loading">Loading…</td></tr>
            ) : rows.length === 0 ? (
              <tr><td colSpan={7} className="px-3 py-6 text-center text-xs"
                       style={{ color: colors.onSurfaceSecondary }}
                       data-testid="lead-alerts-empty">
                No recipients configured. Widget-form submissions
                will still create leads, but no email / SMS pings
                will fire until you add someone below.
              </td></tr>
            ) : rows.map((r, idx) => (
              <tr key={r.id || `new-${idx}`}
                  data-testid={`lead-alerts-row-${idx}`}
                  style={{ borderTop: `1px solid ${colors.border}` }}>
                <td className="px-2 py-2">
                  <input
                    type="text" value={r.name || ""}
                    placeholder="Full name"
                    onChange={(e) => patchRow(idx, { name: e.target.value })}
                    data-testid={`lead-alerts-name-${idx}`}
                    className="w-full px-2 py-1 rounded text-sm"
                    style={{ backgroundColor: colors.surface, color: colors.onSurface,
                              border: `1px solid ${colors.border}` }}
                  />
                </td>
                <td className="px-2 py-2">
                  <input
                    type="email" value={r.email || ""}
                    placeholder="name@company.com"
                    onChange={(e) => patchRow(idx, { email: e.target.value })}
                    data-testid={`lead-alerts-email-${idx}`}
                    className="w-full px-2 py-1 rounded text-sm"
                    style={{ backgroundColor: colors.surface, color: colors.onSurface,
                              border: `1px solid ${colors.border}` }}
                  />
                </td>
                <td className="px-2 py-2">
                  <input
                    type="tel" value={r.phone || ""}
                    placeholder="+16028874400"
                    onChange={(e) => patchRow(idx, { phone: e.target.value })}
                    data-testid={`lead-alerts-phone-${idx}`}
                    className="w-full px-2 py-1 rounded text-sm font-mono"
                    style={{ backgroundColor: colors.surface, color: colors.onSurface,
                              border: `1px solid ${colors.border}` }}
                  />
                </td>
                <td className="text-center px-2 py-2">
                  <input
                    type="checkbox" checked={!!r.email_opt_in}
                    onChange={(e) => patchRow(idx, { email_opt_in: e.target.checked })}
                    data-testid={`lead-alerts-email-optin-${idx}`}
                  />
                </td>
                <td className="text-center px-2 py-2">
                  <input
                    type="checkbox" checked={!!r.sms_opt_in}
                    onChange={(e) => patchRow(idx, { sms_opt_in: e.target.checked })}
                    data-testid={`lead-alerts-sms-optin-${idx}`}
                  />
                </td>
                <td className="px-2 py-2">
                  {(() => {
                    const { chip, latestTarget } = chipFor(r);
                    const style = _chipStyle(chip.tone);
                    const clickable = Boolean(latestTarget);
                    return (
                      <button
                        type="button"
                        disabled={!clickable}
                        onClick={() => clickable && openModal(latestTarget)}
                        data-testid={`lead-alerts-chip-${idx}`}
                        data-chip-tone={chip.tone}
                        title={clickable ? "View last 20 dispatch rows" : "No dispatch history"}
                        className="inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-semibold"
                        style={{
                          backgroundColor: style.bg,
                          color: style.fg,
                          border: `1px solid ${style.bg}`,
                          cursor: clickable ? "pointer" : "default",
                          maxWidth: 220,
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                        }}
                      >
                        {chip.label}
                      </button>
                    );
                  })()}
                </td>
                <td className="text-right px-2 py-2">
                  <button
                    onClick={() => removeRow(idx)}
                    data-testid={`lead-alerts-remove-${idx}`}
                    className="p-1 rounded hover:bg-slate-100 text-slate-500"
                    aria-label="Remove recipient"
                  >
                    <Trash2 size={14} />
                  </button>
                </td>
              </tr>
            ))}
            {rows.map((_, idx) => rowErrors[idx].length > 0 ? (
              <tr key={`err-${idx}`} style={{ backgroundColor: colors.surfaceSecondary }}>
                <td colSpan={7} className="px-3 py-1 text-xs"
                    style={{ color: colors.error }}
                    data-testid={`lead-alerts-row-error-${idx}`}>
                  Row {idx + 1}: {rowErrors[idx].join(" · ")}
                </td>
              </tr>
            ) : null)}
          </tbody>
        </table>
      </div>

      <div className="mt-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <button
            onClick={addRow}
            disabled={rows.length >= 10}
            data-testid="lead-alerts-add"
            className="inline-flex items-center gap-1 px-3 py-1.5 rounded text-sm border"
            style={{ borderColor: colors.border, color: colors.onSurface,
                      backgroundColor: colors.surface,
                      opacity: rows.length >= 10 ? 0.5 : 1,
                      cursor: rows.length >= 10 ? "not-allowed" : "pointer" }}
          >
            <UserPlus size={14} /> Add recipient
          </button>
          <span
            className="text-xs"
            style={{ color: rows.length >= 10 ? colors.error : colors.onSurfaceSecondary }}
            data-testid="lead-alerts-count"
          >
            {rows.length}/10 recipients
            {rows.length >= 10 ? " · limit reached" : ""}
          </span>
        </div>

        <div className="flex items-center gap-2">
          {toast ? (
            <span className="text-sm" style={{ color: colors.brand }}
                   data-testid="lead-alerts-toast">{toast}</span>
          ) : null}
          <button
            onClick={save}
            disabled={!canSave}
            data-testid="lead-alerts-save"
            className="inline-flex items-center gap-1 px-4 py-2 rounded font-semibold text-sm"
            style={{
              backgroundColor: canSave ? colors.brand : colors.muted,
              color: colors.onBrand || "#fff",
              opacity: canSave ? 1 : 0.6,
              cursor: canSave ? "pointer" : "not-allowed",
            }}
          >
            <Save size={14} /> {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>

      {modalRecipient ? (
        <DispatchLogModal
          recipient={modalRecipient}
          rows={modalRows}
          loading={modalLoading}
          onClose={closeModal}
        />
      ) : null}
    </div>
  );
}


// ─── K63.polish — dispatch log drill-down modal ────────────────────

function DispatchLogModal({ recipient, rows, loading, onClose }) {
  return (
    <div
      role="dialog"
      aria-modal="true"
      data-testid="dispatch-log-modal"
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ backgroundColor: "rgba(15,23,42,0.55)" }}
      onClick={onClose}
    >
      <div
        className="w-full max-w-2xl rounded-xl shadow-lg overflow-hidden"
        style={{ backgroundColor: colors.surface,
                  border: `1px solid ${colors.border}` }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-4 py-3"
              style={{ borderBottom: `1px solid ${colors.border}`,
                        backgroundColor: colors.surfaceSecondary }}>
          <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>
            Recent dispatch — <span className="font-mono">{recipient}</span>
          </div>
          <button onClick={onClose} aria-label="Close"
                    data-testid="dispatch-log-modal-close"
                    className="p-1 rounded hover:bg-slate-100"
                    style={{ color: colors.onSurfaceSecondary }}>
            <X size={16} />
          </button>
        </div>
        <div className="max-h-[60vh] overflow-y-auto">
          {loading ? (
            <div className="p-6 text-center text-xs"
                  style={{ color: colors.onSurfaceSecondary }}
                  data-testid="dispatch-log-modal-loading">Loading…</div>
          ) : rows.length === 0 ? (
            <div className="p-6 text-center text-xs"
                  style={{ color: colors.onSurfaceSecondary }}
                  data-testid="dispatch-log-modal-empty">
              No dispatch history for this recipient yet.
            </div>
          ) : (
            <table className="w-full text-xs" data-testid="dispatch-log-modal-table">
              <thead style={{ backgroundColor: colors.surfaceSecondary }}>
                <tr>
                  <th className="text-left px-3 py-2 font-semibold"
                        style={{ color: colors.onSurfaceSecondary }}>When</th>
                  <th className="text-left px-3 py-2 font-semibold"
                        style={{ color: colors.onSurfaceSecondary }}>Channel</th>
                  <th className="text-left px-3 py-2 font-semibold"
                        style={{ color: colors.onSurfaceSecondary }}>Status</th>
                  <th className="text-left px-3 py-2 font-semibold"
                        style={{ color: colors.onSurfaceSecondary }}>Lead</th>
                  <th className="text-left px-3 py-2 font-semibold"
                        style={{ color: colors.onSurfaceSecondary }}>Details</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row, i) => {
                  const failed = row.status === "failed";
                  return (
                    <tr key={row.id || i}
                        style={{ borderTop: `1px solid ${colors.border}` }}
                        data-testid={`dispatch-log-modal-row-${i}`}>
                      <td className="px-3 py-2 whitespace-nowrap"
                          style={{ color: colors.onSurface }}>
                        {row.created_at || ""}
                      </td>
                      <td className="px-3 py-2 uppercase"
                          style={{ color: colors.onSurfaceSecondary }}>
                        {row.channel}
                      </td>
                      <td className="px-3 py-2">
                        <span
                          className="inline-block rounded px-2 py-0.5 text-[10px] font-bold uppercase"
                          style={{
                            backgroundColor: failed ? "#FEE2E2" : "#DCFCE7",
                            color: failed ? "#991B1B" : "#166534",
                          }}
                        >
                          {row.status}
                        </span>
                      </td>
                      <td className="px-3 py-2 font-mono"
                          style={{ color: colors.onSurfaceSecondary }}>
                        {row.lead_id ? row.lead_id.slice(0, 8) : ""}
                      </td>
                      <td className="px-3 py-2"
                          style={{ color: failed ? colors.error : colors.onSurfaceSecondary }}>
                        {failed
                          ? (row.error || "unknown error")
                          : (row.provider_message_id || "")}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}
