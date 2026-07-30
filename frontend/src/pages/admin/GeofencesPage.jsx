/**
 * Phase G5a · Feb-2026 — Geofences admin page.
 *
 * Interactive Google Map with a DrawingManager to sketch circles and
 * polygons. Sidebar lists existing fences; clicking a row highlights
 * its shape on the map and opens a detail drawer with recent events.
 *
 * Uses the shared APIProvider mounted in AppLayout.jsx (libraries
 * `marker` + `drawing`). Falls back to a no-map form UI when the
 * Google JS API is unavailable (e.g., under Vitest or if the key is
 * missing) so the page never breaks the shell.
 */
import React from "react";
import { toast } from "sonner";
import { Map, useMap } from "@vis.gl/react-google-maps";
import { RefreshCw, Trash2, MapPin, X, Save, PenTool } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";

const AZ_CENTER = { lat: 33.6975, lng: -112.3708 };

function _fmt(ts) {
  if (!ts) return "—";
  try { return new Date(ts).toLocaleString(); } catch { return ts; }
}

// ── Click-based drawing overlay (DrawingManager was deprecated in
//    Maps JS v3.65). For CIRCLE: first click sets center, second click
//    sets a point on the perimeter → radius = haversine distance.
//    For POLYGON: each click adds a vertex, "Finish" button closes.
function DrawTools({ mode, onDrawn, onFinishRequested }) {
  const map = useMap();
  const centerRef = React.useRef(null);      // circle center latLng
  const centerMarkerRef = React.useRef(null);
  const previewRef = React.useRef(null);     // circle/polyline preview
  const polyPointsRef = React.useRef([]);    // polygon vertex list
  const clickListenerRef = React.useRef(null);

  // Reset any in-progress overlay when the mode changes.
  const resetPreview = React.useCallback(() => {
    if (previewRef.current) {
      previewRef.current.setMap(null);
      previewRef.current = null;
    }
    if (centerMarkerRef.current) {
      centerMarkerRef.current.setMap(null);
      centerMarkerRef.current = null;
    }
    centerRef.current = null;
    polyPointsRef.current = [];
  }, []);

  React.useEffect(() => {
    if (!map || typeof window === "undefined") return undefined;
    const gm = window.google?.maps;
    if (!gm) return undefined;
    resetPreview();
    if (!mode) return () => resetPreview();

    const handleClick = (evt) => {
      const ll = evt.latLng;
      if (!ll) return;
      if (mode === "circle") {
        if (!centerRef.current) {
          // First click — place the center.
          centerRef.current = ll;
          centerMarkerRef.current = new gm.Circle({
            map,
            center: ll,
            radius: 1,
            fillColor: "#0EA5E9",
            fillOpacity: 0.8,
            strokeColor: "#0EA5E9",
            strokeWeight: 1,
            clickable: false,
          });
        } else {
          // Second click — radius = distance from center.
          const rMeters = gm.geometry?.spherical
            ? gm.geometry.spherical.computeDistanceBetween(
                centerRef.current, ll)
            : haversineFallback(
                centerRef.current.lat(), centerRef.current.lng(),
                ll.lat(), ll.lng());
          onDrawn({
            shape: "circle",
            center_lat: centerRef.current.lat(),
            center_lon: centerRef.current.lng(),
            radius_m: Math.max(5, Math.round(rMeters)),
          });
          resetPreview();
        }
      } else if (mode === "polygon") {
        polyPointsRef.current.push(ll);
        // Redraw preview polyline.
        if (previewRef.current) previewRef.current.setMap(null);
        previewRef.current = new gm.Polyline({
          map,
          path: polyPointsRef.current,
          strokeColor: "#0EA5E9",
          strokeWeight: 2,
          clickable: false,
        });
      }
    };

    clickListenerRef.current = gm.event.addListener(map, "click", handleClick);
    return () => {
      if (clickListenerRef.current) {
        gm.event.removeListener(clickListenerRef.current);
        clickListenerRef.current = null;
      }
      resetPreview();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, mode]);

  // Expose a way for the parent to finish a polygon in progress.
  React.useEffect(() => {
    if (mode !== "polygon" || !onFinishRequested) return;
    onFinishRequested.current = () => {
      const pts = polyPointsRef.current || [];
      if (pts.length < 3) return false;
      onDrawn({
        shape: "polygon",
        points: pts.map((p) => ({ lat: p.lat(), lon: p.lng() })),
      });
      resetPreview();
      return true;
    };
    return () => {
      if (onFinishRequested) onFinishRequested.current = null;
    };
  }, [mode, onDrawn, onFinishRequested, resetPreview]);

  return null;
}

function haversineFallback(lat1, lon1, lat2, lon2) {
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

// ── Existing shape overlays ─────────────────────────────────────────
function ExistingFencesLayer({ fences, activeId, onPick }) {
  const map = useMap();
  const overlaysRef = React.useRef([]);
  React.useEffect(() => {
    if (!map || typeof window === "undefined") return undefined;
    const gm = window.google?.maps;
    if (!gm) return undefined;
    overlaysRef.current.forEach((o) => o.setMap(null));
    overlaysRef.current = [];
    (fences || []).forEach((f) => {
      const active = f.id === activeId;
      const styleBase = {
        strokeWeight: active ? 3 : 2,
        strokeColor: f.active === false ? "#94A3B8"
          : (active ? "#DB2777" : "#0EA5E9"),
        fillColor: f.active === false ? "#CBD5E1"
          : (active ? "#DB2777" : "#0EA5E9"),
        fillOpacity: 0.15,
        clickable: true,
        map,
      };
      if (f.shape === "circle") {
        const c = new gm.Circle({
          ...styleBase,
          center: { lat: f.center_lat, lng: f.center_lon },
          radius: f.radius_m,
        });
        c.addListener("click", () => onPick(f.id));
        overlaysRef.current.push(c);
      } else if (f.shape === "polygon" && (f.points || []).length >= 3) {
        const p = new gm.Polygon({
          ...styleBase,
          paths: f.points.map((pt) => ({ lat: pt.lat, lng: pt.lon })),
        });
        p.addListener("click", () => onPick(f.id));
        overlaysRef.current.push(p);
      }
    });
    return () => {
      overlaysRef.current.forEach((o) => o.setMap(null));
      overlaysRef.current = [];
    };
  }, [map, fences, activeId, onPick]);
  return null;
}

// ── Create/edit form drawer ─────────────────────────────────────────
function FenceForm({ pending, onSubmit, onCancel }) {
  const [name, setName] = React.useState("");
  const [kind, setKind] = React.useState("custom");
  const [enterAlert, setEnterAlert] = React.useState(true);
  const [exitAlert, setExitAlert] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  if (!pending) return null;

  const submit = async () => {
    if (!name.trim()) { toast.error("Name required"); return; }
    setBusy(true);
    try {
      const body = {
        name: name.trim(),
        kind,
        shape: pending.shape,
        alert_on_enter: enterAlert,
        alert_on_exit: exitAlert,
        active: true,
      };
      if (pending.shape === "circle") {
        body.center_lat = pending.center_lat;
        body.center_lon = pending.center_lon;
        body.radius_m = pending.radius_m;
      } else if (pending.shape === "polygon") {
        body.points = pending.points;
      }
      const row = await api.post("/geofences", body);
      toast.success("Geofence created");
      onSubmit(row);
    } catch (e) {
      toast.error("Create failed", { description: e?.message });
    } finally { setBusy(false); }
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4"
         data-testid="geofences-create-drawer" onClick={onCancel}>
      <div className="bg-white rounded-lg shadow-xl max-w-md w-full p-6"
           onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold">
            New geofence — {pending.shape}
          </h3>
          <button type="button" onClick={onCancel} aria-label="Close"
                  data-testid="geofences-create-close"><X size={18} /></button>
        </div>
        <label className="block text-sm mb-3">
          <div className="mb-1 text-zinc-700">Name</div>
          <input value={name} onChange={(e) => setName(e.target.value)}
            className="w-full px-3 py-2 border border-zinc-200 rounded text-sm"
            placeholder="Depot / Job site / No-go zone"
            data-testid="geofences-create-name" />
        </label>
        <label className="block text-sm mb-3">
          <div className="mb-1 text-zinc-700">Kind</div>
          <select value={kind} onChange={(e) => setKind(e.target.value)}
            className="w-full px-3 py-2 border border-zinc-200 rounded text-sm"
            data-testid="geofences-create-kind">
            <option value="custom">Custom</option>
            <option value="job">Job site</option>
            <option value="customer">Customer</option>
            <option value="depot">Depot</option>
            <option value="no_go">No-go zone</option>
          </select>
        </label>
        <label className="flex items-center gap-2 text-sm mb-2">
          <input type="checkbox" checked={enterAlert}
            onChange={(e) => setEnterAlert(e.target.checked)}
            data-testid="geofences-create-enter" />
          Alert on enter
        </label>
        <label className="flex items-center gap-2 text-sm mb-4">
          <input type="checkbox" checked={exitAlert}
            onChange={(e) => setExitAlert(e.target.checked)}
            data-testid="geofences-create-exit" />
          Alert on exit
        </label>
        {pending.shape === "circle" ? (
          <div className="text-xs text-zinc-500 mb-3"
               data-testid="geofences-create-shape-info">
            Circle center: ({pending.center_lat.toFixed(5)},
            {" "}{pending.center_lon.toFixed(5)}) — radius {pending.radius_m}m
          </div>
        ) : (
          <div className="text-xs text-zinc-500 mb-3"
               data-testid="geofences-create-shape-info">
            Polygon with {pending.points.length} vertices
          </div>
        )}
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onCancel}
            className="px-3 py-1.5 border border-zinc-200 rounded text-sm">
            Cancel
          </button>
          <button type="button" onClick={submit} disabled={busy}
            className="inline-flex items-center gap-1 px-3 py-1.5 rounded bg-sky-600 text-white text-sm disabled:opacity-50"
            data-testid="geofences-create-save">
            <Save size={14} /> {busy ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Fallback (no google.maps) form-only creator ─────────────────────
function ManualCreatePanel({ onCreated }) {
  const [name, setName] = React.useState("");
  const [lat, setLat] = React.useState("");
  const [lon, setLon] = React.useState("");
  const [radius, setRadius] = React.useState("100");
  const [busy, setBusy] = React.useState(false);
  const submit = async () => {
    const cLat = parseFloat(lat), cLon = parseFloat(lon), r = parseInt(radius, 10);
    if (!name.trim() || !Number.isFinite(cLat) || !Number.isFinite(cLon)
        || !Number.isFinite(r) || r < 5) {
      toast.error("All fields required"); return;
    }
    setBusy(true);
    try {
      await api.post("/geofences", {
        name: name.trim(), kind: "custom", shape: "circle",
        center_lat: cLat, center_lon: cLon, radius_m: r,
        alert_on_enter: true, alert_on_exit: false, active: true,
      });
      toast.success("Geofence created");
      setName(""); setLat(""); setLon(""); setRadius("100");
      onCreated();
    } catch (e) { toast.error("Failed", { description: e?.message }); }
    finally { setBusy(false); }
  };
  return (
    <div className="bg-white border border-zinc-200 rounded-lg p-4 shadow-sm"
         data-testid="geofences-manual-panel">
      <div className="text-sm font-medium text-zinc-800 mb-3">
        Quick create (circle)
      </div>
      <div className="grid grid-cols-2 gap-2 text-sm">
        <input placeholder="Name" value={name}
          onChange={(e) => setName(e.target.value)}
          className="col-span-2 px-3 py-2 border border-zinc-200 rounded"
          data-testid="geofences-manual-name" />
        <input placeholder="Center lat" value={lat}
          onChange={(e) => setLat(e.target.value)}
          className="px-3 py-2 border border-zinc-200 rounded"
          data-testid="geofences-manual-lat" />
        <input placeholder="Center lon" value={lon}
          onChange={(e) => setLon(e.target.value)}
          className="px-3 py-2 border border-zinc-200 rounded"
          data-testid="geofences-manual-lon" />
        <input placeholder="Radius m" value={radius}
          onChange={(e) => setRadius(e.target.value)}
          className="px-3 py-2 border border-zinc-200 rounded"
          data-testid="geofences-manual-radius" />
      </div>
      <button type="button" onClick={submit} disabled={busy}
        className="mt-3 inline-flex items-center gap-1 px-3 py-1.5 rounded bg-sky-600 text-white text-sm disabled:opacity-50"
        data-testid="geofences-manual-save">
        <Save size={14} /> {busy ? "Saving…" : "Create"}
      </button>
    </div>
  );
}

// ── Detail drawer ───────────────────────────────────────────────────
function DetailDrawer({ fenceId, onClose, onDeleted }) {
  const [row, setRow] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  React.useEffect(() => {
    if (!fenceId) return;
    setLoading(true);
    api.get(`/geofences/${fenceId}`)
      .then((r) => setRow(r))
      .catch((e) => toast.error("Load failed", { description: e?.message }))
      .finally(() => setLoading(false));
  }, [fenceId]);
  const archive = async () => {
    if (!row) return;
    try {
      await api.del(`/geofences/${row.id}`);
      toast.success("Archived");
      onDeleted();
    } catch (e) { toast.error("Failed", { description: e?.message }); }
  };
  if (!fenceId) return null;
  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-end sm:items-center justify-center p-4"
         data-testid="geofences-detail-drawer" onClick={onClose}>
      <div className="bg-white rounded-lg shadow-xl max-w-lg w-full p-6"
           onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-lg font-semibold"
              data-testid="geofences-detail-name">
            {row?.name || "Geofence"}
          </h3>
          <button type="button" onClick={onClose} aria-label="Close"
                  data-testid="geofences-detail-close"><X size={18} /></button>
        </div>
        {loading || !row ? (
          <div className="text-sm text-zinc-500">Loading…</div>
        ) : (
          <div className="space-y-3">
            <div className="text-sm text-zinc-700">
              <div><strong>Kind:</strong> {row.kind}</div>
              <div><strong>Shape:</strong> {row.shape}</div>
              <div><strong>Enter alert:</strong> {String(!!row.alert_on_enter)}</div>
              <div><strong>Exit alert:</strong> {String(!!row.alert_on_exit)}</div>
              <div><strong>Active:</strong> {String(!!row.active)}</div>
            </div>
            <div>
              <div className="text-sm font-medium text-zinc-800 mb-1">
                Recent events
              </div>
              {(row.recent_events || []).length === 0 ? (
                <div className="text-xs text-zinc-500"
                     data-testid="geofences-detail-noevents">No events yet.</div>
              ) : (
                <ul className="space-y-1 text-xs" data-testid="geofences-detail-events">
                  {row.recent_events.slice(0, 10).map((e) => (
                    <li key={e.id} className="flex items-center gap-2">
                      <span className={`inline-block rounded-full px-1.5 py-0.5 ${
                        e.crossing === "enter"
                          ? "bg-emerald-100 text-emerald-800"
                          : "bg-amber-100 text-amber-800"}`}>
                        {e.crossing}
                      </span>
                      <span className="text-zinc-500">{_fmt(e.detected_at)}</span>
                      <span>{e.user_name || e.user_id}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div className="flex justify-between pt-2">
              <button type="button" onClick={archive}
                className="inline-flex items-center gap-1 text-red-600 hover:underline text-sm"
                data-testid="geofences-detail-archive">
                <Trash2 size={14} /> Archive
              </button>
              <button type="button" onClick={onClose}
                className="px-3 py-1.5 border border-zinc-200 rounded text-sm">
                Close
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Main page ───────────────────────────────────────────────────────
export default function GeofencesPage() {
  const [fences, setFences] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [forbidden, setForbidden] = React.useState(false);
  const [mode, setMode] = React.useState(null); // "circle" | "polygon" | null
  const [pending, setPending] = React.useState(null);
  const [activeId, setActiveId] = React.useState(null);
  const [detailId, setDetailId] = React.useState(null);
  // Ref that the DrawTools child assigns a "finish polygon" callback to,
  // so the toolbar Finish button can trigger it from outside the map.
  const finishRef = React.useRef(null);
  const mapsKey = process.env.REACT_APP_GOOGLE_MAPS_API_KEY
    || process.env.REACT_APP_GOOGLE_API_KEY || "";
  const hasMaps = Boolean(mapsKey);

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.get("/geofences");
      setFences(r?.items || []);
      setForbidden(false);
    } catch (e) {
      if ((e?.message || "").includes("403")) setForbidden(true);
      else toast.error("Load failed", { description: e?.message });
    } finally { setLoading(false); }
  }, []);
  React.useEffect(() => { load(); }, [load]);

  const initialCenter = React.useMemo(() => {
    const circle = fences.find((f) => f.shape === "circle" && f.active);
    if (circle) return { lat: circle.center_lat, lng: circle.center_lon };
    const poly = fences.find((f) => f.shape === "polygon" && (f.points || [])[0]);
    if (poly) return { lat: poly.points[0].lat, lng: poly.points[0].lon };
    return AZ_CENTER;
  }, [fences]);

  if (forbidden) {
    return (
      <div className="p-6" data-testid="geofences-forbidden">
        <h1 className="text-2xl font-semibold text-zinc-900">Access denied</h1>
        <p className="text-sm text-zinc-500 mt-2">
          You don't have permission to manage geofences.
        </p>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-4" data-testid="geofences-page">
      <header className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-zinc-900"
              data-testid="geofences-title">Geofences</h1>
          <p className="text-sm text-zinc-500 mt-1">
            Draw circles or polygons on the map to define entry/exit
            zones. Techs' pings are evaluated in real time.
          </p>
        </div>
        <button type="button" onClick={load}
          className="inline-flex items-center gap-1 px-3 py-1.5 border border-zinc-200 rounded text-sm hover:bg-zinc-50"
          data-testid="geofences-refresh">
          <RefreshCw size={14} /> Refresh
        </button>
      </header>

      {hasMaps ? (
        <>
          <div className="flex flex-wrap gap-2 text-sm"
               data-testid="geofences-draw-toolbar">
            <button type="button" onClick={() => setMode("circle")}
              className={`inline-flex items-center gap-1 px-3 py-1.5 rounded border ${
                mode === "circle" ? "bg-sky-600 text-white border-sky-600"
                                  : "bg-white border-zinc-200 hover:bg-zinc-50"}`}
              data-testid="geofences-draw-circle-btn">
              <MapPin size={14} /> Draw circle
            </button>
            <button type="button" onClick={() => setMode("polygon")}
              className={`inline-flex items-center gap-1 px-3 py-1.5 rounded border ${
                mode === "polygon" ? "bg-sky-600 text-white border-sky-600"
                                   : "bg-white border-zinc-200 hover:bg-zinc-50"}`}
              data-testid="geofences-draw-polygon-btn">
              <PenTool size={14} /> Draw polygon
            </button>
            {mode && (
              <button type="button" onClick={() => setMode(null)}
                className="inline-flex items-center gap-1 px-3 py-1.5 border border-zinc-200 rounded"
                data-testid="geofences-draw-cancel-btn">
                Cancel
              </button>
            )}
            {mode === "polygon" && (
              <button type="button"
                onClick={() => {
                  const done = finishRef.current && finishRef.current();
                  if (!done) toast.error("Add at least 3 points first");
                  else setMode(null);
                }}
                className="inline-flex items-center gap-1 px-3 py-1.5 border border-emerald-500 text-emerald-700 bg-emerald-50 rounded"
                data-testid="geofences-draw-finish-btn">
                Finish polygon
              </button>
            )}
            <span className="text-xs text-zinc-500 self-center ml-2"
                  data-testid="geofences-draw-hint">
              {mode === "circle"
                ? "Click to place the center, then click again to set radius."
                : mode === "polygon"
                  ? "Click to add points, then hit Finish (need ≥3)."
                  : "Pick a tool to start drawing."}
            </span>
          </div>
          <div className="rounded-xl overflow-hidden"
               style={{ border: `1px solid ${colors?.border || "#e4e4e7"}`,
                        height: "min(60vh, 620px)", minHeight: 380 }}
               data-testid="geofences-map-container">
            <Map
              mapId="DEMO_MAP_ID"
              defaultCenter={initialCenter}
              defaultZoom={11}
              gestureHandling="cooperative"
              clickableIcons={false}
              style={{ width: "100%", height: "100%" }}>
              <DrawTools mode={mode} onDrawn={(s) => { setPending(s); setMode(null); }}
                         onFinishRequested={finishRef} />
              <ExistingFencesLayer fences={fences} activeId={activeId}
                                    onPick={setActiveId} />
            </Map>
          </div>
        </>
      ) : (
        <ManualCreatePanel onCreated={load} />
      )}

      <div className="bg-white border border-zinc-200 rounded-lg shadow-sm overflow-hidden"
           data-testid="geofences-list">
        {loading ? (
          <div className="p-6 text-sm text-zinc-500">Loading…</div>
        ) : fences.length === 0 ? (
          <div className="p-6 text-sm text-zinc-500"
               data-testid="geofences-empty">
            No geofences yet. Use the draw tools above to create one.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-zinc-50 text-zinc-500 text-xs">
              <tr>
                <th className="text-left px-4 py-2">Name</th>
                <th className="text-left px-4 py-2">Kind</th>
                <th className="text-left px-4 py-2">Shape</th>
                <th className="text-left px-4 py-2">Alerts</th>
                <th className="text-left px-4 py-2">Active</th>
                <th className="text-right px-4 py-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {fences.map((f) => (
                <tr key={f.id}
                    className={`border-t border-zinc-100 ${
                      activeId === f.id ? "bg-sky-50" : ""}`}
                    data-testid={`geofences-row-${f.id}`}>
                  <td className="px-4 py-2 font-medium">
                    <button type="button" onClick={() => setActiveId(f.id)}
                      className="text-left hover:underline"
                      data-testid={`geofences-select-${f.id}`}>
                      {f.name}
                    </button>
                  </td>
                  <td className="px-4 py-2">{f.kind}</td>
                  <td className="px-4 py-2">
                    {f.shape}
                    {f.shape === "circle"
                      ? ` (${f.radius_m}m)`
                      : ` (${(f.points || []).length} pts)`}
                  </td>
                  <td className="px-4 py-2 text-xs">
                    {f.alert_on_enter ? "enter" : ""}
                    {f.alert_on_enter && f.alert_on_exit ? " + " : ""}
                    {f.alert_on_exit ? "exit" : ""}
                    {!f.alert_on_enter && !f.alert_on_exit ? "—" : ""}
                  </td>
                  <td className="px-4 py-2">
                    {f.active ? (
                      <span className="inline-block rounded-full px-2 py-0.5 text-xs"
                        style={{ background: "#DCFCE7", color: "#065F46" }}>
                        Active</span>
                    ) : (
                      <span className="inline-block rounded-full px-2 py-0.5 text-xs"
                        style={{ background: "#E5E7EB", color: "#374151" }}>
                        Archived</span>
                    )}
                  </td>
                  <td className="px-4 py-2 text-right">
                    <button type="button" onClick={() => setDetailId(f.id)}
                      className="text-sky-600 hover:underline text-xs"
                      data-testid={`geofences-open-${f.id}`}>
                      Details
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {pending && hasMaps && (
        <FenceForm pending={pending}
          onSubmit={() => { setPending(null); load(); }}
          onCancel={() => setPending(null)} />
      )}
      {detailId && (
        <DetailDrawer fenceId={detailId}
          onClose={() => setDetailId(null)}
          onDeleted={() => { setDetailId(null); load(); }} />
      )}
    </div>
  );
}
