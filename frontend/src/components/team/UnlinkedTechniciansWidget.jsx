/**
 * Feb-2026 · Sprint 2 · Section A — Admin "Unlinked Technicians" widget.
 *
 * Surfaces every ``db.technicians`` row whose ``user_id`` is null so
 * admins can click-through to create + link a matching ``users`` row
 * (with a random temp password and an optional invite email).
 *
 * Props
 * -----
 * * ``isAdmin`` (boolean) — mirrors the parent's role gate. When
 *   ``false`` the widget renders ``null`` (defense-in-depth; the
 *   backend also 403s any non-admin caller).
 * * ``onCreated({email})`` — optional callback fired after a
 *   successful create-user so the parent can refresh its own roster
 *   list (the team page's ``/team`` fetch is the caller's).
 *
 * Rendering rules
 * ---------------
 * * When the GET returns 0 rows OR errors, the widget renders
 *   ``null`` — this is an "attention when needed" surface, not a
 *   permanent card.
 * * Success modal shows the temp password ONCE with a copy button
 *   plus the invite-email status ("sent" / "skipped" / etc.).
 * * 409 responses (email_already_in_use, already_linked) surface
 *   inline on the row that failed, WITHOUT dismissing the widget,
 *   with a Refresh button so the admin can retry after fixing the
 *   duplicate.
 */
import React from "react";
import { AlertCircle, Copy as CopyIcon, RefreshCw, Trash2, UserPlus, X as XIcon } from "lucide-react";
import { api } from "@/api";


// ══════════════════════════════════════════════════════════════════
// Helpers
// ══════════════════════════════════════════════════════════════════
function _formatCreatedAt(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "—";
    return d.toLocaleDateString(undefined, {
      year: "numeric", month: "short", day: "numeric",
    });
  } catch {
    return "—";
  }
}


function _readErrorPayload(err) {
  // ``api.post`` throws with a ``.body`` (dict) OR ``.message`` (str)
  // depending on the wrapper version. Support both without leaking
  // an ``[object Object]`` into the toast.
  if (!err) return { code: null, message: "Unknown error" };
  const body = err.body || err.data || err.response?.data || null;
  if (body && typeof body === "object") {
    const detail = body.detail || body;
    if (detail && typeof detail === "object") {
      return {
        code: detail.code || null,
        message: detail.message || err.message || "Request failed",
        user_id: detail.user_id || null,
      };
    }
    if (typeof detail === "string") {
      return { code: null, message: detail };
    }
  }
  return { code: null, message: err.message || "Request failed" };
}


// ══════════════════════════════════════════════════════════════════
// Success modal
// ══════════════════════════════════════════════════════════════════
function TempPasswordModal({ payload, onClose }) {
  const [copied, setCopied] = React.useState(false);
  if (!payload) return null;
  const { email, temporary_password, invite_email_status } = payload;
  const inviteLine = (() => {
    switch (invite_email_status) {
      case "sent":
      case "mocked":
        return "The invite email was also sent.";
      case "suppressed":
        return "Invite email suppressed (recipient on suppression list).";
      case "skipped":
        return "No invite email sent — copy the password and share it manually.";
      case "failed":
      default:
        return "Invite email failed to send — copy the password and share it manually.";
    }
  })();
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(temporary_password);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      /* clipboard blocked — user can still select + copy */
    }
  };
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: "rgba(15, 23, 42, 0.62)" }}
      data-testid="unlinked-tech-temp-password-modal"
      onClick={onClose}
    >
      <div
        className="rounded-2xl p-6 max-w-md w-full mx-4"
        style={{ background: "#ffffff", boxShadow: "0 24px 60px rgba(15,23,42,0.30)" }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between mb-2">
          <h3 className="text-lg font-bold" style={{ color: "#0F172A" }}>
            User account created
          </h3>
          <button
            onClick={onClose}
            className="p-1 rounded-md hover:bg-slate-100"
            aria-label="Close"
            data-testid="unlinked-tech-temp-password-close"
          >
            <XIcon size={16} />
          </button>
        </div>
        <p className="text-sm mb-4" style={{ color: "#475569" }}>
          Login: <strong data-testid="unlinked-tech-temp-password-email">{email}</strong>
        </p>
        <div
          className="rounded-xl px-4 py-3 mb-2"
          style={{
            background: "#F8FAFC",
            border: "1px solid #E2E8F0",
          }}
        >
          <div className="text-[11px] uppercase tracking-wide mb-1"
                style={{ color: "#64748B" }}>
            Temporary password
          </div>
          <div className="flex items-center justify-between gap-2">
            <code
              className="text-base font-semibold"
              style={{ fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
                       color: "#0F172A", letterSpacing: "0.02em" }}
              data-testid="unlinked-tech-temp-password-value"
            >
              {temporary_password}
            </code>
            <button
              onClick={copy}
              className="text-xs font-semibold px-2.5 py-1.5 rounded-lg inline-flex items-center gap-1"
              style={{
                background: copied ? "#0F766E" : "#0F172A",
                color: "#ffffff",
              }}
              data-testid="unlinked-tech-temp-password-copy"
            >
              <CopyIcon size={12} />
              {copied ? "Copied" : "Copy"}
            </button>
          </div>
        </div>
        <p className="text-xs mb-4" style={{ color: "#64748B" }}
           data-testid="unlinked-tech-temp-password-invite-line">
          {inviteLine}
        </p>
        <div className="flex justify-end">
          <button
            onClick={onClose}
            className="text-sm font-bold px-4 py-2 rounded-xl"
            style={{ background: "#0F172A", color: "#ffffff" }}
            data-testid="unlinked-tech-temp-password-dismiss"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  );
}


