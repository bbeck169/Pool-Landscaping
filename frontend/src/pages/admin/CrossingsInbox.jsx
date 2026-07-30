/**
 * Phase G5a · Feb-2026 — Geofence crossings inbox.
 * Lists /api/geofence-events with filters + acknowledge action.
 */
import React from "react";
import { toast } from "sonner";
import { api } from "@/api";
import { RefreshCw, CheckCircle2 } from "lucide-react";

function _fmt(ts) {
  if (!ts) return "—";
  try { return new Date(ts).toLocaleString(); } catch { return ts; }
}

export default function CrossingsInbox() {
  const [items, setItems] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [forbidden, setForbidden] = React.useState(false);
  const [crossingFilter, setCrossingFilter] = React.useState("");
  const [ackFilter, setAckFilter] = React.useState("false");

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      const qs = new URLSearchParams();
      if (crossingFilter) qs.set("crossing", crossingFilter);
      if (ackFilter !== "") qs.set("acknowledged", ackFilter);
      qs.set("limit", "200");
      const r = await api.get(`/geofence-events?${qs.toString()}`);
      setItems(r?.items || []);
      setForbidden(false);
    } catch (e) {
      if ((e?.message || "").includes("403")) setForbidden(true);
      else toast.error("Load failed", { description: e?.message });
    } finally { setLoading(false); }
  }, [crossingFilter, ackFilter]);

  React.useEffect(() => { load(); }, [load]);

  const ack = async (eid) => {
    try {
      await api.post(`/geofence-events/${eid}/acknowledge`);
      toast.success("Acknowledged");
      load();
    } catch (e) {
      toast.error("Failed", { description: e?.message });
    }
  };

  if (forbidden) {
    return (
      <div className="p-6" data-testid="crossings-inbox-forbidden">
        <h1 className="text-2xl font-semibold text-zinc-900">Access denied</h1>
        <p className="text-sm text-zinc-500 mt-2">
          You don't have permission to view geofence crossings.
        </p>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-4" data-testid="crossings-inbox-page">
      <header className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-zinc-900"
              data-testid="crossings-inbox-title">Geofence Crossings</h1>
          <p className="text-sm text-zinc-500 mt-1">
            Enter/exit events for active geofences. Acknowledge to clear.
          </p>
        </div>
        <button type="button" onClick={load}
          className="inline-flex items-center gap-1 px-3 py-1.5 border border-zinc-200 rounded text-sm hover:bg-zinc-50"
          data-testid="crossings-inbox-refresh">
          <RefreshCw size={14} /> Refresh
        </button>
      </header>

      <div className="flex flex-wrap gap-3 text-sm" data-testid="crossings-inbox-filters">
        <label className="flex items-center gap-2">
          <span className="text-zinc-600">Type</span>
          <select value={crossingFilter}
            onChange={(e) => setCrossingFilter(e.target.value)}
            className="px-2 py-1 border border-zinc-200 rounded"
            data-testid="crossings-inbox-filter-crossing">
            <option value="">All</option>
            <option value="enter">Enter</option>
            <option value="exit">Exit</option>
          </select>
        </label>
        <label className="flex items-center gap-2">
          <span className="text-zinc-600">Acknowledged</span>
          <select value={ackFilter}
            onChange={(e) => setAckFilter(e.target.value)}
            className="px-2 py-1 border border-zinc-200 rounded"
            data-testid="crossings-inbox-filter-ack">
            <option value="">Any</option>
            <option value="false">Unacknowledged</option>
            <option value="true">Acknowledged</option>
          </select>
        </label>
      </div>

      <div className="bg-white border border-zinc-200 rounded-lg shadow-sm overflow-hidden"
           data-testid="crossings-inbox-table">
        {loading ? (
          <div className="p-6 text-sm text-zinc-500">Loading…</div>
        ) : items.length === 0 ? (
          <div className="p-6 text-sm text-zinc-500"
               data-testid="crossings-inbox-empty">No crossings.</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-zinc-50 text-zinc-500 text-xs">
              <tr>
                <th className="text-left px-4 py-2">When</th>
                <th className="text-left px-4 py-2">Technician</th>
                <th className="text-left px-4 py-2">Geofence</th>
                <th className="text-left px-4 py-2">Direction</th>
                <th className="text-left px-4 py-2">Lat/Lon</th>
                <th className="text-right px-4 py-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map((e) => (
                <tr key={e.id} className="border-t border-zinc-100"
                    data-testid={`crossings-inbox-row-${e.id}`}>
                  <td className="px-4 py-2 text-zinc-700">{_fmt(e.detected_at)}</td>
                  <td className="px-4 py-2">{e.user_name || e.user_id}</td>
                  <td className="px-4 py-2">{e.geofence_name || e.geofence_id}</td>
                  <td className="px-4 py-2">
                    {e.crossing === "enter" ? (
                      <span className="inline-block rounded-full px-2 py-0.5 text-xs"
                        style={{ background: "#DCFCE7", color: "#065F46" }}
                        data-testid={`crossings-inbox-crossing-${e.id}`}>
                        Enter
                      </span>
                    ) : (
                      <span className="inline-block rounded-full px-2 py-0.5 text-xs"
                        style={{ background: "#FEF3C7", color: "#92400E" }}
                        data-testid={`crossings-inbox-crossing-${e.id}`}>
                        Exit
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-2 text-zinc-500 text-xs">
                    {typeof e.lat === "number" && typeof e.lon === "number"
                      ? `${e.lat.toFixed(5)}, ${e.lon.toFixed(5)}` : "—"}
                  </td>
                  <td className="px-4 py-2 text-right">
                    {e.acknowledged ? (
                      <span className="text-xs text-zinc-400"
                            data-testid={`crossings-inbox-ack-${e.id}`}>Acknowledged</span>
                    ) : (
                      <button type="button" onClick={() => ack(e.id)}
                        className="inline-flex items-center gap-1 text-sky-600 hover:underline text-xs"
                        data-testid={`crossings-inbox-ack-btn-${e.id}`}>
                        <CheckCircle2 size={12} /> Acknowledge
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
