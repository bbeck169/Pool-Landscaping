/**
 * Phase G4 · Feb-2026 — GPS per-user controls.
 * Admin+/manager only. Table + edit drawer.
 */
import React from "react";
import { toast } from "sonner";
import { api } from "@/api";
import { RefreshCw, X, Save } from "lucide-react";

function _fmt(ts) {
  if (!ts) return "—";
  try { return new Date(ts).toLocaleString(); } catch { return ts; }
}

function EditDrawer({ tech, onClose, onSaved }) {
  const [optOut, setOptOut] = React.useState(!!tech?.opted_out);
  const [retention, setRetention] = React.useState(
    tech?.retention_override_days ?? "");
  const [note, setNote] = React.useState(tech?.note || "");
  const [busy, setBusy] = React.useState(false);
  if (!tech) return null;
  const save = async () => {
    setBusy(true);
    try {
      const body = {
        gps_tracking_opt_out: !!optOut,
        gps_tracking_note: note,
      };
      if (retention === "" || retention === null) {
        // clear override — send null explicitly is not supported by
        // Optional[int]; send only when a value is provided.
      } else {
        const n = parseInt(retention, 10);
        if (!Number.isFinite(n) || n < 7 || n > 365) {
          toast.error("Retention must be 7–365 days"); setBusy(false); return;
        }
        body.gps_retention_override_days = n;
      }
      await api.patch(`/admin/gps/users/${tech.user_id}`, body);
      toast.success("Saved");
      onSaved?.();
      onClose?.();
    } catch (e) {
      toast.error("Save failed", { description: e?.message });
    } finally { setBusy(false); }
  };
  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4"
         data-testid="gps-user-edit-drawer" onClick={onClose}>
      <div className="bg-white rounded-lg shadow-xl max-w-md w-full p-6"
           onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold">
            GPS controls — {tech.user_name}
          </h3>
          <button type="button" onClick={onClose} aria-label="Close"
                  data-testid="gps-user-edit-close"><X size={18} /></button>
        </div>
        <label className="flex items-center gap-2 text-sm mb-3">
          <input type="checkbox" checked={optOut}
                  onChange={(e) => setOptOut(e.target.checked)}
                  data-testid="gps-user-opt-out-toggle" />
          This user opts out of GPS tracking
        </label>
        <label className="block text-sm mb-3">
          <div className="mb-1 text-zinc-700">
            Retention override (days)
          </div>
          <input type="number" min={7} max={365}
                  value={retention}
                  placeholder="Leave blank to use tenant default"
                  onChange={(e) => setRetention(e.target.value)}
                  className="w-full px-3 py-2 border border-zinc-200 rounded text-sm"
                  data-testid="gps-user-retention-input" />
        </label>
        <label className="block text-sm mb-3">
          <div className="mb-1 text-zinc-700">Admin note</div>
          <textarea rows={3} value={note}
                     onChange={(e) => setNote(e.target.value)}
                     className="w-full px-3 py-2 border border-zinc-200 rounded text-sm"
                     data-testid="gps-user-note-input" />
        </label>
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose}
                   className="px-3 py-1.5 border border-zinc-200 rounded text-sm">
            Cancel
          </button>
          <button type="button" onClick={save} disabled={busy}
                   className="inline-flex items-center gap-1 px-3 py-1.5 rounded bg-sky-600 text-white text-sm disabled:opacity-50"
                   data-testid="gps-user-save-btn">
            <Save size={14} /> {busy ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function GpsUsersPage() {
  const [data, setData] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [editing, setEditing] = React.useState(null);
  const [forbidden, setForbidden] = React.useState(false);

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.get("/admin/gps/tracking-summary");
      setData(r);
      setForbidden(false);
    } catch (e) {
      if ((e?.message || "").includes("403")) {
        setForbidden(true);
      } else {
        toast.error("Load failed", { description: e?.message });
      }
    } finally { setLoading(false); }
  }, []);

  React.useEffect(() => { load(); }, [load]);

  if (forbidden) {
    return (
      <div className="p-6" data-testid="gps-users-forbidden">
        <h1 className="text-2xl font-semibold text-zinc-900">
          Access denied
        </h1>
        <p className="text-sm text-zinc-500 mt-2">
          You don't have permission to view GPS user controls.
        </p>
      </div>
    );
  }

  const counts = data?.counts || {};
  const techs = data?.technicians || [];

  return (
    <div className="p-6 space-y-6" data-testid="gps-users-page">
      <header className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-zinc-900"
              data-testid="gps-users-title">GPS Per-User Controls</h1>
          <p className="text-sm text-zinc-500 mt-1">
            Toggle individual techs on/off and set per-user retention
            overrides. Overrides never widen the tenant's setting.
          </p>
        </div>
        <button type="button" onClick={load}
                className="inline-flex items-center gap-1 px-3 py-1.5 border border-zinc-200 rounded text-sm hover:bg-zinc-50"
                data-testid="gps-users-refresh">
          <RefreshCw size={14} /> Refresh
        </button>
      </header>

      <div className="bg-white border border-zinc-200 rounded-lg p-4 shadow-sm"
           data-testid="gps-users-summary">
        <div className="flex flex-wrap gap-6 text-sm">
          <div><span className="text-zinc-500">Tenant enabled:</span>{" "}
            <strong data-testid="gps-summary-tenant-enabled">
              {String(!!data?.tenant_enabled)}</strong></div>
          <div><span className="text-zinc-500">HR ack:</span>{" "}
            <strong>{String(!!data?.hr_agreement_ack)}</strong></div>
          <div><span className="text-zinc-500">Total techs:</span>{" "}
            <strong data-testid="gps-summary-total">
              {counts.total_technicians ?? 0}</strong></div>
          <div><span className="text-zinc-500">Opted in:</span>{" "}
            <strong className="text-emerald-700"
                     data-testid="gps-summary-opted-in">
              {counts.opted_in ?? 0}</strong></div>
          <div><span className="text-zinc-500">Opted out:</span>{" "}
            <strong className="text-red-700"
                     data-testid="gps-summary-opted-out">
              {counts.opted_out ?? 0}</strong></div>
          <div><span className="text-zinc-500">Clocked in now:</span>{" "}
            <strong data-testid="gps-summary-clocked-in">
              {counts.clocked_in_now ?? 0}</strong></div>
          <div><span className="text-zinc-500">Sending pings:</span>{" "}
            <strong data-testid="gps-summary-sending">
              {counts.sending_pings_now ?? 0}</strong></div>
        </div>
      </div>

      <div className="bg-white border border-zinc-200 rounded-lg shadow-sm overflow-hidden"
           data-testid="gps-users-table">
        {loading ? (
          <div className="p-6 text-sm text-zinc-500">Loading…</div>
        ) : techs.length === 0 ? (
          <div className="p-6 text-sm text-zinc-500"
               data-testid="gps-users-empty">No technicians.</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-zinc-50 text-zinc-500 text-xs">
              <tr>
                <th className="text-left px-4 py-2">Name</th>
                <th className="text-left px-4 py-2">Tracking</th>
                <th className="text-left px-4 py-2">Retention</th>
                <th className="text-left px-4 py-2">Clocked in</th>
                <th className="text-left px-4 py-2">Last ping</th>
                <th className="text-left px-4 py-2">Note</th>
                <th className="text-right px-4 py-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {techs.map((t) => (
                <tr key={t.user_id} className="border-t border-zinc-100"
                    data-testid={`gps-user-row-${t.user_id}`}>
                  <td className="px-4 py-2 font-medium">
                    {t.user_name}
                  </td>
                  <td className="px-4 py-2"
                      data-testid={`gps-user-status-${t.user_id}`}>
                    {t.opted_out ? (
                      <span className="inline-block rounded-full px-2 py-0.5 text-xs"
                            style={{ background: "#FEE2E2", color: "#7F1D1D" }}>
                        Opted out
                      </span>
                    ) : (
                      <span className="inline-block rounded-full px-2 py-0.5 text-xs"
                            style={{ background: "#DCFCE7", color: "#065F46" }}>
                        Opted in
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-2 text-zinc-700">
                    {t.retention_override_days ?? "tenant default"}
                  </td>
                  <td className="px-4 py-2">
                    {t.clocked_in ? "Yes" : "No"}
                  </td>
                  <td className="px-4 py-2 text-zinc-500 text-xs">
                    {_fmt(t.last_ping_at)}
                  </td>
                  <td className="px-4 py-2 text-zinc-500 text-xs truncate max-w-[240px]"
                      title={t.note || ""}>
                    {t.note || "—"}
                  </td>
                  <td className="px-4 py-2 text-right">
                    <button type="button"
                             onClick={() => setEditing(t)}
                             className="text-sky-600 hover:underline text-xs"
                             data-testid={`gps-user-edit-${t.user_id}`}>
                      Edit
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {editing && (
        <EditDrawer tech={editing}
                     onClose={() => setEditing(null)}
                     onSaved={load} />
      )}
    </div>
  );
}