// ══════════════════════════════════════════════════════════════════
// Confirm Remove modal — Feb-2026
// Inline plain-React modal (no Radix, no portal) so the widget can
// be mounted in isolation under vitest without a `ConfirmProvider`
// wrapper. Mirrors the sibling `TempPasswordModal` pattern already
// in this file for visual + testid consistency.
// ══════════════════════════════════════════════════════════════════
function ConfirmRemoveModal({ payload, busy, onCancel, onConfirm }) {
  if (!payload) return null;
  const { name, tech_id, email } = payload;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: "rgba(15, 23, 42, 0.62)" }}
      data-testid="team-unlinked-tech-remove-confirm-modal"
      onClick={busy ? undefined : onCancel}
    >
      <div
        className="rounded-2xl p-6 max-w-md w-full mx-4"
        style={{
          background: "#ffffff",
          boxShadow: "0 24px 60px rgba(15,23,42,0.30)",
          border: "1px solid #DC2626",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start gap-3 mb-3">
          <div
            className="rounded-full p-2 flex-shrink-0"
            style={{ background: "#FEE2E2" }}
            aria-hidden="true"
          >
            <Trash2 size={16} style={{ color: "#DC2626" }} />
          </div>
          <div className="flex-1">
            <h3
              className="text-lg font-bold"
              style={{ color: "#0F172A" }}
              data-testid="team-unlinked-tech-remove-confirm-title"
            >
              Remove unlinked technician?
            </h3>
            <p className="text-sm mt-1" style={{ color: "#475569" }}>
              This soft-deletes{" "}
              <strong>{name || tech_id}</strong>
              {email ? (
                <>
                  {" "}(<code style={{ fontSize: "12px" }}>{email}</code>)
                </>
              ) : null}
              {" "}from the Unlinked Technicians list. The record stays in
              the database and can be recovered by a super-admin, but it
              will no longer appear here.
            </p>
          </div>
        </div>
        <div className="flex justify-end gap-2 mt-2">
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            className="text-sm font-semibold px-4 py-2 rounded-xl"
            style={{
              background: "#F1F5F9",
              color: "#0F172A",
              cursor: busy ? "not-allowed" : "pointer",
              opacity: busy ? 0.6 : 1,
            }}
            data-testid="team-unlinked-tech-remove-confirm-cancel"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={busy}
            className="text-sm font-bold px-4 py-2 rounded-xl inline-flex items-center gap-1"
            style={{
              background: busy ? "#991B1B" : "#DC2626",
              color: "#ffffff",
              cursor: busy ? "not-allowed" : "pointer",
              opacity: busy ? 0.75 : 1,
            }}
            data-testid="team-unlinked-tech-remove-confirm-ok"
          >
            <Trash2 size={12} />
            {busy ? "Removing…" : "Remove"}
          </button>
        </div>
      </div>
    </div>
  );
}


