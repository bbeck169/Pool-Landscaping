import React, { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Ruler } from "lucide-react";
import { api, TOKEN_KEY } from "@/api";
import { colors } from "@/theme";
import { useIsNarrow } from "@/hooks/useIsNarrow";

/* ═══════════════════════════════════════════════════════════════════
   CAD Studio — Editor surface.

   Phase CAD-1 · Feb-2026 — foundation for the property-drawing
   workspace:

     * Server-proxied Google Static Maps satellite backdrop
       (``GET /api/cad/map-tile``). No API key ships to the browser.
     * Scale-to-real-world calibration tool. Two clicks + a known
       distance in feet drive ``feet_per_pixel``, which persists on
       the design + drives the on-canvas scale bar.
     * Sidebar surface listing lat/lng, zoom (with +/-), the
       feet-per-pixel value, cache/live status pill, and a refresh
       button.

   The pre-Phase-CAD-1 tool set (pointer / rect / circle / palm /
   cactus / spa / firepit / text) is preserved verbatim — the map
   backdrop layers underneath existing tool strokes.
   ═══════════════════════════════════════════════════════════════════ */


function Toast({ text }) {
  if (!text) return null;
  return (
    <div className="fixed bottom-6 right-6 z-50 px-4 py-2 rounded-xl text-sm text-white shadow-lg"
         style={{ backgroundColor: colors.onSurface }} data-testid="ai-tool-toast">
      {text}
    </div>
  );
}


const CAD_TOOLS = [
  { k: "pointer", label: "Select" },
  { k: "rect",    label: "Rectangle" },
  { k: "circle",  label: "Circle" },
  { k: "tree",    label: "Palm" },
  { k: "cactus",  label: "Cactus" },
  { k: "spa",     label: "Spa" },
  { k: "firepit", label: "Fire pit" },
  { k: "text",    label: "Text" },
  { k: "scale",   label: "Scale Calibrate", icon: Ruler },
];


// Zoom clamps mirror ``routers/cad.py::_ZOOM_MIN/_MAX``. Kept in
// sync locally so the sidebar +/- buttons never send an out-of-range
// zoom to the server (the server also clamps as a belt-and-braces).
const ZOOM_MIN = 15;
const ZOOM_MAX = 21;


function _readMapHeaders(res) {
  const src = res.headers.get("X-Geocode-Source") || "live";
  const lat = parseFloat(res.headers.get("X-Map-Lat") || "0");
  const lng = parseFloat(res.headers.get("X-Map-Lng") || "0");
  const zoom = parseInt(res.headers.get("X-Map-Zoom") || "19", 10);
  const fpp = parseFloat(res.headers.get("X-Feet-Per-Pixel") || "0");
  return { lat, lng, zoom, feetPerPixel: fpp, source: src };
}


async function fetchMapTile({ customerId, zoom, size }) {
  const BASE = process.env.REACT_APP_BACKEND_URL;
  const token = (() => {
    try { return localStorage.getItem(TOKEN_KEY) || ""; }
    catch { return ""; }
  })();
  const qs = new URLSearchParams({
    customer_id: customerId,
    zoom: String(zoom),
    size,
  });
  const url = `${BASE}/api/cad/map-tile?${qs.toString()}`;
  const res = await fetch(url, {
    method: "GET",
    headers: token ? { "Authorization": `Bearer ${token}` } : {},
  });
  if (!res.ok) {
    let detail = null;
    try { detail = (await res.json())?.detail || null; }
    catch { /* body wasn't JSON — return status only */ }
    const err = new Error(`map-tile HTTP ${res.status}`);
    err.status = res.status;
    err.errorCode = (detail && detail.error_code) || `http_${res.status}`;
    throw err;
  }
  const blob = await res.blob();
  return { blob, meta: _readMapHeaders(res) };
}


function _dist(a, b) {
  const dx = a.xPx - b.xPx;
  const dy = a.yPx - b.yPx;
  return Math.sqrt(dx * dx + dy * dy);
}


