import React, { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { LogIn, LogOut, RotateCcw, X, ShieldCheck } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import { Button } from "@/components/ui-kit";

/* Phase 13 parity-gap closures — two thin admin list pages that
   mirror the Expo mobile equivalents.  Feb-2026: extended with
   admin check-in / check-out / reset overrides. */

function Card({ children, testid }) {
  return (
    <div className="rounded-2xl bg-white p-5" style={{ border: `1px solid ${colors.border}` }} data-testid={testid}>
      {children}
    </div>
  );
}

/* ─── /leads ─── */
export function LeadsList() {
  const [rows, setRows] = useState(null);
  useEffect(() => { api.get("/leads").then((r) => setRows(Array.isArray(r) ? r : [])); }, []);
  return (
    <div className="p-4 md:p-8 max-w-6xl mx-auto space-y-4" data-testid="leads-list-page">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold">Leads</h1>
        <Link to="/leads/new" className="px-4 py-2 rounded-xl text-sm font-semibold text-white" style={{ backgroundColor: colors.brand }} data-testid="leads-new">+ New lead</Link>
      </div>
      <Card>
        {rows === null && <div className="text-sm" style={{ color: colors.onSurfaceSecondary }}>Loading…</div>}
        {rows && rows.length === 0 && <div className="text-sm text-center py-8" style={{ color: colors.onSurfaceSecondary }}>No leads yet — capture one from D2D or a public form.</div>}
        <table className="w-full text-sm">
          <tbody>
            {rows && rows.map((l) => (
              <tr key={l.id} className="border-b last:border-0" style={{ borderColor: colors.border }} data-testid={`lead-row-${l.id}`}>
                <td className="py-2 font-semibold">{l.name || "Unknown"}</td>
                <td className="py-2">{l.phone || l.email || "—"}</td>
                <td className="py-2 text-xs" style={{ color: colors.onSurfaceSecondary }}>{l.source}</td>
                <td className="py-2 text-xs" style={{ color: colors.onSurfaceSecondary }}>{l.status || "new"}</td>
                <td className="py-2 text-xs" style={{ color: colors.onSurfaceSecondary }}>{(l.created_at || "").slice(0, 10)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

/* ─── Admin override modal ─── */
function nowLocalIso() {
  const d = new Date();
  const off = d.getTimezoneOffset();
  const local = new Date(d.getTime() - off * 60000);
  return local.toISOString().slice(0, 16);
}

function AdminOverrideModal({ action, row, onClose, onDone }) {
  // action ∈ 'checkin' | 'checkout' | 'reset'
  const [when, setWhen] = useState(nowLocalIso());
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const title = action === "checkin" ? "Check in on tech's behalf"
    : action === "checkout" ? "Check tech out"
    : "Reset check-in history";

  const submit = async () => {
    if (!row?.job_id || !row?.user_id) {
      setErr("This row is missing job_id or user_id — can't override.");
      return;
    }
    setBusy(true); setErr("");
    try {
      const iso = new Date(when).toISOString();
      if (action === "checkin") {
        await api.post(`/jobs/${row.job_id}/checkins/admin-checkin`, {
          user_id: row.user_id, checked_in_at: iso, notes: note,
        });
      } else if (action === "checkout") {
        await api.post(`/jobs/${row.job_id}/checkins/admin-checkout`, {
          user_id: row.user_id, checked_out_at: iso, notes: note,
        });
      } else {
        if (!note.trim()) { setErr("Reason is required for reset."); setBusy(false); return; }
        await api.post(`/jobs/${row.job_id}/checkins/admin-reset`, {
          user_id: row.user_id, reason: note,
        });
      }
      onDone?.();
    } catch (e) {
      setErr(e?.data?.detail || e?.message || "Override failed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: "rgba(0,0,0,0.55)" }}
      onClick={onClose}
      data-testid="checkin-override-backdrop"
    >
      <div
        className="w-full max-w-md rounded-2xl overflow-hidden shadow-2xl"
        style={{ background: colors.surface }}
        onClick={(e) => e.stopPropagation()}
        data-testid="checkin-override-modal"
      >
        <header
          className="px-5 py-3 flex items-center justify-between"
          style={{ borderBottom: `1px solid ${colors.border}` }}
        >
          <div className="flex items-center gap-2 text-base font-bold"
                style={{ color: colors.onSurface }}>
            <ShieldCheck size={16} /> {title}
          </div>
          <button onClick={onClose} data-testid="checkin-override-close"
                  style={{ color: colors.onSurfaceSecondary }}><X size={16} /></button>
        </header>
        <div className="px-5 py-4 space-y-3">
          <div className="text-xs"
                style={{ color: colors.onSurfaceSecondary }}>
            Tech: <span className="font-semibold"
                          style={{ color: colors.onSurface }}>
              {row?.technician_name || row?.tech_name || row?.user_id}
            </span><br />
            Job: <span className="font-mono">{row?.job_id}</span>
          </div>
          {action !== "reset" ? (
            <div>
              <label className="text-xs uppercase font-semibold block mb-1"
                      style={{ color: colors.onSurfaceSecondary }}>
                {action === "checkin" ? "Checked in at" : "Checked out at"}
              </label>
              <input
                type="datetime-local"
                value={when}
                onChange={(e) => setWhen(e.target.value)}
                className="w-full px-3 py-2 text-sm rounded-lg"
                style={{ background: colors.surface,
                          border: `1px solid ${colors.border}` }}
                data-testid="checkin-override-when"
              />
            </div>
          ) : null}
          <div>
            <label className="text-xs uppercase font-semibold block mb-1"
                    style={{ color: colors.onSurfaceSecondary }}>
              {action === "reset" ? "Reason (required)" : "Note (optional)"}
            </label>
            <input
              type="text"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              className="w-full px-3 py-2 text-sm rounded-lg"
              style={{ background: colors.surface,
                        border: `1px solid ${colors.border}` }}
              placeholder={action === "reset"
                ? "e.g., Duplicate entry from GPS glitch"
                : "Reason for admin override"}
              data-testid="checkin-override-note"
            />
          </div>
          {err ? (
            <div className="rounded-xl p-2 text-xs"
                  style={{ background: "#FEE2E2", color: "#7F1D1D",
                            border: "1px solid #FCA5A5" }}
                  data-testid="checkin-override-error">
              {String(err).slice(0, 200)}
            </div>
          ) : null}
        </div>
        <footer
          className="px-5 py-3 flex justify-end gap-2"
          style={{ borderTop: `1px solid ${colors.border}`,
                    background: colors.surfaceSecondary }}
        >
          <Button variant="ghost" onClick={onClose}
                  testid="checkin-override-cancel">Cancel</Button>
          <Button onClick={submit} disabled={busy}
                  testid="checkin-override-submit">
            {busy ? "Working…" : "Confirm"}
          </Button>
        </footer>
      </div>
    </div>
  );
}

/* ─── /checkins ─── */
export function CheckinsList() {
  const [rows, setRows] = useState(null);
  const [mode, setMode] = useState(null);   // {action, row} for modal
  const [tick, setTick] = useState(0);

  useEffect(() => {
    api.get("/attendance/checkins").catch(() => api.get("/checkins"))
      .then((r) => setRows(Array.isArray(r) ? r : []))
      .catch(() => setRows([]));
  }, [tick]);

  // Deduce a per-row status ("checked_in" if an open check-in exists for
  // the tech+job pair in the visible rows, else "pending").
  const rowStatus = useMemo(() => {
    const status = {};
    (rows || []).forEach((r) => {
      const key = `${r.job_id}::${r.user_id}`;
      // If there's ANY row for this pair without checked_out_at, they
      // are currently on-site.
      if (r.event !== "admin_reset" && r.checked_out_at == null
          && (r.event === "checkin" || r.event === "admin_checkin"
              || r.event == null)) {
        status[key] = "checked_in";
      } else if (!status[key]) {
        status[key] = "pending";
      }
    });
    return status;
  }, [rows]);

  const openModal = (action, row) => setMode({ action, row });
  const closeModal = () => setMode(null);
  const done = () => { setMode(null); setTick((t) => t + 1); };

  return (
    <div className="p-4 md:p-8 max-w-6xl mx-auto space-y-4" data-testid="checkins-page">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold">Job check-ins</h1>
        <div className="text-xs" style={{ color: colors.onSurfaceSecondary }}>
          Admin overrides are logged in the audit trail.
        </div>
      </div>
      <Card>
        {rows === null && <div className="text-sm" style={{ color: colors.onSurfaceSecondary }}>Loading…</div>}
        {rows && rows.length === 0 && <div className="text-sm text-center py-8" style={{ color: colors.onSurfaceSecondary }}>No check-ins recorded yet.</div>}
        {rows && rows.map((c) => {
          const key = `${c.job_id}::${c.user_id}`;
          const st = rowStatus[key] || "pending";
          const canOverride = c.job_id && c.user_id;
          return (
            <div key={c.id}
                  className="py-2 border-b last:border-0 flex items-center justify-between gap-3"
                  style={{ borderColor: colors.border }}
                  data-testid={`checkin-${c.id}`}>
              <div className="flex-1 min-w-0">
                <div className="font-semibold text-sm">
                  {c.technician_name || c.tech_name || c.user_id || "Unknown tech"}
                </div>
                <div className="text-xs truncate"
                      style={{ color: colors.onSurfaceSecondary }}>
                  {c.address || c.job_id} · {(c.created_at || "").slice(0, 16).replace("T", " ")}
                </div>
              </div>
              {c.event && (
                <span className="text-xs font-semibold px-2 py-0.5 rounded-full whitespace-nowrap"
                      style={{ backgroundColor: colors.surfaceSecondary }}>
                  {c.event}
                </span>
              )}
              <div className="flex items-center gap-1">
                {st !== "checked_in" && canOverride ? (
                  <button
                    onClick={() => openModal("checkin", c)}
                    className="text-xs px-2 py-1 rounded-lg font-semibold flex items-center gap-1"
                    style={{ background: "#DCFCE7", color: "#166534" }}
                    data-testid={`checkin-row-checkin-${c.id}`}
                    title="Check in as tech"
                  ><LogIn size={11} /> Check in</button>
                ) : null}
                {st === "checked_in" && canOverride ? (
                  <button
                    onClick={() => openModal("checkout", c)}
                    className="text-xs px-2 py-1 rounded-lg font-semibold flex items-center gap-1"
                    style={{ background: "#FEF3C7", color: "#78350F" }}
                    data-testid={`checkin-row-checkout-${c.id}`}
                    title="Check out"
                  ><LogOut size={11} /> Check out</button>
                ) : null}
                {canOverride ? (
                  <button
                    onClick={() => openModal("reset", c)}
                    className="text-xs px-2 py-1 rounded-lg font-semibold flex items-center gap-1"
                    style={{ background: "#FEE2E2", color: "#7F1D1D" }}
                    data-testid={`checkin-row-reset-${c.id}`}
                    title="Reset check-in history for this tech + job"
                  ><RotateCcw size={11} /> Reset</button>
                ) : null}
              </div>
            </div>
          );
        })}
      </Card>
      {mode ? (
        <AdminOverrideModal
          action={mode.action}
          row={mode.row}
          onClose={closeModal}
          onDone={done}
        />
      ) : null}
    </div>
  );
}
