// Phase G5b · Feb-2026 — "Change attribution" modal for a driver stop.
//
// Loads same-day candidate jobs from /api/jobs (filtered by
// scheduled_date and status=scheduled), sorted by distance to the
// stop centroid. Fires POST /api/admin/gps/stops/{id}/attribute with
// either { job_id } or { unlink: true }.
import React from "react";
import { toast } from "sonner";
import { X, Link2Off, MapPin } from "lucide-react";
import { api } from "@/api";
import { AddressLink } from "@/components/customer";

function _haversineM(lat1, lon1, lat2, lon2) {
  const R = 6371000;
  const toRad = (d) => (d * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) *
      Math.sin(dLon / 2) ** 2;
  return R * 2 * Math.asin(Math.min(1, Math.sqrt(a)));
}

function _dayFromIso(iso) {
  if (!iso) return "";
  return String(iso).slice(0, 10);
}

export default function StopAttributionModal({ stop, onClose, onSaved }) {
  const [candidates, setCandidates] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [busy, setBusy] = React.useState(false);

  React.useEffect(() => {
    if (!stop) return;
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        // Fetch same-day scheduled jobs for the candidate list.
        const day = _dayFromIso(stop.started_at);
        const qs = new URLSearchParams();
        if (day) qs.set("scheduled_date", day);
        qs.set("status", "scheduled");
        qs.set("limit", "50");
        const rows = await api.get(`/jobs?${qs.toString()}`);
        const enriched = (rows || []).map((j) => {
          // Try job.lat/lon → property.lat/lng → customer.service_lat/lng.
          const jl = j.lat, jn = j.lon;
          const pl = j.property_lat || j.property?.lat;
          const pn = j.property_lng || j.property?.lng;
          const cl = j.customer?.service_lat;
          const cn = j.customer?.service_lng;
          const lat = jl ?? pl ?? cl ?? null;
          const lon = jn ?? pn ?? cn ?? null;
          let distance = null;
          if (typeof lat === "number" && typeof lon === "number"
              && typeof stop.center_lat === "number"
              && typeof stop.center_lon === "number") {
            distance = _haversineM(stop.center_lat, stop.center_lon, lat, lon);
          }
          return {
            id: j.id,
            name: j.title || j.service_type || "Job",
            customer_name: j.customer_name || "",
            address: j.address || j.property_address || "",
            lat, lon,
            distance_m: distance,
          };
        }).sort((a, b) => {
          if (a.distance_m == null && b.distance_m == null) return 0;
          if (a.distance_m == null) return 1;
          if (b.distance_m == null) return -1;
          return a.distance_m - b.distance_m;
        });
        if (!cancelled) setCandidates(enriched);
      } catch (e) {
        if (!cancelled) toast.error("Failed to load jobs", { description: e?.message });
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [stop]);

  const link = async (jobId) => {
    setBusy(true);
    try {
      const r = await api.post(`/admin/gps/stops/${stop.id}/attribute`,
        { job_id: jobId });
      toast.success("Stop linked to job");
      onSaved?.(r);
      onClose?.();
    } catch (e) {
      toast.error("Link failed", { description: e?.message });
    } finally { setBusy(false); }
  };

  const unlink = async () => {
    setBusy(true);
    try {
      const r = await api.post(`/admin/gps/stops/${stop.id}/attribute`,
        { unlink: true });
      toast.success("Stop unlinked");
      onSaved?.(r);
      onClose?.();
    } catch (e) {
      toast.error("Unlink failed", { description: e?.message });
    } finally { setBusy(false); }
  };

  if (!stop) return null;
  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4"
         data-testid="stop-attribution-modal" onClick={onClose}>
      <div className="bg-white rounded-lg shadow-xl max-w-lg w-full p-6"
           onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-lg font-semibold" data-testid="stop-attribution-title">
            Change attribution
          </h3>
          <button type="button" onClick={onClose} aria-label="Close"
            data-testid="stop-attribution-close"><X size={18} /></button>
        </div>
        <div className="text-xs text-zinc-500 mb-3"
             data-testid="stop-attribution-context">
          Stop {(stop.started_at || "").slice(11, 19)}
          {" – "}{(stop.ended_at || "").slice(11, 19)}
          {" · "}
          {typeof stop.center_lat === "number"
            ? `${stop.center_lat.toFixed(5)}, ${stop.center_lon.toFixed(5)}`
            : "(no coords)"}
        </div>
        {loading ? (
          <div className="text-sm text-zinc-500 py-6 text-center">Loading candidate jobs…</div>
        ) : candidates.length === 0 ? (
          <div className="text-sm text-zinc-500 py-6 text-center"
               data-testid="stop-attribution-nocands">
            No scheduled jobs on this day.
          </div>
        ) : (
          <ul className="divide-y divide-zinc-100 max-h-72 overflow-auto rounded border border-zinc-200"
              data-testid="stop-attribution-candidates">
            {candidates.slice(0, 20).map((c) => (
              <li key={c.id}
                  className="flex items-center gap-2 p-2 hover:bg-zinc-50"
                  data-testid={`stop-attribution-candidate-${c.id}`}>
                <MapPin size={14} className="text-sky-500" />
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium truncate">{c.name}</div>
                  <div className="text-xs text-zinc-500 truncate">
                    {c.customer_name || "—"}
                    {c.address ? <> · <AddressLink address={c.address} /></> : ""}
                  </div>
                </div>
                <div className="text-xs text-zinc-500 w-20 text-right">
                  {c.distance_m != null
                    ? `${Math.round(c.distance_m)} m`
                    : "no geo"}
                </div>
                <button type="button" onClick={() => link(c.id)}
                  disabled={busy}
                  className="text-sky-600 hover:underline text-xs disabled:opacity-50"
                  data-testid={`stop-attribution-link-${c.id}`}>
                  Link
                </button>
              </li>
            ))}
          </ul>
        )}
        <div className="flex justify-between items-center pt-4">
          <button type="button" onClick={unlink} disabled={busy}
            className="inline-flex items-center gap-1 text-red-600 hover:underline text-xs disabled:opacity-50"
            data-testid="stop-attribution-unlink-btn">
            <Link2Off size={14} /> Unlink
          </button>
          <button type="button" onClick={onClose}
            className="px-3 py-1.5 border border-zinc-200 rounded text-sm">
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
