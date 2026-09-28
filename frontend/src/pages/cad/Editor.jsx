import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Stage, Layer, Rect, Circle, Line, Text as KText, Group } from "react-konva";
import {
  Ruler, Trees, Sprout, TreePalm, Wheat, Flower,
  Lightbulb, LampDesk, Lamp,
} from "lucide-react";
import { api, TOKEN_KEY } from "@/api";
import { colors } from "@/theme";
import { useIsNarrow } from "@/hooks/useIsNarrow";
import {
  shoelaceSqft, polylineLengthFt, feetToImperial,
  snapPoint, collectSnapEdges, polygonCentroid,
} from "./shapeMath";


/* ═══════════════════════════════════════════════════════════════════
   CAD Studio — Editor surface.

   Phase CAD-1 · Feb-2026 — Google Static Maps backdrop + scale
   calibration.
   Phase CAD-2 · Feb-2026 — react-konva vector layer + pavers /
   walls / plant + lighting icons / tape measure / property-line
   snapping + auto area+dimension labels + MARCO AI shape
   generation sidebar.
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
  { k: "spa",     label: "Spa" },
  { k: "firepit", label: "Fire pit" },
  { k: "text",    label: "Text" },
  { k: "scale",   label: "Scale", icon: Ruler },
  { k: "paver",   label: "Pavers" },
  { k: "wall",    label: "Wall" },
  { k: "tape",    label: "Tape" },
];

const PLANT_ICONS = [
  { k: "tree",  label: "Tree",   Icon: Trees },
  { k: "shrub", label: "Shrub",  Icon: Sprout },
  { k: "bush",  label: "Bush",   Icon: Flower },
  { k: "palm",  label: "Palm",   Icon: TreePalm },
  { k: "grass", label: "Grass",  Icon: Wheat },
];
const LIGHT_ICONS = [
  { k: "path_light", label: "Path light", Icon: Lightbulb },
  { k: "spot_light", label: "Spot light", Icon: LampDesk },
  { k: "wall_light", label: "Wall light", Icon: Lamp },
];
const ALL_ICONS = [...PLANT_ICONS, ...LIGHT_ICONS];

// Legacy → new-icon-key map for the emoji ``tree``/``cactus`` type
// values older designs may carry.
const LEGACY_ICON_MAP = { tree: "tree", cactus: "shrub" };


const ZOOM_MIN = 15;
const ZOOM_MAX = 21;


function _uuid() {
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return `id-${Math.random().toString(36).slice(2, 10)}`;
}


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
    customer_id: customerId, zoom: String(zoom), size,
  });
  const url = `${BASE}/api/cad/map-tile?${qs.toString()}`;
  const res = await fetch(url, {
    method: "GET",
    headers: token ? { "Authorization": `Bearer ${token}` } : {},
  });
  if (!res.ok) {
    let detail = null;
    try { detail = (await res.json())?.detail || null; }
    catch { /* body wasn't JSON */ }
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


/** Serialize the design's persisted fields for PUT. Kept in one
 * place so every save path (auto-metadata, scale calibration,
 * shape mutation, MARCO accept, explicit Save) writes the same
 * envelope + never drops a field. */
function _designWriteBody(design, mapMeta, canvasSize) {
  return {
    name: design.name,
    canvas_w_ft: design.canvas_w_ft ?? 60,
    canvas_h_ft: design.canvas_h_ft ?? 40,
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
    map_size_px: design.map_size_px ?? { w: canvasSize.w, h: canvasSize.h },
    snap_threshold_px: design.snap_threshold_px ?? 8,
  };
}