// ══════════════════════════════════════════════════════════════════
// Main widget
// ══════════════════════════════════════════════════════════════════
export default function UnlinkedTechniciansWidget({ isAdmin, onCreated }) {
  const [rows, setRows] = React.useState(null);   // null=loading, []=empty
  const [busyTechId, setBusyTechId] = React.useState(null);
  const [rowErrors, setRowErrors] = React.useState({}); // {tech_id: {code, message}}
  const [modalPayload, setModalPayload] = React.useState(null);
  // Feb-2026 — open ConfirmRemoveModal with the pending row.
  const [removeTarget, setRemoveTarget] = React.useState(null);

  const load = React.useCallback(async () => {
    if (!isAdmin) return;
    try {
      const r = await api.get("/admin/technicians/unlinked");
      const list = Array.isArray(r?.technicians) ? r.technicians : [];
      setRows(list);
    } catch {
      // Silent — the widget is opt-in / attention-when-needed. A
      // GET failure just hides it until the next refresh.
      setRows([]);
    }
  }, [isAdmin]);

  React.useEffect(() => { load(); }, [load]);

  if (!isAdmin) return null;
  if (rows === null) return null;      // still loading — no flicker
  if (rows.length === 0) return null;  // nothing unlinked — hide entirely

  const createUser = async (row) => {
    setBusyTechId(row.tech_id);
    setRowErrors((prev) => {
      const next = { ...prev };
      delete next[row.tech_id];
      return next;
    });
    try {
      const r = await api.post(
        `/admin/technicians/${encodeURIComponent(row.tech_id)}/create-user`,
        {},
      );
      setModalPayload({
        email: r?.email || row.email,
        temporary_password: r?.temporary_password || "",
        invite_email_status: r?.invite_email_status || "skipped",
      });
      // Remove the row from the local list so the widget shrinks
      // toward zero without a re-fetch (which would race with the
      // caller's roster refresh below).
      setRows((prev) => (prev || []).filter((x) => x.tech_id !== row.tech_id));
      if (typeof onCreated === "function") {
        onCreated({ email: r?.email || row.email, user_id: r?.user_id });
      }
    } catch (err) {
      const payload = _readErrorPayload(err);
      setRowErrors((prev) => ({ ...prev, [row.tech_id]: payload }));
    } finally {
      setBusyTechId(null);
    }
  };

  // ──────────────────────────────────────────────────────────────
  // Feb-2026 — Remove (soft-delete) handler.
  // Mutation path: POST /admin/technicians/{tech_id}/remove
  //
  // On 200: filter the row out of the local `rows` state, clear
  //   any pending inline error on that row, close the modal. NO
  //   refetch — preserves the Refresh-test's call-count invariant.
  //
  // On 400 `already_removed` OR 404: treat as idempotent success
  //   (the backend state is already where the admin wants it;
  //   converge the UI silently, no inline error).
  //
  // On any other error (400 `not_unlinked_technician`, 403, 5xx):
  //   close the modal and surface the error inline on the row via
  //   the existing `rowErrors` map + error-row renderer.
  // ──────────────────────────────────────────────────────────────
  const removeTech = async (row) => {
    setBusyTechId(row.tech_id);
    try {
      await api.post(
        `/admin/technicians/${encodeURIComponent(row.tech_id)}/remove`,
        {},
      );
      setRows((prev) => (prev || []).filter((x) => x.tech_id !== row.tech_id));
      setRowErrors((prev) => {
        const next = { ...prev };
        delete next[row.tech_id];
        return next;
      });
      setRemoveTarget(null);
    } catch (err) {
      const payload = _readErrorPayload(err);
      const status = err?.status;
      if (payload.code === "already_removed" || status === 404) {
        // Idempotent — converge silently.
        setRows((prev) => (prev || []).filter((x) => x.tech_id !== row.tech_id));
        setRowErrors((prev) => {
          const next = { ...prev };
          delete next[row.tech_id];
          return next;
        });
        setRemoveTarget(null);
      } else {
        // Real failure — close modal, surface inline on the row.
        setRowErrors((prev) => ({ ...prev, [row.tech_id]: payload }));
        setRemoveTarget(null);
      }
    } finally {
      setBusyTechId(null);
    }
  };

  return (
    <>
      <div
        className="rounded-2xl p-4 mb-4"
        style={{
          background: "#FEF3C7",
          border: "1px solid #FCD34D",
        }}
        data-testid="unlinked-technicians-widget"
      >
        <div className="flex items-center gap-2 mb-3">
          <AlertCircle size={16} style={{ color: "#B45309" }} />
          <h3 className="text-sm font-bold uppercase tracking-wide"
              style={{ color: "#78350F" }}
              data-testid="unlinked-technicians-title">
            Unlinked Technicians
            <span
              className="ml-2 inline-flex items-center justify-center rounded-full text-[10px] font-bold px-2 py-0.5"
              style={{ background: "#B45309", color: "#FFFFFF" }}
              data-testid="unlinked-technicians-count-badge"
            >
              {rows.length}
            </span>
          </h3>
          <div className="flex-1" />
          <button
            onClick={load}
            className="inline-flex items-center gap-1 text-xs font-semibold px-2 py-1 rounded-lg"
            style={{
              background: "rgba(255,255,255,0.65)",
              border: "1px solid #FCD34D",
              color: "#78350F",
            }}
            data-testid="unlinked-technicians-refresh"
          >
            <RefreshCw size={11} /> Refresh
          </button>
        </div>

        <p className="text-xs mb-3" style={{ color: "#78350F" }}>
          These technicians don't have login credentials yet. Create a user
          account so they can sign in.
        </p>

        <div className="overflow-x-auto">
          <table
            className="w-full text-sm"
            style={{ borderCollapse: "separate", borderSpacing: 0 }}
            data-testid="unlinked-technicians-table"
          >
            <thead>
              <tr style={{ color: "#78350F" }}
                  className="text-xs uppercase tracking-wide">
                <th className="text-left py-2 pr-3">Name</th>
                <th className="text-left py-2 pr-3">Email</th>
                <th className="text-left py-2 pr-3">Phone</th>
                <th className="text-left py-2 pr-3">Created</th>
                <th className="text-right py-2 pl-3">Action</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const err = rowErrors[r.tech_id];
                const busy = busyTechId === r.tech_id;
                return (
                  <React.Fragment key={r.tech_id}>
                    <tr
                      data-testid={`unlinked-tech-row-${r.tech_id}`}
                      style={{ background: "rgba(255,255,255,0.55)" }}
                    >
                      <td className="py-2 pr-3 font-semibold"
                           style={{ color: "#0F172A" }}
                           data-testid={`unlinked-tech-name-${r.tech_id}`}>
                        {r.name || "—"}
                      </td>
                      <td className="py-2 pr-3"
                           style={{ color: "#334155" }}
                           data-testid={`unlinked-tech-email-${r.tech_id}`}>
                        {r.email || "—"}
                      </td>
                      <td className="py-2 pr-3"
                           style={{ color: "#334155" }}>
                        {r.phone || "—"}
                      </td>
                      <td className="py-2 pr-3"
                           style={{ color: "#64748B" }}>
                        {_formatCreatedAt(r.created_at)}
                      </td>
                      <td className="py-2 pl-3 text-right">
                        <div className="inline-flex items-center gap-2 justify-end">
                          <button
                            onClick={() => createUser(r)}
                            disabled={busy || !r.email}
                            className="inline-flex items-center gap-1 text-xs font-bold px-3 py-1.5 rounded-lg"
                            style={{
                              background: busy || !r.email
                                ? "#94A3B8" : "#0F172A",
                              color: "#ffffff",
                              cursor: busy || !r.email
                                ? "not-allowed" : "pointer",
                              opacity: busy ? 0.7 : 1,
                            }}
                            data-testid={`unlinked-tech-create-btn-${r.tech_id}`}
                            title={!r.email
                              ? "This tech doc has no email — set one first."
                              : undefined}
                          >
                            <UserPlus size={11} />
                            {busy ? "Creating…" : "Create user account"}
                          </button>
                          <button
                            onClick={() => setRemoveTarget(r)}
                            disabled={busy}
                            className="inline-flex items-center gap-1 text-xs font-bold px-3 py-1.5 rounded-lg"
                            style={{
                              background: busy ? "#94A3B8" : "#DC2626",
                              color: "#ffffff",
                              cursor: busy ? "not-allowed" : "pointer",
                              opacity: busy ? 0.7 : 1,
                            }}
                            data-testid={`team-unlinked-tech-remove-${r.tech_id}`}
                            title="Soft-delete this unlinked technician record"
                          >
                            <Trash2 size={11} />
                            Remove
                          </button>
                        </div>
                      </td>
                    </tr>
                    {err ? (
                      <tr
                        data-testid={`unlinked-tech-error-row-${r.tech_id}`}
                      >
                        <td colSpan={5} className="py-2 pr-3">
                          <div
                            className="rounded-lg px-3 py-2 text-xs flex items-center justify-between gap-2"
                            style={{
                              background: "#FEE2E2",
                              border: "1px solid #FCA5A5",
                              color: "#991B1B",
                            }}
                            data-testid={`unlinked-tech-error-${r.tech_id}`}
                          >
                            <span>
                              <strong>{err.code || "error"}: </strong>
                              {err.message}
                              {err.user_id ? (
                                <span className="opacity-70"> (existing user id: {err.user_id})</span>
                              ) : null}
                            </span>
                            <button
                              onClick={load}
                              className="inline-flex items-center gap-1 text-xs font-semibold px-2 py-1 rounded-md"
                              style={{
                                background: "#991B1B",
                                color: "#ffffff",
                              }}
                              data-testid={`unlinked-tech-error-refresh-${r.tech_id}`}
                            >
                              <RefreshCw size={10} /> Refresh
                            </button>
                          </div>
                        </td>
                      </tr>
                    ) : null}
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
      <TempPasswordModal
        payload={modalPayload}
        onClose={() => setModalPayload(null)}
      />
      <ConfirmRemoveModal
        payload={removeTarget}
        busy={!!removeTarget && busyTechId === removeTarget.tech_id}
        onCancel={() => setRemoveTarget(null)}
        onConfirm={() => removeTarget && removeTech(removeTarget)}
      />
    </>
  );
}