export default function CadEditor() {
  const { id } = useParams();
  const [design, setDesign] = useState(null);
  const [tool, setTool] = useState("pointer");
  const [_dragging, _setDragging] = useState(null);
  const [toast, setToast] = useState("");
  const canvasRef = useRef(null);
  // Phase CAD-1 — map backdrop state.
  const [mapMeta, setMapMeta] = useState(null);
  const [mapImgUrl, setMapImgUrl] = useState(null);
  const [mapLoading, setMapLoading] = useState(false);
  const [mapError, setMapError] = useState(null);
  // Phase CAD-1 — scale calibration state.
  const [scalePoints, setScalePoints] = useState([]);
  // Sidebar-controlled zoom (falls back to design.map_zoom, then 19).
  const [zoomOverride, setZoomOverride] = useState(null);
  const isNarrow = useIsNarrow(768);

  useEffect(() => {
    if (!id) return;
    api.get(`/designs/${id}`).then(setDesign).catch(() => setToast("Failed to load"));
  }, [id]);

  const canvasSize = { w: 800, h: 500 };

  // Effective zoom used for map fetches. Priority: user-driven
  // override → persisted ``design.map_zoom`` → default 19.
  const effectiveZoom = zoomOverride
    ?? (design?.map_zoom ?? 19);

  // ── Map tile fetch ────────────────────────────────────────────
  const loadMap = useCallback(async (customerId, zoom) => {
    if (!customerId) return;
    setMapLoading(true);
    setMapError(null);
    try {
      const { blob, meta } = await fetchMapTile({
        customerId,
        zoom,
        size: `${canvasSize.w}x${canvasSize.h}`,
      });
      const url = URL.createObjectURL(blob);
      setMapImgUrl((prev) => {
        if (prev) {
          try { URL.revokeObjectURL(prev); } catch { /* noop */ }
        }
        return url;
      });
      setMapMeta(meta);
      // Persist metadata to the design so a returning session
      // reuses the same coordinates + calibration without another
      // round-trip. Best-effort; failure is silent (map still
      // renders locally).
      try {
        await api.put(`/designs/${id}`, {
          name: design?.name || "Untitled design",
          canvas_w_ft: design?.canvas_w_ft ?? 60,
          canvas_h_ft: design?.canvas_h_ft ?? 40,
          boundary: design?.boundary || [],
          elements: design?.elements || [],
          area_sqft: design?.area_sqft || 0,
          perimeter_ft: design?.perimeter_ft || 0,
          customer_id: design?.customer_id,
          lead_id: design?.lead_id,
          map_center_lat: meta.lat,
          map_center_lng: meta.lng,
          map_zoom: meta.zoom,
          feet_per_pixel: (design?.feet_per_pixel ?? meta.feetPerPixel),
          map_size_px: { w: canvasSize.w, h: canvasSize.h },
        });
      } catch { /* non-fatal — the map is already in state */ }
    } catch (e) {
      setMapError({
        code: e.errorCode || `http_${e.status || "unknown"}`,
      });
    } finally {
      setMapLoading(false);
    }
  }, [id, design, canvasSize.w, canvasSize.h]);

  // Auto-fetch when the loaded design surfaces its customer_id (or
  // the user bumps the sidebar zoom).
  useEffect(() => {
    if (!design || !design.customer_id) return;
    loadMap(design.customer_id, effectiveZoom);
    // Deliberately excluded ``loadMap`` from deps — it closes over
    // ``design``, which changes every keystroke on the name input.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [design?.customer_id, effectiveZoom]);

  const onCanvasMouseDown = (e) => {
    if (!design) return;
    if (tool === "pointer") return;
    const rect = canvasRef.current.getBoundingClientRect();
    const x = (e.clientX - rect.left) / rect.width;
    const y = (e.clientY - rect.top) / rect.height;
    // Phase CAD-1 — scale-calibration tool takes two clicks and
    // then prompts for a known distance in feet.
    if (tool === "scale") {
      const p = { x, y, xPx: x * rect.width, yPx: y * rect.height };
      const next = [...scalePoints, p];
      if (next.length < 2) {
        setScalePoints(next);
        return;
      }
      // Second click — prompt for the known distance.
      const known = window.prompt(
        "Known distance between the two points (feet)?",
        "10",
      );
      const feet = parseFloat(known);
      if (!isFinite(feet) || feet <= 0) {
        setScalePoints([]);
        setTool("pointer");
        return;
      }
      const pixels = _dist(p, next[0]);
      if (pixels <= 0) {
        setScalePoints([]);
        setTool("pointer");
        return;
      }
      const fpp = feet / pixels;
      setMapMeta((m) => (m ? { ...m, feetPerPixel: fpp } : m));
      setDesign((d) => (d ? { ...d, feet_per_pixel: fpp } : d));
      // Persist.
      api.put(`/designs/${id}`, {
        name: design.name,
        canvas_w_ft: design.canvas_w_ft,
        canvas_h_ft: design.canvas_h_ft,
        boundary: design.boundary || [],
        elements: design.elements || [],
        area_sqft: design.area_sqft || 0,
        perimeter_ft: design.perimeter_ft || 0,
        customer_id: design.customer_id,
        lead_id: design.lead_id,
        map_center_lat: design.map_center_lat ?? mapMeta?.lat ?? null,
        map_center_lng: design.map_center_lng ?? mapMeta?.lng ?? null,
        map_zoom: design.map_zoom ?? mapMeta?.zoom ?? null,
        feet_per_pixel: fpp,
        map_size_px: design.map_size_px
          ?? { w: canvasSize.w, h: canvasSize.h },
      }).catch(() => setToast("Scale save failed"));
      setToast(`Calibrated · ${fpp.toFixed(4)} ft/px`);
      setScalePoints([]);
      setTool("pointer");
      return;
    }
    const elem = {
      id: crypto.randomUUID(), type: tool,
      x, y,
      w: tool === "rect" ? 0.1 : 0.05,
      h: tool === "rect" ? 0.06 : 0.05,
      label: tool === "text" ? "Label" : "",
    };
    setDesign({ ...design, elements: [...(design.elements || []), elem] });
    setTool("pointer");
  };

  const removeElem = (eid) => {
    setDesign({ ...design, elements: (design.elements || []).filter((e) => e.id !== eid) });
  };

  const save = async () => {
    if (!design) return;
    try {
      await api.put(`/designs/${id}`, {
        name: design.name,
        canvas_w_ft: design.canvas_w_ft,
        canvas_h_ft: design.canvas_h_ft,
        boundary: design.boundary || [],
        elements: design.elements || [],
        area_sqft: design.area_sqft || 0,
        perimeter_ft: design.perimeter_ft || 0,
        customer_id: design.customer_id,
        lead_id: design.lead_id,
        map_center_lat: design.map_center_lat ?? mapMeta?.lat ?? null,
        map_center_lng: design.map_center_lng ?? mapMeta?.lng ?? null,
        map_zoom: design.map_zoom ?? mapMeta?.zoom ?? null,
        feet_per_pixel: design.feet_per_pixel ?? mapMeta?.feetPerPixel ?? null,
        map_size_px: design.map_size_px
          ?? { w: canvasSize.w, h: canvasSize.h },
      });
      setToast("Saved");
    } catch (e) { setToast(e.message); }
  };

  if (!design) return <div className="p-8 text-sm" style={{ color: colors.onSurfaceSecondary }}>Loading design…</div>;

  // Mobile guard — the drawing surface is desktop/tablet only.
  if (isNarrow) {
    return (
      <div className="p-8 max-w-md mx-auto text-center" data-testid="cad-mobile-guard">
        <div className="text-4xl mb-3">🖥️</div>
        <div className="font-bold text-lg">CAD editor needs a larger screen</div>
        <div className="text-sm mt-2" style={{ color: colors.onSurfaceSecondary }}>
          Please use a tablet or desktop to open <strong>{design.name}</strong>.
        </div>
        <Link to="/cad" className="inline-block mt-4 px-4 py-2 rounded-xl text-sm font-semibold text-white" style={{ backgroundColor: colors.brand }}>← Back to designs</Link>
      </div>
    );
  }

  const feetPerPixel = design.feet_per_pixel
    ?? mapMeta?.feetPerPixel
    ?? null;
  const statusPill = mapLoading
    ? { text: "Loading", bg: colors.surfaceSecondary }
    : mapError
      ? { text: `Error · ${mapError.code}`, bg: "#FEE2E2" }
      : mapMeta?.source === "cache"
        ? { text: "Cached", bg: "#DCFCE7" }
        : mapMeta?.source === "live"
          ? { text: "Live", bg: "#DBEAFE" }
          : { text: "—", bg: colors.surfaceSecondary };

  return (
    <div className="p-4 md:p-6 max-w-7xl mx-auto space-y-4" data-testid="cad-editor-page">
      <div className="flex items-center gap-3">
        <Link to="/cad" className="text-sm font-semibold" style={{ color: colors.brand }}>← Designs</Link>
        <input value={design.name} onChange={(e) => setDesign({ ...design, name: e.target.value })}
               className="text-xl font-bold flex-1 px-2 py-1 rounded"
               style={{ border: `1px solid ${colors.border}` }} data-testid="cad-name" />
        <button onClick={save} className="px-4 py-2 rounded-lg text-sm font-semibold text-white" style={{ backgroundColor: colors.brand }} data-testid="cad-save">Save</button>
      </div>

      <div className="flex flex-wrap gap-2">
        {CAD_TOOLS.map((t) => {
          const Icon = t.icon;
          return (
            <button key={t.k} onClick={() => { setTool(t.k); if (t.k !== "scale") setScalePoints([]); }}
                    className="px-3 py-1.5 rounded-lg text-xs font-semibold inline-flex items-center gap-1"
                    style={{
                      backgroundColor: tool === t.k ? colors.brandTertiary : colors.surfaceSecondary,
                      color: tool === t.k ? colors.onBrandTertiary : colors.onSurfaceSecondary,
                    }}
                    data-testid={`cad-tool-${t.k}`}>
              {Icon ? <Icon size={12} /> : null}
              {t.label}
            </button>
          );
        })}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
        {/* Drawing surface — left 3/4 */}
        <div className="lg:col-span-3">
          <div
            ref={canvasRef}
            onMouseDown={onCanvasMouseDown}
            className="relative rounded-2xl overflow-hidden"
            style={{
              width: "100%", aspectRatio: `${canvasSize.w}/${canvasSize.h}`,
              backgroundColor: "#F0F9FF",
              backgroundImage: mapImgUrl
                ? "none"
                : "linear-gradient(#E0F2FE 1px, transparent 1px), linear-gradient(90deg, #E0F2FE 1px, transparent 1px)",
              backgroundSize: `${100/12}% ${100/8}%`,
              border: `1px solid ${colors.border}`,
              cursor: tool === "pointer" ? "default" : "crosshair",
            }}
            data-testid="cad-canvas"
          >
            {mapImgUrl && (
              <img
                src={mapImgUrl}
                alt="satellite backdrop"
                data-testid="cad-map-backdrop-img"
                className="absolute inset-0 w-full h-full object-cover pointer-events-none"
                style={{ zIndex: 0 }}
              />
            )}
            {/* Scale-tool markers */}
            {scalePoints.map((p, idx) => (
              <div
                key={idx}
                className="absolute w-2 h-2 rounded-full -ml-1 -mt-1 pointer-events-none"
                style={{
                  left: `${p.x * 100}%`, top: `${p.y * 100}%`,
                  backgroundColor: "#DC2626", zIndex: 5,
                }}
                data-testid={`cad-scale-marker-${idx}`}
              />
            ))}
            {(design.elements || []).map((el) => (
              <div
                key={el.id}
                onClick={(e) => { e.stopPropagation(); if (tool === "pointer") removeElem(el.id); }}
                className="absolute flex items-center justify-center"
                style={{
                  left: `${el.x * 100}%`, top: `${el.y * 100}%`,
                  width: `${(el.w || 0.05) * 100}%`,
                  height: `${(el.h || 0.05) * 100}%`,
                  backgroundColor: el.type === "rect" ? "#0284C7" : el.type === "spa" ? "#7C3AED" : el.type === "firepit" ? "#DC2626" : "transparent",
                  borderRadius: el.type === "circle" || el.type === "spa" ? "50%" : 6,
                  fontSize: 22, color: "#fff",
                  opacity: 0.85,
                  cursor: tool === "pointer" ? "pointer" : "crosshair",
                  zIndex: 2,
                }}
                data-testid={`cad-elem-${el.id}`}
              >
                {el.type === "tree" && "🌴"}
                {el.type === "cactus" && "🌵"}
                {el.type === "text" && <span style={{ color: "#111", fontSize: 12 }}>{el.label || "Label"}</span>}
              </div>
            ))}
            {/* Scale bar overlay — bottom-right of the canvas. */}
            {feetPerPixel && feetPerPixel > 0 && (
              <div
                className="absolute bottom-2 right-2 flex items-center gap-1"
                style={{ zIndex: 4 }}
                data-testid="cad-scale-bar-overlay"
              >
                <div
                  className="h-1"
                  style={{
                    width: `${Math.min(200, 50 / feetPerPixel)}px`,
                    backgroundColor: "#111",
                  }}
                />
                <span
                  className="text-xs font-semibold px-1 rounded"
                  style={{ backgroundColor: "#fff", color: "#111" }}
                >
                  50 ft
                </span>
              </div>
            )}
          </div>
          <div className="text-xs mt-2" style={{ color: colors.onSurfaceSecondary }}>
            Canvas: {design.canvas_w_ft || 60} ft × {design.canvas_h_ft || 40} ft · {design.elements?.length || 0} elements · Click pointer + element to delete.
          </div>
        </div>

        {/* Sidebar — right 1/4 */}
        <aside className="lg:col-span-1 space-y-3" data-testid="cad-sidebar">
          <section
            className="rounded-2xl p-3 space-y-2"
            style={{ border: `1px solid ${colors.border}` }}
            data-testid="cad-map-backdrop-section"
          >
            <div className="flex items-center justify-between">
              <div className="text-xs font-semibold uppercase tracking-wider"
                   style={{ color: colors.onSurfaceSecondary }}>
                Map Backdrop
              </div>
              <span
                className="text-xs font-semibold px-2 py-0.5 rounded-full"
                style={{ backgroundColor: statusPill.bg, color: "#111" }}
                data-testid="cad-map-status-pill"
              >
                {statusPill.text}
              </span>
            </div>

            {mapError && (
              <div
                className="text-xs rounded p-2"
                style={{ backgroundColor: "#FEE2E2", color: "#991B1B" }}
                data-testid="cad-map-error-banner"
              >
                Map unavailable — <strong>{mapError.code}</strong>.
                You can still draw on a blank canvas.
              </div>
            )}

            <div className="text-xs space-y-1">
              <div className="flex justify-between">
                <span style={{ color: colors.onSurfaceSecondary }}>Lat</span>
                <span data-testid="cad-map-lat-value">{mapMeta?.lat?.toFixed?.(5) ?? "—"}</span>
              </div>
              <div className="flex justify-between">
                <span style={{ color: colors.onSurfaceSecondary }}>Lng</span>
                <span data-testid="cad-map-lng-value">{mapMeta?.lng?.toFixed?.(5) ?? "—"}</span>
              </div>
              <div className="flex justify-between items-center">
                <span style={{ color: colors.onSurfaceSecondary }}>Zoom</span>
                <div className="inline-flex items-center gap-1">
                  <button
                    onClick={() => setZoomOverride((z) => Math.max(ZOOM_MIN, ((z ?? effectiveZoom) - 1)))}
                    className="w-6 h-6 rounded text-xs font-bold"
                    style={{ backgroundColor: colors.surfaceSecondary }}
                    data-testid="cad-map-zoom-minus"
                  >−</button>
                  <span className="w-6 text-center" data-testid="cad-map-zoom-value">
                    {effectiveZoom}
                  </span>
                  <button
                    onClick={() => setZoomOverride((z) => Math.min(ZOOM_MAX, ((z ?? effectiveZoom) + 1)))}
                    className="w-6 h-6 rounded text-xs font-bold"
                    style={{ backgroundColor: colors.surfaceSecondary }}
                    data-testid="cad-map-zoom-plus"
                  >+</button>
                </div>
              </div>
              <div className="flex justify-between items-center pt-1">
                <span style={{ color: colors.onSurfaceSecondary }}>ft / px</span>
                <input
                  type="number"
                  step="0.0001"
                  value={feetPerPixel ?? ""}
                  onChange={(e) => {
                    const v = parseFloat(e.target.value);
                    if (!isFinite(v)) return;
                    setDesign((d) => (d ? { ...d, feet_per_pixel: v } : d));
                    setMapMeta((m) => (m ? { ...m, feetPerPixel: v } : m));
                  }}
                  className="w-24 text-xs text-right px-1 py-0.5 rounded"
                  style={{ border: `1px solid ${colors.border}` }}
                  data-testid="cad-feet-per-pixel-input"
                />
              </div>
              <button
                onClick={() => {
                  setDesign((d) => (d ? { ...d, feet_per_pixel: null } : d));
                  setMapMeta((m) => (m ? { ...m, feetPerPixel: m.feetPerPixel } : m));
                }}
                className="text-xs underline"
                style={{ color: colors.onSurfaceSecondary }}
                data-testid="cad-feet-per-pixel-reset"
              >
                Reset to server-computed
              </button>
            </div>

            <button
              onClick={() => design.customer_id && loadMap(design.customer_id, effectiveZoom)}
              className="w-full px-3 py-1.5 rounded-lg text-xs font-semibold text-white"
              style={{ backgroundColor: colors.brand }}
              disabled={!design.customer_id || mapLoading}
              data-testid="cad-map-refresh-btn"
            >
              {mapLoading ? "Loading…" : "Refresh map"}
            </button>
          </section>
        </aside>
      </div>

      <Toast text={toast} />
    </div>
  );
}
