/**
 * Phase 20B.1b · Admin appointment approval queue.
 */
import React, { useEffect, useState } from "react";
import { CalendarClock, Check, X, RefreshCw } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";

export default function AppointmentsQueue() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [reject, setReject] = useState(null);
  const [reason, setReason] = useState("");
  const [toast, setToast] = useState("");

  const load = () => {
    setLoading(true);
    api.get("/portal/appointments")
      .then((r) => { setRows(r); setLoading(false); })
      .catch(() => setLoading(false));
  };

  useEffect(load, []);
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(""), 3000);
    return () => clearTimeout(t);
  }, [toast]);

  const confirm = async (id) => {
    try {
      const r = await api.post(`/portal/appointments/${id}/confirm`);
      setToast(`Confirmed — job ${String(r.job_id || "").slice(0, 8)} created`);
      load();
    } catch (e) { setToast(e.message); }
  };
  const doReject = async () => {
    if (!reason.trim()) return;
    try {
      await api.post(`/portal/appointments/${reject.id}/reject`, { reason });
      setToast("Rejected"); setReject(null); setReason(""); load();
    } catch (e) { setToast(e.message); }
  };

  const pending = rows.filter((r) => r.status === "pending");
  const decided = rows.filter((r) => r.status !== "pending");

  return (
    <div className="max-w-5xl mx-auto p-4 md:p-6" data-testid="admin-appointments-page">
      <div className="flex items-center justify-between mb-6">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <CalendarClock size={22} style={{ color: colors.brand }}/>
            <h1 className="text-3xl font-bold" style={{ color: colors.onSurface }}>
              Booking Requests
            </h1>
          </div>
          <p className="text-sm" style={{ color: colors.muted }}>
            Confirm or reject customer-submitted appointment requests.
          </p>
        </div>
        <button onClick={load}
                className="p-2 rounded-lg"
                style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
                data-testid="admin-appointments-refresh">
          <RefreshCw size={16}/>
        </button>
      </div>

      <h2 className="text-sm font-bold mb-3 uppercase tracking-wider"
          style={{ color: colors.muted }}>
        Pending ({pending.length})
      </h2>
      <div className="space-y-2 mb-8" data-testid="admin-appointments-pending">
        {loading ? (
          <div className="text-sm" style={{ color: colors.muted }}>Loading…</div>
        ) : pending.length === 0 ? (
          <div className="text-sm rounded-xl p-4"
               style={{ backgroundColor: colors.surface, border: `1px dashed ${colors.border}`, color: colors.muted }}>
            Nothing pending right now.
          </div>
        ) : pending.map((r) => (
          <div key={r.id} className="rounded-xl p-4"
               style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
               data-testid={`appt-row-${r.id}`}>
            <div className="flex items-start justify-between gap-4 flex-wrap">
              <div>
                <div className="text-sm font-bold" style={{ color: colors.onSurface }}>
                  {r.customer_name} · {r.service_type}
                </div>
                <div className="text-xs mt-1" style={{ color: colors.muted }}>
                  {r.preferred_date} · {r.preferred_window}
                  {r.notes ? ` · "${r.notes.slice(0, 60)}"` : ""}
                </div>
              </div>
              <div className="flex gap-2">
                <button onClick={() => confirm(r.id)}
                        className="flex items-center gap-1 px-3 py-1.5 text-sm font-semibold rounded-lg"
                        style={{ backgroundColor: "#059669", color: "#fff" }}
                        data-testid={`appt-confirm-${r.id}`}>
                  <Check size={14}/> Confirm
                </button>
                <button onClick={() => setReject(r)}
                        className="flex items-center gap-1 px-3 py-1.5 text-sm font-semibold rounded-lg"
                        style={{ backgroundColor: colors.surface, color: "#991B1B",
                                 border: `1px solid #FCA5A5` }}
                        data-testid={`appt-reject-${r.id}`}>
                  <X size={14}/> Reject
                </button>
              </div>
            </div>
          </div>
        ))}
      </div>

      {decided.length > 0 && (
        <>
          <h2 className="text-sm font-bold mb-3 uppercase tracking-wider"
              style={{ color: colors.muted }}>Recent</h2>
          <div className="space-y-2">
            {decided.slice(0, 20).map((r) => (
              <div key={r.id} className="rounded-lg p-3 flex items-center gap-3"
                   style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-semibold truncate" style={{ color: colors.onSurface }}>
                    {r.customer_name} · {r.service_type}
                  </div>
                  <div className="text-xs truncate" style={{ color: colors.muted }}>
                    {r.preferred_date} · {r.preferred_window}
                    {r.reject_reason ? ` · Rejected: ${r.reject_reason.slice(0, 40)}` : ""}
                  </div>
                </div>
                <span className="text-xs font-bold uppercase px-2 py-0.5 rounded"
                      style={{
                        backgroundColor: r.status === "confirmed" ? "#DCFCE7" : "#FEE2E2",
                        color: r.status === "confirmed" ? "#166534" : "#991B1B",
                      }}>
                  {r.status}
                </span>
              </div>
            ))}
          </div>
        </>
      )}

      {reject && (
        <div className="fixed inset-0 z-40 flex items-center justify-center p-4"
             style={{ background: "rgba(0,0,0,0.5)" }}
             onClick={() => setReject(null)}
             data-testid="appt-reject-modal">
          <div className="max-w-md w-full p-6 rounded-2xl" onClick={(e) => e.stopPropagation()}
               style={{ backgroundColor: colors.surface }}>
            <h3 className="text-lg font-bold mb-3" style={{ color: colors.onSurface }}>
              Reject appointment
            </h3>
            <textarea value={reason} onChange={(e) => setReason(e.target.value)}
                      placeholder="Reason (required, shared with customer)"
                      rows={3}
                      className="w-full rounded-lg p-2.5 text-sm mb-3"
                      style={{ backgroundColor: colors.background, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                      data-testid="appt-reject-reason" />
            <div className="flex justify-end gap-2">
              <button onClick={() => setReject(null)}
                      className="px-3 py-1.5 text-sm rounded-lg"
                      style={{ border: `1px solid ${colors.border}`, color: colors.onSurface }}>
                Cancel
              </button>
              <button onClick={doReject}
                      className="px-3 py-1.5 text-sm font-semibold rounded-lg"
                      style={{ backgroundColor: "#DC2626", color: "#fff" }}
                      data-testid="appt-reject-confirm">
                Reject
              </button>
            </div>
          </div>
        </div>
      )}

      {toast && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 px-4 py-2.5 rounded-xl text-sm font-semibold shadow-lg z-50"
             style={{ backgroundColor: colors.onSurface, color: "#fff" }}
             data-testid="admin-appointments-toast">
          {toast}
        </div>
      )}
    </div>
  );
}