export default function CadEditor() {
  const { id } = useParams();
  const [design, setDesign] = useState(null);
  const [tool, setTool] = useState("pointer");
  const [_dragging, _setDragging] = useState(null);
  const [toast, setToast] = useState("");
  const canvasRef = useRef(null);
  // ── Map backdrop state (CAD-1) ────────────────────────────────
  const [mapMeta, setMapMeta] = useState(null);
  const [mapImgUrl, setMapImgUrl] = useState(null);
  const [mapLoading, setMapLoading] = useState(false);
  const [mapError, setMapError] = useState(null);
  // ── Scale-calibration + tool in-flight state ──────────────────
  const [scalePoints, setScalePoints] = useState([]);
  const [paverInProgress, setPaverInProgress] = useState([]);
  const [wallInProgress, setWallInProgress] = useState([]);
  const [tapePoints, setTapePoints] = useState([]);
  const [persistNextMeasurement, setPersistNextMeasurement] = useState(false);
  // ── Icon library / MARCO state ────────────────────────────────
  const [placingIcon, setPlacingIcon] = useState(null);
  const [marcoPrompt, setMarcoPrompt] = useState("");
  const [marcoLoading, setMarcoLoading] = useState(false);
  const [marcoPreview, setMarcoPreview] = useState(null);
  // Sidebar-controlled zoom.
  const [zoomOverride, setZoomOverride] = useState(null);
  const isNarrow = useIsNarrow(768);

  useEffect(() => {
    if (!id) return;
    api.get(`/designs/${id}`).then(setDesign).catch(() => setToast("Failed to load"));
  }, [id]);

  const canvasSize = { w: 800, h: 500 };
  const effectiveZoom = zoomOverride ?? (design?.map_zoom ?? 19);
  const snapThresholdPx = design?.snap_threshold_px ?? 8;

  // ── Map tile fetch (CAD-1) ────────────────────────────────────
  const loadMap = useCallback(async (customerId, zoom) => {
    if (!customerId) return;
    setMapLoading(true);
    setMapError(null);
    try {
      const { blob, meta } = await fetchMapTile({
        customerId, zoom, size: `${canvasSize.w}x${canvasSize.h}`,
      });
      const url = URL.createObjectURL(blob);
      setMapImgUrl((prev) => {
        if (prev) { try { URL.revokeObjectURL(prev); } catch { /* noop */ } }
        return url;
      });
      setMapMeta(meta);
      try {
        await api.put(`/designs/${id}`, {
          ..._designWriteBody(design || {}, meta, canvasSize),
          map_center_lat: meta.lat,
          map_center_lng: meta.lng,
          map_zoom: meta.zoom,
          feet_per_pixel: (design?.feet_per_pixel ?? meta.feetPerPixel),
        });
      } catch { /* non-fatal */ }
    } catch (e) {
      setMapError({ code: e.errorCode || `http_${e.status || "unknown"}` });
    } finally {
      setMapLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, canvasSize.w, canvasSize.h]);

  useEffect(() => {
    if (!design || !design.customer_id) return;
    loadMap(design.customer_id, effectiveZoom);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [design?.customer_id, effectiveZoom]);

  // ── Snap machinery ────────────────────────────────────────────
  const snapEdges = useMemo(
    () => (design ? collectSnapEdges(design) : []),
    [design],
  );
  const maybeSnap = useCallback((normPt) => {
    if (!snapEdges.length) return { ...normPt, snapped: false };
    return snapPoint(normPt, snapEdges, snapThresholdPx, canvasSize);
  }, [snapEdges, snapThresholdPx, canvasSize.w, canvasSize.h]);

  // ── Stage click handler (Phase CAD-2-FIX · Feb-2026 —
  // real Konva swap: event handlers now live on the Konva
  // ``<Stage>`` itself, not on the outer positioning div. The
  // handler accepts both a Konva SyntheticEvent shape
  // (``e.evt.clientX``) AND a plain DOM MouseEvent shape so the
  // react-konva mock used in tests still delivers a working event
  // without pulling in the real Konva runtime).
  const onStageMouseDown = (e) => {
    if (!design) return;
    if (tool === "pointer" && !placingIcon) return;
    const native = (e && e.evt) ? e.evt : e;
    const rect = canvasRef.current.getBoundingClientRect();
    const rawX = (native.clientX - rect.left) / rect.width;
    const rawY = (native.clientY - rect.top) / rect.height;
    const snapped = maybeSnap({ x: rawX, y: rawY });
    const x = snapped.x;
    const y = snapped.y;
    const xPx = x * rect.width;
    const yPx = y * rect.height;

    // Icon library placement wins over any active tool.
    if (placingIcon) {
      const el = {
        id: _uuid(), type: "icon",
        coords: [{ x, y }],
        props: { icon: placingIcon, rotation_deg: 0 },
      };
      const next = { ...design, elements: [...(design.elements || []), el] };
      setDesign(next);
      setPlacingIcon(null);
      _persistDesign(next);
      return;
    }

    if (tool === "scale") {
      const p = { x, y, xPx, yPx };
      const next = [...scalePoints, p];
      if (next.length < 2) { setScalePoints(next); return; }
      const known = window.prompt(
        "Known distance between the two points (feet)?", "10",
      );
      const feet = parseFloat(known);
      const pixels = _dist(p, next[0]);
      if (!isFinite(feet) || feet <= 0 || pixels <= 0) {
        setScalePoints([]); setTool("pointer"); return;
      }
      const fpp = feet / pixels;
      const nextDesign = { ...design, feet_per_pixel: fpp };
      setMapMeta((m) => (m ? { ...m, feetPerPixel: fpp } : m));
      setDesign(nextDesign);
      _persistDesign(nextDesign).catch(() => setToast("Scale save failed"));
      setToast(`Calibrated · ${fpp.toFixed(4)} ft/px`);
      setScalePoints([]); setTool("pointer");
      return;
    }

    if (tool === "paver") {
      setPaverInProgress((v) => [...v, { x, y }]);
      return;
    }
    if (tool === "wall") {
      setWallInProgress((v) => [...v, { x, y }]);
      return;
    }
    if (tool === "tape") {
      const next = [...tapePoints, { x, y }];
      if (next.length < 2) { setTapePoints(next); return; }
      const persist = persistNextMeasurement;
      if (persist) {
        const el = {
          id: _uuid(), type: "dimension",
          coords: [...next],
          props: { persist_dimension: true },
        };
        const nd = { ...design, elements: [...(design.elements || []), el] };
        setDesign(nd);
        _persistDesign(nd);
      }
      // Non-persistent measurement remains in ``tapePoints`` until
      // the user picks another tool. Show it as an overlay.
      setTapePoints(next);
      setPersistNextMeasurement(false);
      setTool("pointer");
      return;
    }

    // Legacy element tools (rect / circle / spa / firepit / text)
    // preserved from CAD-1. They persist as ``{x, y, w, h}`` +
    // ``type``.
    if (["rect", "circle", "spa", "firepit", "text"].includes(tool)) {
      const elem = {
        id: _uuid(), type: tool,
        x, y,
        w: tool === "rect" ? 0.1 : 0.05,
        h: tool === "rect" ? 0.06 : 0.05,
        label: tool === "text" ? "Label" : "",
      };
      const next = { ...design, elements: [...(design.elements || []), elem] };
      setDesign(next);
      setTool("pointer");
      _persistDesign(next);
    }
  };

  const _persistDesign = useCallback((d) => {
    if (!d) return Promise.resolve();
    return api.put(`/designs/${id}`, _designWriteBody(d, mapMeta, canvasSize));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, mapMeta, canvasSize.w, canvasSize.h]);

  const finishPaver = () => {
    if (paverInProgress.length < 3) {
      setPaverInProgress([]); setTool("pointer"); return;
    }
    const el = {
      id: _uuid(), type: "paver",
      coords: [...paverInProgress],
      props: {},
      computed: {
        area_sqft: shoelaceSqft(
          paverInProgress, design.canvas_w_ft || 60,
          design.canvas_h_ft || 40,
        ),
      },
    };
    const next = { ...design, elements: [...(design.elements || []), el] };
    setDesign(next);
    setPaverInProgress([]);
    setTool("pointer");
    _persistDesign(next);
  };

  const finishWall = () => {
    if (wallInProgress.length < 2) {
      setWallInProgress([]); setTool("pointer"); return;
    }
    const el = {
      id: _uuid(), type: "wall",
      coords: [...wallInProgress],
      props: {},
      computed: {
        linear_ft: polylineLengthFt(
          wallInProgress, design.canvas_w_ft || 60,
          design.canvas_h_ft || 40,
        ),
      },
    };
    const next = { ...design, elements: [...(design.elements || []), el] };
    setDesign(next);
    setWallInProgress([]);
    setTool("pointer");
    _persistDesign(next);
  };

  const removeElem = (eid) => {
    const next = {
      ...design,
      elements: (design.elements || []).filter((e) => e.id !== eid),
    };
    setDesign(next);
    _persistDesign(next);
  };

  const save = async () => {
    if (!design) return;
    try {
      await _persistDesign(design);
      setToast("Saved");
    } catch (e) { setToast(e.message); }
  };

  // ── MARCO Designer actions ────────────────────────────────────
  const marcoGenerate = async () => {
    if (!marcoPrompt.trim()) return;
    setMarcoLoading(true);
    try {
      const body = await api.post("/cad/generate", {
        design_id: id,
        prompt: marcoPrompt.trim(),
      });
      setMarcoPreview(body);
    } catch (e) {
      setToast(e.message || "MARCO failed");
    } finally {
      setMarcoLoading(false);
    }
  };
  const marcoAccept = () => {
    if (!marcoPreview) return;
    // Convert each MARCO shape into a persisted element.
    const additions = (marcoPreview.shapes || []).map((s) => {
      const el = {
        id: _uuid(), type: s.type,
        coords: s.coords || [],
        props: {
          icon: s.icon || null, rotation_deg: 0,
          label_override: s.label || null,
        },
      };
      if (s.type === "pool" || s.type === "spa" || s.type === "paver") {
        el.computed = {
          area_sqft: shoelaceSqft(
            s.coords || [],
            design.canvas_w_ft || 60,
            design.canvas_h_ft || 40,
          ),
        };
      } else if (s.type === "wall") {
        el.computed = {
          linear_ft: polylineLengthFt(
            s.coords || [],
            design.canvas_w_ft || 60,
            design.canvas_h_ft || 40,
          ),
        };
      }
      return el;
    });
    const next = {
      ...design,
      elements: [...(design.elements || []), ...additions],
    };
    setDesign(next);
    setMarcoPreview(null);
    setMarcoPrompt("");
    _persistDesign(next);
  };
  const marcoDiscard = () => setMarcoPreview(null);

  if (!design) return <div className="p-8 text-sm" style={{ color: colors.onSurfaceSecondary }}>Loading design…</div>;

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

  const feetPerPixel = design.feet_per_pixel ?? mapMeta?.feetPerPixel ?? null;
  const statusPill = mapLoading
    ? { text: "Loading", bg: colors.surfaceSecondary }
    : mapError
      ? { text: `Error · ${mapError.code}`, bg: "#FEE2E2" }
      : mapMeta?.source === "cache"
        ? { text: "Cached", bg: "#DCFCE7" }
        : mapMeta?.source === "live"
          ? { text: "Live", bg: "#DBEAFE" }
          : { text: "—", bg: colors.surfaceSecondary };

  const cw = design.canvas_w_ft || 60;
  const ch = design.canvas_h_ft || 40;

  return (
    <div className="p-4 md:p-6 max-w-7xl mx-auto space-y-4" data-testid="cad-editor-page">
      <div className="flex items-center gap-3">
        <Link to="/cad" className="text-sm font-semibold" style={{ color: colors.brand }}>← Designs</Link>
        <input value={design.name} onChange={(e) => setDesign({ ...design, name: e.target.value })}
               className="text-xl font-bold flex-1 px-2 py-1 rounded"
               style={{ border: `1px solid ${colors.border}` }} data-testid="cad-name" />
        <button onClick={save} className="px-4 py-2 rounded-lg text-sm font-semibold text-white" style={{ backgroundColor: colors.brand }} data-testid="cad-save">Save</button>
      </div>

      <div className="flex flex-wrap gap-2 items-center">
        {CAD_TOOLS.map((t) => {
          const Icon = t.icon;
          const active = tool === t.k;
          return (
            <button key={t.k} onClick={() => {
              setTool(t.k);
              setPlacingIcon(null);
              if (t.k !== "scale") setScalePoints([]);
              if (t.k !== "paver") setPaverInProgress([]);
              if (t.k !== "wall") setWallInProgress([]);
              if (t.k !== "tape") setTapePoints([]);
            }}
                    className="px-3 py-1.5 rounded-lg text-xs font-semibold inline-flex items-center gap-1"
                    style={{
                      backgroundColor: active ? colors.brandTertiary : colors.surfaceSecondary,
                      color: active ? colors.onBrandTertiary : colors.onSurfaceSecondary,
                    }}
                    data-testid={`cad-tool-${t.k}`}>
              {Icon ? <Icon size={12} /> : null}
              {t.label}
            </button>
          );
        })}
        {tool === "paver" && (
          <button onClick={finishPaver}
                  className="px-3 py-1.5 rounded-lg text-xs font-semibold text-white"
                  style={{ backgroundColor: colors.brand }}
                  data-testid="cad-paver-finish">
            Close polygon ({paverInProgress.length} pts)
          </button>
        )}
        {tool === "wall" && (
          <button onClick={finishWall}
                  className="px-3 py-1.5 rounded-lg text-xs font-semibold text-white"
                  style={{ backgroundColor: colors.brand }}
                  data-testid="cad-wall-finish">
            Finish wall ({wallInProgress.length} pts)
          </button>
        )}
        {tool === "tape" && (
          <label className="text-xs inline-flex items-center gap-1"
                 style={{ color: colors.onSurfaceSecondary }}>
            <input type="checkbox"
                   checked={persistNextMeasurement}
                   onChange={(e) => setPersistNextMeasurement(e.target.checked)}
                   data-testid="cad-tape-persist-checkbox" />
            Persist measurement
          </label>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
        {/* Drawing surface */}
        <div className="lg:col-span-3">
          <div
            ref={canvasRef}
            className="relative rounded-2xl overflow-hidden"
            style={{
              width: "100%", aspectRatio: `${canvasSize.w}/${canvasSize.h}`,
              backgroundColor: "#F0F9FF",
              backgroundImage: mapImgUrl ? "none"
                : "linear-gradient(#E0F2FE 1px, transparent 1px), linear-gradient(90deg, #E0F2FE 1px, transparent 1px)",
              backgroundSize: `${100/12}% ${100/8}%`,
              border: `1px solid ${colors.border}`,
              cursor: tool === "pointer" && !placingIcon ? "default" : "crosshair",
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
            {/* Konva vector layer — PRIMARY interactive surface.
                All mouseDown handling lives here (Phase CAD-2-FIX).
                The outer div is now a positioning wrapper only. */}
            <Stage
              width={canvasSize.w}
              height={canvasSize.h}
              onMouseDown={onStageMouseDown}
              data-testid="cad-konva-stage"
              className="absolute inset-0"
              style={{ zIndex: 1, width: "100%", height: "100%" }}
            >
              <Layer data-testid="cad-konva-layer">
                {/* Persisted elements (legacy + CAD-2) */}
                {(design.elements || []).map((el) => (
                  <ShapeNode
                    key={el.id} el={el}
                    canvasSize={canvasSize} cw={cw} ch={ch}
                    onDelete={tool === "pointer" ? () => removeElem(el.id) : null}
                  />
                ))}
                {/* In-progress paver polygon */}
                {paverInProgress.length > 0 && (
                  <PaverPreview coords={paverInProgress} size={canvasSize} />
                )}
                {/* In-progress wall polyline */}
                {wallInProgress.length > 0 && (
                  <WallPreview coords={wallInProgress} size={canvasSize} />
                )}
                {/* Tape measure overlay (non-persistent) */}
                {tapePoints.length === 2 && !persistNextMeasurement && (
                  <TapeOverlay
                    coords={tapePoints} size={canvasSize}
                    cw={cw} ch={ch}
                  />
                )}
                {/* MARCO preview */}
                {marcoPreview && (marcoPreview.shapes || []).map((s, i) => (
                  <ShapeNode
                    key={`marco-${i}`} el={{
                      id: `marco-${i}`,
                      type: s.type,
                      coords: s.coords,
                      props: { icon: s.icon, label_override: s.label },
                    }}
                    canvasSize={canvasSize} cw={cw} ch={ch}
                    ghost
                    testidOverride={`cad-preview-shape-${i}`}
                  />
                ))}
              </Layer>
            </Stage>
            {/* CAD-1 scale-tool markers stay as HTML divs so the
                CAD-1 scale-tool test keeps working unchanged. */}
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
            {/* Scale bar overlay (CAD-1). */}
            {feetPerPixel && feetPerPixel > 0 && (
              <div
                className="absolute bottom-2 right-2 flex items-center gap-1"
                style={{ zIndex: 4 }}
                data-testid="cad-scale-bar-overlay"
              >
                <div className="h-1"
                     style={{
                       width: `${Math.min(200, 50 / feetPerPixel)}px`,
                       backgroundColor: "#111",
                     }} />
                <span className="text-xs font-semibold px-1 rounded"
                      style={{ backgroundColor: "#fff", color: "#111" }}>
                  50 ft
                </span>
              </div>
            )}
          </div>
          <div className="text-xs mt-2" style={{ color: colors.onSurfaceSecondary }}>
            Canvas: {cw} ft × {ch} ft · {(design.elements || []).length} elements
            {placingIcon && (
              <> · <strong>Click on canvas to place {placingIcon}</strong></>
            )}
          </div>
        </div>

        {/* Sidebar */}
        <aside className="lg:col-span-1 space-y-3" data-testid="cad-sidebar">
          {/* CAD-1 Map Backdrop section (unchanged) */}
          <section className="rounded-2xl p-3 space-y-2"
                   style={{ border: `1px solid ${colors.border}` }}
                   data-testid="cad-map-backdrop-section">
            <div className="flex items-center justify-between">
              <div className="text-xs font-semibold uppercase tracking-wider"
                   style={{ color: colors.onSurfaceSecondary }}>
                Map Backdrop
              </div>
              <span className="text-xs font-semibold px-2 py-0.5 rounded-full"
                    style={{ backgroundColor: statusPill.bg, color: "#111" }}
                    data-testid="cad-map-status-pill">
                {statusPill.text}
              </span>
            </div>
            {mapError && (
              <div className="text-xs rounded p-2"
                   style={{ backgroundColor: "#FEE2E2", color: "#991B1B" }}
                   data-testid="cad-map-error-banner">
                Map unavailable — <strong>{mapError.code}</strong>. You can still draw on a blank canvas.
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
                  <button onClick={() => setZoomOverride((z) => Math.max(ZOOM_MIN, ((z ?? effectiveZoom) - 1)))}
                          className="w-6 h-6 rounded text-xs font-bold"
                          style={{ backgroundColor: colors.surfaceSecondary }}
                          data-testid="cad-map-zoom-minus">−</button>
                  <span className="w-6 text-center" data-testid="cad-map-zoom-value">{effectiveZoom}</span>
                  <button onClick={() => setZoomOverride((z) => Math.min(ZOOM_MAX, ((z ?? effectiveZoom) + 1)))}
                          className="w-6 h-6 rounded text-xs font-bold"
                          style={{ backgroundColor: colors.surfaceSecondary }}
                          data-testid="cad-map-zoom-plus">+</button>
                </div>
              </div>
              <div className="flex justify-between items-center pt-1">
                <span style={{ color: colors.onSurfaceSecondary }}>ft / px</span>
                <input type="number" step="0.0001"
                       value={feetPerPixel ?? ""}
                       onChange={(e) => {
                         const v = parseFloat(e.target.value);
                         if (!isFinite(v)) return;
                         setDesign((d) => (d ? { ...d, feet_per_pixel: v } : d));
                         setMapMeta((m) => (m ? { ...m, feetPerPixel: v } : m));
                       }}
                       className="w-24 text-xs text-right px-1 py-0.5 rounded"
                       style={{ border: `1px solid ${colors.border}` }}
                       data-testid="cad-feet-per-pixel-input" />
              </div>
              <button onClick={() => {
                setDesign((d) => (d ? { ...d, feet_per_pixel: null } : d));
                setMapMeta((m) => (m ? { ...m, feetPerPixel: m.feetPerPixel } : m));
              }} className="text-xs underline"
                      style={{ color: colors.onSurfaceSecondary }}
                      data-testid="cad-feet-per-pixel-reset">
                Reset to server-computed
              </button>
            </div>
            <button onClick={() => design.customer_id && loadMap(design.customer_id, effectiveZoom)}
                    className="w-full px-3 py-1.5 rounded-lg text-xs font-semibold text-white"
                    style={{ backgroundColor: colors.brand }}
                    disabled={!design.customer_id || mapLoading}
                    data-testid="cad-map-refresh-btn">
              {mapLoading ? "Loading…" : "Refresh map"}
            </button>
          </section>

          {/* CAD-2 Icon library */}
          <section className="rounded-2xl p-3 space-y-2"
                   style={{ border: `1px solid ${colors.border}` }}
                   data-testid="cad-icon-library-section">
            <div className="text-xs font-semibold uppercase tracking-wider"
                 style={{ color: colors.onSurfaceSecondary }}>Icon Library</div>
            <div className="text-xs" style={{ color: colors.onSurfaceSecondary }}>Plants</div>
            <div className="grid grid-cols-5 gap-1">
              {PLANT_ICONS.map(({ k, label, Icon }) => (
                <button key={k}
                        onClick={() => {
                          setPlacingIcon(k);
                          setTool("pointer");
                        }}
                        title={label}
                        className="flex items-center justify-center h-7 rounded"
                        style={{
                          backgroundColor: placingIcon === k ? colors.brandTertiary : colors.surfaceSecondary,
                          color: placingIcon === k ? colors.onBrandTertiary : colors.onSurfaceSecondary,
                        }}
                        data-testid={`cad-icon-${k}`}>
                  <Icon size={14} />
                </button>
              ))}
            </div>
            <div className="text-xs" style={{ color: colors.onSurfaceSecondary }}>Lighting</div>
            <div className="grid grid-cols-5 gap-1">
              {LIGHT_ICONS.map(({ k, label, Icon }) => (
                <button key={k}
                        onClick={() => {
                          setPlacingIcon(k);
                          setTool("pointer");
                        }}
                        title={label}
                        className="flex items-center justify-center h-7 rounded"
                        style={{
                          backgroundColor: placingIcon === k ? colors.brandTertiary : colors.surfaceSecondary,
                          color: placingIcon === k ? colors.onBrandTertiary : colors.onSurfaceSecondary,
                        }}
                        data-testid={`cad-icon-${k}`}>
                  <Icon size={14} />
                </button>
              ))}
            </div>
          </section>

          {/* CAD-2 MARCO Designer */}
          <section className="rounded-2xl p-3 space-y-2"
                   style={{ border: `1px solid ${colors.border}` }}
                   data-testid="cad-marco-section">
            <div className="text-xs font-semibold uppercase tracking-wider"
                 style={{ color: colors.onSurfaceSecondary }}>MARCO Designer</div>
            <textarea
              value={marcoPrompt}
              onChange={(e) => setMarcoPrompt(e.target.value)}
              placeholder="Describe the layout you want…"
              className="w-full text-xs p-2 rounded resize-none"
              style={{ border: `1px solid ${colors.border}`, minHeight: 60 }}
              rows={3}
              data-testid="cad-marco-textarea" />
            <div className="flex gap-1">
              <button onClick={marcoGenerate}
                      disabled={marcoLoading || !marcoPrompt.trim()}
                      className="flex-1 px-3 py-1.5 rounded-lg text-xs font-semibold text-white"
                      style={{ backgroundColor: colors.brand,
                               opacity: marcoLoading ? 0.5 : 1 }}
                      data-testid="cad-marco-generate">
                {marcoPreview ? "Regenerate" : (marcoLoading ? "Generating…" : "Generate")}
              </button>
            </div>
            {marcoPreview && (
              <>
                <div className="text-xs rounded p-2"
                     style={{ backgroundColor: colors.surfaceSecondary,
                              color: colors.onSurfaceSecondary }}
                     data-testid="cad-marco-reasoning">
                  {marcoPreview.reasoning}
                </div>
                {(marcoPreview.warnings || []).length > 0 && (
                  <div className="text-xs rounded p-2"
                       style={{ backgroundColor: "#FEF3C7", color: "#92400E" }}
                       data-testid="cad-marco-warnings">
                    {marcoPreview.warnings.map((w, i) => (
                      <div key={i}>• {w}</div>
                    ))}
                  </div>
                )}
                <div className="flex gap-1">
                  <button onClick={marcoAccept}
                          className="flex-1 px-3 py-1.5 rounded-lg text-xs font-semibold text-white"
                          style={{ backgroundColor: "#059669" }}
                          data-testid="cad-marco-accept">
                    Accept
                  </button>
                  <button onClick={marcoDiscard}
                          className="flex-1 px-3 py-1.5 rounded-lg text-xs font-semibold"
                          style={{ backgroundColor: colors.surfaceSecondary,
                                   color: colors.onSurfaceSecondary }}
                          data-testid="cad-marco-discard">
                    Discard
                  </button>
                </div>
              </>
            )}
          </section>
        </aside>
      </div>

      <Toast text={toast} />
    </div>
  );
}


/* ────────────────────────────────────────────────────────────────
   Konva shape renderers
   ──────────────────────────────────────────────────────────────── */


function ShapeNode({ el, canvasSize, cw, ch, onDelete, ghost, testidOverride }) {
  const type = el.type;
  const tid = testidOverride || `cad-shape-${el.id}`;
  const stroke = ghost ? "#059669" : "#0F172A";
  const fillOpacity = ghost ? 0.25 : 0.5;

  // CAD-2 pool / spa via coords polygon (MARCO output + accepted
  // shapes). Legacy ``x/y/w/h`` pool + spa fall through to the
  // legacy branches below.
  if ((type === "pool" || type === "spa")
      && Array.isArray(el.coords) && el.coords.length >= 3) {
    const flat = el.coords.flatMap(
      (p) => [p.x * canvasSize.w, p.y * canvasSize.h],
    );
    const centroid = polygonCentroid(el.coords);
    const sqft = el.computed?.area_sqft
      ?? shoelaceSqft(el.coords, cw, ch);
    // Rectangular pool/spa also gets a width×length label.
    const fill = type === "pool" ? "#0284C7" : "#7C3AED";
    let dimText = null;
    if (el.coords.length === 4) {
      const w1 = Math.hypot(
        (el.coords[1].x - el.coords[0].x) * cw,
        (el.coords[1].y - el.coords[0].y) * ch,
      );
      const w2 = Math.hypot(
        (el.coords[2].x - el.coords[1].x) * cw,
        (el.coords[2].y - el.coords[1].y) * ch,
      );
      dimText = `${Math.round(w1)}' × ${Math.round(w2)}'`;
    }
    return (
      <Group data-testid={tid} onClick={onDelete}>
        <Line points={flat} closed
              fill={fill} opacity={fillOpacity}
              stroke={stroke} strokeWidth={1} />
        {sqft > 0 && (
          <ShapeLabel
            x={centroid.x * canvasSize.w}
            y={centroid.y * canvasSize.h - (dimText ? 8 : 0)}
            text={`${Math.round(sqft)} sq ft`}
            testid={`cad-shape-label-${el.id}`}
          />
        )}
        {dimText && (
          <ShapeLabel
            x={centroid.x * canvasSize.w}
            y={centroid.y * canvasSize.h + 8}
            text={dimText}
            testid={`cad-shape-dims-${el.id}`}
          />
        )}
      </Group>
    );
  }

  // Rectangular pool/spa/legacy rectangle
  if (type === "rect" || (type === "pool" && el.x !== undefined)) {
    const w = (el.w || 0.1) * canvasSize.w;
    const h = (el.h || 0.06) * canvasSize.h;
    const x = (el.x || 0) * canvasSize.w;
    const y = (el.y || 0) * canvasSize.h;
    return (
      <Group data-testid={tid} onClick={onDelete}>
        <Rect x={x} y={y} width={w} height={h}
              fill="#0284C7" opacity={fillOpacity} stroke={stroke} strokeWidth={1} />
        <ShapeLabel x={x + w / 2} y={y + h / 2}
                    text={`${((el.w || 0.1) * cw).toFixed(0)}' × ${((el.h || 0.06) * ch).toFixed(0)}'`}
                    testid={`cad-shape-label-${el.id}`} />
      </Group>
    );
  }
  if (type === "spa" && el.x !== undefined) {
    // Circular spa via a Konva Circle centered on x,y (legacy shape).
    const r = ((el.w || 0.05) * canvasSize.w) / 2;
    const cx = (el.x || 0) * canvasSize.w + r;
    const cy = (el.y || 0) * canvasSize.h + r;
    return (
      <Group data-testid={tid} onClick={onDelete}>
        <Circle x={cx} y={cy} radius={r}
                fill="#7C3AED" opacity={fillOpacity} stroke={stroke} strokeWidth={1} />
      </Group>
    );
  }
  if (type === "circle") {
    const r = ((el.w || 0.05) * canvasSize.w) / 2;
    const cx = (el.x || 0) * canvasSize.w + r;
    const cy = (el.y || 0) * canvasSize.h + r;
    return (
      <Group data-testid={tid} onClick={onDelete}>
        <Circle x={cx} y={cy} radius={r}
                fill="transparent" stroke={stroke} strokeWidth={2} />
      </Group>
    );
  }
  if (type === "firepit") {
    const w = (el.w || 0.05) * canvasSize.w;
    const h = (el.h || 0.05) * canvasSize.h;
    const x = (el.x || 0) * canvasSize.w;
    const y = (el.y || 0) * canvasSize.h;
    return (
      <Group data-testid={tid} onClick={onDelete}>
        <Rect x={x} y={y} width={w} height={h}
              fill="#DC2626" opacity={fillOpacity} stroke={stroke} strokeWidth={1}
              cornerRadius={4} />
      </Group>
    );
  }
  if (type === "text") {
    return (
      <Group data-testid={tid} onClick={onDelete}>
        <KText x={(el.x || 0) * canvasSize.w}
               y={(el.y || 0) * canvasSize.h}
               text={el.label || "Label"} fontSize={12}
               fill={stroke} />
      </Group>
    );
  }
  // Legacy tree/cactus rendered as an icon-key lookup.
  if (LEGACY_ICON_MAP[type]) {
    const cx = (el.x || 0) * canvasSize.w;
    const cy = (el.y || 0) * canvasSize.h;
    return (
      <Group data-testid={tid} onClick={onDelete}>
        <Circle x={cx} y={cy} radius={8} fill="#059669" opacity={fillOpacity} />
        <KText x={cx - 6} y={cy - 6}
               text={type === "tree" ? "T" : "C"} fontSize={10} fill="#fff" />
      </Group>
    );
  }
  // CAD-2 icon element — coords[0], props.icon.
  if (type === "icon" && Array.isArray(el.coords) && el.coords.length > 0) {
    const cx = el.coords[0].x * canvasSize.w;
    const cy = el.coords[0].y * canvasSize.h;
    return (
      <Group data-testid={tid}
             data-icon={el.props?.icon}
             onClick={onDelete}>
        <Circle x={cx} y={cy} radius={9} fill="#059669" opacity={fillOpacity} />
      </Group>
    );
  }
  // Pavers polygon.
  if (type === "paver" && Array.isArray(el.coords)) {
    const flat = el.coords.flatMap(
      (p) => [p.x * canvasSize.w, p.y * canvasSize.h],
    );
    const centroid = polygonCentroid(el.coords);
    const sqft = el.computed?.area_sqft
      ?? shoelaceSqft(el.coords, cw, ch);
    return (
      <Group data-testid={tid} onClick={onDelete}>
        <Line points={flat} closed
              fill="#D97706" opacity={fillOpacity}
              stroke={stroke} strokeWidth={1} />
        {sqft > 0 && (
          <ShapeLabel
            x={centroid.x * canvasSize.w} y={centroid.y * canvasSize.h}
            text={`${Math.round(sqft)} sq ft`}
            testid={`cad-shape-label-${el.id}`}
          />
        )}
      </Group>
    );
  }
  // Wall polyline.
  if (type === "wall" && Array.isArray(el.coords) && el.coords.length >= 2) {
    const flat = el.coords.flatMap(
      (p) => [p.x * canvasSize.w, p.y * canvasSize.h],
    );
    const ft = el.computed?.linear_ft
      ?? polylineLengthFt(el.coords, cw, ch);
    // Label at the midpoint of the last segment.
    const mid = el.coords.length >= 2 ? {
      x: (el.coords[0].x + el.coords[el.coords.length - 1].x) / 2,
      y: (el.coords[0].y + el.coords[el.coords.length - 1].y) / 2,
    } : { x: 0.5, y: 0.5 };
    return (
      <Group data-testid={tid} onClick={onDelete}>
        <Line points={flat} stroke={stroke} strokeWidth={3} />
        {ft > 0 && (
          <ShapeLabel
            x={mid.x * canvasSize.w} y={mid.y * canvasSize.h}
            text={`${Math.round(ft)} ft`}
            testid={`cad-shape-label-${el.id}`}
          />
        )}
      </Group>
    );
  }
  // Persisted dimension (tape measure).
  if (type === "dimension" && Array.isArray(el.coords) && el.coords.length === 2) {
    return <TapeGlyph coords={el.coords} size={canvasSize}
                      cw={cw} ch={ch} testid={tid} />;
  }
  // Boundary polygon element (defensive — boundary usually lives
  // on ``design.boundary``, not in ``elements``).
  if (type === "boundary" && Array.isArray(el.coords)) {
    const flat = el.coords.flatMap(
      (p) => [p.x * canvasSize.w, p.y * canvasSize.h],
    );
    return (
      <Group data-testid={tid} onClick={onDelete}>
        <Line points={flat} closed stroke="#7C3AED"
              strokeWidth={2} dash={[6, 4]} />
      </Group>
    );
  }
  return null;
}


function ShapeLabel({ x, y, text, testid }) {
  return (
    <Group data-testid={testid}
           data-label-text={text}>
      <Rect x={x - 26} y={y - 8} width={52} height={16}
            fill="#fff" opacity={0.9} cornerRadius={3} />
      <KText x={x - 24} y={y - 5} text={text}
             fontSize={11} fontStyle="bold" fill="#0F172A" />
    </Group>
  );
}


function PaverPreview({ coords, size }) {
  const flat = coords.flatMap(
    (p) => [p.x * size.w, p.y * size.h],
  );
  return (
    <Group data-testid="cad-paver-inprogress">
      <Line points={flat} stroke="#D97706" strokeWidth={2}
            dash={[6, 4]} />
      {coords.map((p, i) => (
        <Circle key={i} x={p.x * size.w} y={p.y * size.h}
                radius={3} fill="#D97706" />
      ))}
    </Group>
  );
}


function WallPreview({ coords, size }) {
  const flat = coords.flatMap(
    (p) => [p.x * size.w, p.y * size.h],
  );
  return (
    <Group data-testid="cad-wall-inprogress">
      <Line points={flat} stroke="#0F172A" strokeWidth={2}
            dash={[6, 4]} />
      {coords.map((p, i) => (
        <Circle key={i} x={p.x * size.w} y={p.y * size.h}
                radius={3} fill="#0F172A" />
      ))}
    </Group>
  );
}


function TapeOverlay({ coords, size, cw, ch }) {
  return (
    <TapeGlyph coords={coords} size={size} cw={cw} ch={ch}
               testid="cad-tape-inprogress" />
  );
}


function TapeGlyph({ coords, size, cw, ch, testid }) {
  const [a, b] = coords;
  const ax = a.x * size.w;
  const ay = a.y * size.h;
  const bx = b.x * size.w;
  const by = b.y * size.h;
  const totalFt = polylineLengthFt(coords, cw, ch);
  const label = feetToImperial(totalFt);
  const midX = (ax + bx) / 2;
  const midY = (ay + by) / 2;
  return (
    <Group data-testid={testid} data-label-text={label}>
      <Line points={[ax, ay, bx, by]}
            stroke="#DC2626" strokeWidth={2} />
      {/* End ticks */}
      <Circle x={ax} y={ay} radius={4}
              fill="#fff" stroke="#DC2626" strokeWidth={2} />
      <Circle x={bx} y={by} radius={4}
              fill="#fff" stroke="#DC2626" strokeWidth={2} />
      <ShapeLabel x={midX} y={midY} text={label}
                  testid={`${testid}-label`} />
    </Group>
  );
}
