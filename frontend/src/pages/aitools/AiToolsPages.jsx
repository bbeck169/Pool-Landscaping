import React, { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "@/api";
import { colors } from "@/theme";
import AddressAutocomplete from "@/components/AddressAutocomplete";
import { ZillowUsageChip } from "@/components/ZillowUsageChip";

/* ═══ Phase 11 — Web AI & Tools (all admin-only, one dense module) ═══ */

const BASE = process.env.REACT_APP_BACKEND_URL;

function Card({ children, testid, className = "" }) {
  return (
    <div
      className={`rounded-2xl bg-white p-5 ${className}`}
      style={{ border: `1px solid ${colors.border}` }}
      data-testid={testid}
    >
      {children}
    </div>
  );
}

function Toast({ text }) {
  if (!text) return null;
  return (
    <div className="fixed bottom-6 right-6 z-50 px-4 py-2 rounded-xl text-sm text-white shadow-lg"
         style={{ backgroundColor: colors.onSurface }} data-testid="ai-tool-toast">
      {text}
    </div>
  );
}

async function fileToBase64(file) {
  return new Promise((resolve) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || "").split(",", 2)[1]);
    reader.readAsDataURL(file);
  });
}

/* ═══════════════════════════════════════════════════════════════════
   1. Landscape AI
   ═══════════════════════════════════════════════════════════════════ */
export function LandscapeAI() {
  const [imageB64, setImageB64] = useState("");
  const [style, setStyle] = useState("Desert Contemporary");
  const [elements, setElements] = useState(["Fire pit", "Palm trees", "Turf lawn"]);
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [history, setHistory] = useState([]);
  const [toast, setToast] = useState("");
  const styles = ["Modern", "Mediterranean", "Desert Contemporary", "Traditional", "Resort"];
  const featureOptions = ["Fire pit", "Palm trees", "Turf lawn", "Pergola", "Water feature", "BBQ island", "Cactus garden", "Paver walkway"];

  useEffect(() => { api.get("/landscape/renders").then((r) => setHistory(Array.isArray(r) ? r : [])); }, []);

  const onFile = async (e) => {
    const f = e.target.files?.[0]; if (!f) return;
    setImageB64(await fileToBase64(f));
  };
  const toggleEl = (el) => setElements((v) => v.includes(el) ? v.filter((x) => x !== el) : [...v, el]);

  const generate = async () => {
    if (!imageB64) return setToast("Upload a yard photo first");
    setBusy(true); setResult(null);
    try {
      const r = await api.post("/landscape/render", {
        image_base64: imageB64, style, elements, prompt,
      }, 60000);
      setResult(r);
      api.get("/landscape/renders").then((rr) => setHistory(Array.isArray(rr) ? rr : []));
    } catch (e) { setToast(e.message); }
    finally { setBusy(false); }
  };

  return (
    <div className="p-4 md:p-8 max-w-7xl mx-auto space-y-6" data-testid="landscape-ai-page">
      <div>
        <h1 className="text-3xl font-bold">Landscape AI</h1>
        <p className="text-sm" style={{ color: colors.onSurfaceSecondary }}>Upload a yard photo · describe the redesign · generate a photoreal render.</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card testid="landscape-input">
          <div className="space-y-4">
            <div>
              <label className="text-xs font-semibold block mb-1">Yard photo</label>
              <input type="file" accept="image/*" onChange={onFile} className="text-sm" data-testid="landscape-file" />
              {imageB64 && <img alt="yard" src={`data:image/jpeg;base64,${imageB64}`} className="mt-2 rounded-xl max-h-40" />}
            </div>
            <div>
              <label className="text-xs font-semibold block mb-1">Style</label>
              <select value={style} onChange={(e) => setStyle(e.target.value)}
                      className="w-full px-3 py-2 rounded-lg text-sm" style={{ border: `1px solid ${colors.border}` }}
                      data-testid="landscape-style">
                {styles.map((s) => <option key={s}>{s}</option>)}
              </select>
            </div>
            <div>
              <label className="text-xs font-semibold block mb-1">Features</label>
              <div className="flex flex-wrap gap-2">
                {featureOptions.map((el) => (
                  <button key={el} onClick={() => toggleEl(el)}
                          className="px-3 py-1 rounded-full text-xs font-semibold"
                          style={{
                            backgroundColor: elements.includes(el) ? colors.brandTertiary : colors.surfaceSecondary,
                            color: elements.includes(el) ? colors.onBrandTertiary : colors.onSurfaceSecondary,
                          }}
                          data-testid={`landscape-el-${el.toLowerCase().replace(/\s+/g,"-")}`}>
                    {el}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <label className="text-xs font-semibold block mb-1">Additional notes</label>
              <textarea value={prompt} onChange={(e) => setPrompt(e.target.value)}
                        placeholder="e.g. drought-tolerant plants, gravel + boulders, spa nook…"
                        rows={3}
                        className="w-full px-3 py-2 rounded-lg text-sm" style={{ border: `1px solid ${colors.border}` }}
                        data-testid="landscape-prompt" />
            </div>
            <button onClick={generate} disabled={busy}
                    className="w-full py-2 rounded-xl text-sm font-semibold text-white"
                    style={{ backgroundColor: colors.brand, opacity: busy ? 0.6 : 1 }}
                    data-testid="landscape-generate">
              {busy ? "Generating…  (15-30s)" : "Generate render"}
            </button>
          </div>
        </Card>

        <Card testid="landscape-output">
          {!result && !busy && <div className="text-sm py-16 text-center" style={{ color: colors.onSurfaceSecondary }}>Your rendered design appears here.</div>}
          {busy && <div className="text-sm py-16 text-center" style={{ color: colors.onSurfaceSecondary }}>Sketching, painting, rendering…</div>}
          {result && (
            <>
              <img alt="rendered" src={`data:image/png;base64,${result.output_image}`} className="rounded-xl w-full" data-testid="landscape-render-image" />
              {result.description && (
                <div className="mt-3 text-sm" style={{ color: colors.onSurface }} data-testid="landscape-description">
                  {result.description}
                </div>
              )}
              {result.shopping_list?.length > 0 && (
                <div className="mt-4">
                  <div className="text-xs font-semibold uppercase tracking-wider mb-2" style={{ color: colors.onSurfaceSecondary }}>Shopping list</div>
                  {result.shopping_list.map((it, i) => (
                    <label key={i} className="flex items-center gap-2 py-1 text-sm cursor-pointer" data-testid={`landscape-shop-${i}`}>
                      <input type="checkbox" defaultChecked />
                      <span className="flex-1">{it.item}</span>
                      <span className="text-xs" style={{ color: colors.onSurfaceSecondary }}>{it.category}</span>
                      <span className="font-semibold">${(it.estimated_cost || 0).toLocaleString()}</span>
                    </label>
                  ))}
                </div>
              )}
              <div className="mt-3 flex gap-2">
                <a download="landscape.png" href={`data:image/png;base64,${result.output_image}`}
                   className="px-3 py-2 rounded-lg text-xs font-semibold" style={{ backgroundColor: colors.surfaceSecondary }} data-testid="landscape-download">
                  Download
                </a>
                <button onClick={generate}
                        className="px-3 py-2 rounded-lg text-xs font-semibold text-white"
                        style={{ backgroundColor: colors.brand }} data-testid="landscape-regen">
                  Regenerate
                </button>
              </div>
            </>
          )}
        </Card>
      </div>

      {history.length > 0 && (
        <div>
          <h2 className="text-sm font-bold mb-2" style={{ color: colors.onSurfaceSecondary }}>History</h2>
          <div className="grid grid-cols-3 md:grid-cols-6 gap-2">
            {history.slice(0, 12).map((h) => (
              <div key={h.id} className="rounded-xl overflow-hidden" style={{ border: `1px solid ${colors.border}` }} data-testid={`landscape-history-${h.id}`}>
                <img alt="past" src={`data:image/png;base64,${h.output_image}`} className="w-full h-24 object-cover" />
              </div>
            ))}
          </div>
        </div>
      )}
      <Toast text={toast} />
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════
   2. CAD Studio
   ═══════════════════════════════════════════════════════════════════ */
export function CadList() {
  const [rows, setRows] = useState(null);
  const [toast, setToast] = useState("");
  useEffect(() => { api.get("/designs").then((r) => setRows(Array.isArray(r) ? r : [])); }, []);
  const create = async () => {
    const r = await api.post("/designs", { name: "New design" });
    window.location.href = `/cad/editor/${r.id}`;
  };
  return (
    <div className="p-4 md:p-8 max-w-6xl mx-auto space-y-4" data-testid="cad-list-page">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold">CAD Studio</h1>
        <button onClick={create} className="px-4 py-2 rounded-xl text-sm font-semibold text-white" style={{ backgroundColor: colors.brand }} data-testid="cad-new">+ New design</button>
      </div>
      <Card>
        {rows === null && <div className="text-sm" style={{ color: colors.onSurfaceSecondary }}>Loading…</div>}
        {rows && rows.length === 0 && <div className="text-sm text-center py-8" style={{ color: colors.onSurfaceSecondary }}>No designs yet.</div>}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {rows && rows.map((d) => (
            <Link key={d.id} to={`/cad/editor/${d.id}`}
                  className="rounded-xl p-3 flex flex-col gap-2 hover:brightness-95 transition"
                  style={{ border: `1px solid ${colors.border}` }}
                  data-testid={`cad-card-${d.id}`}>
              {d.thumbnail
                ? <img alt="thumb" src={d.thumbnail} className="rounded w-full h-24 object-cover" />
                : <div className="rounded w-full h-24 flex items-center justify-center text-xs" style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurfaceSecondary }}>No preview</div>}
              <div className="font-semibold text-sm">{d.name}</div>
              <div className="text-xs" style={{ color: colors.onSurfaceSecondary }}>Updated {(d.updated_at || "").slice(0, 10)}</div>
            </Link>
          ))}
        </div>
      </Card>
      <Toast text={toast} />
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
];

export function CadEditor() {
  const { id } = useParams();
  const [design, setDesign] = useState(null);
  const [tool, setTool] = useState("pointer");
  const [dragging, setDragging] = useState(null);
  const [toast, setToast] = useState("");
  const canvasRef = useRef(null);

  useEffect(() => {
    if (!id) return;
    api.get(`/designs/${id}`).then(setDesign).catch(() => setToast("Failed to load"));
  }, [id]);

  const canvasSize = { w: 800, h: 500 };
  const scale = design ? (canvasSize.w / (design.canvas_w_ft || 60)) : 12;

  const onCanvasMouseDown = (e) => {
    if (tool === "pointer" || !design) return;
    const rect = canvasRef.current.getBoundingClientRect();
    const x = (e.clientX - rect.left) / rect.width;
    const y = (e.clientY - rect.top) / rect.height;
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
      });
      setToast("Saved");
    } catch (e) { setToast(e.message); }
  };

  if (!design) return <div className="p-8 text-sm" style={{ color: colors.onSurfaceSecondary }}>Loading design…</div>;

  // Mobile guard — the drawing surface is desktop/tablet only.
  if (typeof window !== "undefined" && window.innerWidth < 768) {
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
        {CAD_TOOLS.map((t) => (
          <button key={t.k} onClick={() => setTool(t.k)}
                  className="px-3 py-1.5 rounded-lg text-xs font-semibold"
                  style={{
                    backgroundColor: tool === t.k ? colors.brandTertiary : colors.surfaceSecondary,
                    color: tool === t.k ? colors.onBrandTertiary : colors.onSurfaceSecondary,
                  }}
                  data-testid={`cad-tool-${t.k}`}>
            {t.label}
          </button>
        ))}
      </div>

      <div
        ref={canvasRef}
        onMouseDown={onCanvasMouseDown}
        className="relative rounded-2xl"
        style={{
          width: "100%", aspectRatio: `${canvasSize.w}/${canvasSize.h}`,
          backgroundColor: "#F0F9FF",
          backgroundImage: "linear-gradient(#E0F2FE 1px, transparent 1px), linear-gradient(90deg, #E0F2FE 1px, transparent 1px)",
          backgroundSize: `${100/12}% ${100/8}%`,
          border: `1px solid ${colors.border}`,
          cursor: tool === "pointer" ? "default" : "crosshair",
        }}
        data-testid="cad-canvas"
      >
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
            }}
            data-testid={`cad-elem-${el.id}`}
          >
            {el.type === "tree" && "🌴"}
            {el.type === "cactus" && "🌵"}
            {el.type === "text" && <span style={{ color: "#111", fontSize: 12 }}>{el.label || "Label"}</span>}
          </div>
        ))}
      </div>
      <div className="text-xs" style={{ color: colors.onSurfaceSecondary }}>
        Canvas: {design.canvas_w_ft || 60} ft × {design.canvas_h_ft || 40} ft · {design.elements?.length || 0} elements · Click pointer + element to delete.
      </div>
      <Toast text={toast} />
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════
   3. Satellite Measure
   ═══════════════════════════════════════════════════════════════════ */
export function SatelliteMeasure() {
  const [address, setAddress] = useState("");
  const [center, setCenter] = useState([33.7897, -112.3226]);
  const [points, setPoints] = useState([]);
  const [saved, setSaved] = useState([]);
  const [toast, setToast] = useState("");
  const [customerId, setCustomerId] = useState("");
  const [customers, setCustomers] = useState([]);

  useEffect(() => {
    api.get("/measurements").then((r) => setSaved(Array.isArray(r) ? r : []));
    api.get("/customers").then((r) => setCustomers(Array.isArray(r) ? r : (r?.rows || [])));
  }, []);

  // Shoelace formula (approx, degrees to feet via cos(lat) factor).
  const areaSqft = React.useMemo(() => {
    if (points.length < 3) return 0;
    const R = 20925721.784776; // Earth mean radius in feet
    const rad = (d) => d * Math.PI / 180;
    let area = 0;
    for (let i = 0; i < points.length; i++) {
      const [lat1, lng1] = points[i];
      const [lat2, lng2] = points[(i + 1) % points.length];
      area += rad(lng2 - lng1) * (2 + Math.sin(rad(lat1)) + Math.sin(rad(lat2)));
    }
    return Math.abs(area * R * R / 2);
  }, [points]);

  const clickMap = (lat, lng) => setPoints((p) => [...p, [lat, lng]]);

  const savePoly = async () => {
    if (points.length < 3) return setToast("Need at least 3 points");
    const r = await api.post("/measurements", {
      name: address || "Measurement",
      mode: "area",
      points: points.map(([lat, lng]) => ({ latitude: lat, longitude: lng })),
      area_sqft: areaSqft,
      customer_id: customerId || null,
    });
    setSaved([r, ...saved]);
    setPoints([]);
    setToast(`Saved · ${Math.round(areaSqft).toLocaleString()} sqft`);
  };

  return (
    <div className="p-4 md:p-6 max-w-7xl mx-auto space-y-4" data-testid="measure-page">
      <div>
        <h1 className="text-3xl font-bold">Satellite Measure</h1>
        <p className="text-sm" style={{ color: colors.onSurfaceSecondary }}>Click on the map to trace a polygon — area computes live in sq ft.</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Card className="lg:col-span-2">
          <div className="mb-3">
            <AddressAutocomplete
              value={address}
              onChange={setAddress}
              onSelect={(p) => { setAddress(p.formatted); if (p.lat && p.lng) setCenter([p.lat, p.lng]); }}
              placeholder="Enter property address"
              testid="measure-address"
            />
          </div>
          <MeasureMap center={center} points={points} onClickMap={clickMap} />
        </Card>

        <Card>
          <div className="text-xs font-semibold uppercase tracking-wider mb-1" style={{ color: colors.onSurfaceSecondary }}>Current polygon</div>
          <div className="text-3xl font-bold" data-testid="measure-area-sqft">{Math.round(areaSqft).toLocaleString()}</div>
          <div className="text-xs mb-3" style={{ color: colors.onSurfaceSecondary }}>square feet · {points.length} vertices</div>

          <div className="mb-3">
            <label className="text-xs font-semibold block mb-1">Customer (optional)</label>
            <select value={customerId} onChange={(e) => setCustomerId(e.target.value)}
                    className="w-full px-3 py-2 rounded-lg text-sm" style={{ border: `1px solid ${colors.border}` }}
                    data-testid="measure-customer">
              <option value="">Unassigned</option>
              {customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </div>

          <div className="flex gap-2">
            <button onClick={savePoly} className="flex-1 px-3 py-2 rounded-lg text-xs font-semibold text-white" style={{ backgroundColor: colors.brand }} data-testid="measure-save">Save</button>
            <button onClick={() => setPoints([])} className="px-3 py-2 rounded-lg text-xs font-semibold" style={{ backgroundColor: colors.surfaceSecondary }} data-testid="measure-reset">Reset</button>
          </div>
        </Card>
      </div>

      <Card testid="measure-history">
        <div className="text-sm font-bold mb-2">Recent measurements</div>
        {saved.length === 0 && <div className="text-xs" style={{ color: colors.onSurfaceSecondary }}>None yet.</div>}
        {saved.slice(0, 6).map((m) => (
          <div key={m.id} className="flex items-center justify-between py-1 border-b last:border-0" style={{ borderColor: colors.border }}>
            <div className="text-sm">{m.name}</div>
            <div className="text-xs" style={{ color: colors.onSurfaceSecondary }}>{Math.round(m.area_sqft || 0).toLocaleString()} sqft</div>
          </div>
        ))}
      </Card>

      <Toast text={toast} />
    </div>
  );
}

function MeasureMap({ center, points, onClickMap }) {
  // Uses Leaflet directly (satellite tiles from Esri) for reliability without provider toggle.
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const layerRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const L = await import("leaflet");
      await import("leaflet/dist/leaflet.css");
      if (cancelled || !containerRef.current || mapRef.current) return;
      mapRef.current = L.map(containerRef.current, { center, zoom: 18 });
      L.tileLayer(
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        { attribution: "Tiles © Esri", maxZoom: 21 }
      ).addTo(mapRef.current);
      mapRef.current.on("click", (e) => onClickMap(e.latlng.lat, e.latlng.lng));
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line
  }, []);

  useEffect(() => {
    if (mapRef.current) mapRef.current.setView(center, 18);
  }, [center]);

  useEffect(() => {
    (async () => {
      const L = await import("leaflet");
      if (!mapRef.current) return;
      if (layerRef.current) mapRef.current.removeLayer(layerRef.current);
      if (points.length >= 2) {
        layerRef.current = points.length >= 3
          ? L.polygon(points, { color: "#0284C7", fillOpacity: 0.25 }).addTo(mapRef.current)
          : L.polyline(points, { color: "#0284C7" }).addTo(mapRef.current);
      } else if (points.length === 1) {
        layerRef.current = L.circleMarker(points[0], { radius: 5, color: "#0284C7" }).addTo(mapRef.current);
      }
    })();
  }, [points]);

  return <div ref={containerRef} className="rounded-xl" style={{ height: 520, border: `1px solid ${colors.border}` }} data-testid="measure-map" />;
}

/* ═══════════════════════════════════════════════════════════════════
   4. Virtual Bid
   ═══════════════════════════════════════════════════════════════════ */
export function VirtualBid() {
  const [address, setAddress] = useState("");
  const [prop, setProp] = useState(null);
  const [bid, setBid] = useState(null);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState("");
  const [manual, setManual] = useState({ lot: "", home: "" });
  const [rateLimited, setRateLimited] = useState(false);

  const lookup = async () => {
    if (!address) return;
    setBusy(true); setProp(null); setBid(null); setRateLimited(false);
    try {
      const r = await api.get(`/property/lookup?address=${encodeURIComponent(address)}`);
      setProp(r);
    } catch (e) {
      if (String(e?.message || "").includes("429")) setRateLimited(true);
      setToast(`${e.message} — enter facts manually below`);
    }
    finally { setBusy(false); }
  };

  const generate = async () => {
    setBusy(true);
    try {
      const payload = {
        address,
        lot_size_sqft: prop?.lot_size_sqft || Number(manual.lot) || null,
        home_sqft: prop?.sqft || Number(manual.home) || null,
        year_built: prop?.year_built, beds: prop?.beds, baths: prop?.baths,
        zestimate: prop?.zestimate,
      };
      const r = await api.post("/virtual-bid/generate", payload, 60000);
      setBid(r);
    } catch (e) { setToast(e.message); }
    finally { setBusy(false); }
  };

  return (
    <div className="p-4 md:p-8 max-w-5xl mx-auto space-y-6" data-testid="virtual-bid-page">
      <div>
        <h1 className="text-3xl font-bold">Virtual Bid</h1>
        <p className="text-sm" style={{ color: colors.onSurfaceSecondary }}>Address → Zillow lookup → AI-generated bid narrative + pricing.</p>
        <div className="mt-3">
          <ZillowUsageChip rateLimited={rateLimited} refreshKey={prop ? 1 : 0}
                            testid="vbid-zillow-chip" />
        </div>
      </div>

      <Card>
        <div className="flex gap-2">
          <div className="flex-1">
            <AddressAutocomplete value={address} onChange={setAddress}
                                 onSelect={(p) => setAddress(p.formatted)}
                                 placeholder="Enter property address" testid="vbid-address" />
          </div>
          <button onClick={lookup} disabled={busy || !address}
                  className="px-4 py-2 rounded-xl text-sm font-semibold text-white"
                  style={{ backgroundColor: colors.brand, opacity: busy ? 0.6 : 1 }}
                  data-testid="vbid-lookup">
            {busy ? "…" : "Look up"}
          </button>
        </div>

        {prop && (
          <div className="mt-4 grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
            <FactTile label="Lot size" value={prop.lot_size_sqft ? `${Math.round(prop.lot_size_sqft).toLocaleString()} sqft` : "—"} />
            <FactTile label="Home size" value={prop.sqft ? `${Math.round(prop.sqft).toLocaleString()} sqft` : "—"} />
            <FactTile label="Built" value={prop.year_built || "—"} />
            <FactTile label="Zestimate" value={prop.zestimate ? `$${Math.round(prop.zestimate).toLocaleString()}` : "—"} />
          </div>
        )}

        {!prop && !busy && (
          <div className="mt-4">
            <div className="text-xs mb-1" style={{ color: colors.onSurfaceSecondary }}>Or enter facts manually:</div>
            <div className="grid grid-cols-2 gap-2">
              <input placeholder="Lot sqft" value={manual.lot} onChange={(e) => setManual({ ...manual, lot: e.target.value })}
                     className="px-3 py-2 rounded-lg text-sm" style={{ border: `1px solid ${colors.border}` }}
                     data-testid="vbid-manual-lot" />
              <input placeholder="Home sqft" value={manual.home} onChange={(e) => setManual({ ...manual, home: e.target.value })}
                     className="px-3 py-2 rounded-lg text-sm" style={{ border: `1px solid ${colors.border}` }}
                     data-testid="vbid-manual-home" />
            </div>
          </div>
        )}

        <button onClick={generate} disabled={busy || !address}
                className="mt-4 w-full py-2 rounded-xl text-sm font-semibold text-white"
                style={{ backgroundColor: colors.brandSecondary, opacity: busy ? 0.6 : 1 }}
                data-testid="vbid-generate">
          {busy ? "Generating…" : "Generate bid"}
        </button>
      </Card>

      {bid && (
        <Card testid="vbid-result">
          <div className="grid grid-cols-3 gap-3 mb-4">
            <FactTile label="Est. pool volume" value={`${bid.estimated_pool_gallons.toLocaleString()} gal`} />
            <FactTile label="Weekly service" value={`$${bid.weekly_service_price}/mo`} />
            <FactTile label="One-time cleanup" value={`$${bid.one_time_cleanup_price}`} />
          </div>
          <div className="whitespace-pre-line text-sm" style={{ color: colors.onSurface }}>{bid.narrative}</div>
        </Card>
      )}

      <Toast text={toast} />
    </div>
  );
}

function FactTile({ label, value }) {
  return (
    <div className="rounded-xl p-3" style={{ backgroundColor: colors.surfaceSecondary }}>
      <div className="text-xs uppercase tracking-wider" style={{ color: colors.onSurfaceSecondary }}>{label}</div>
      <div className="font-bold">{value}</div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════
   5. Digital Business Card
   ═══════════════════════════════════════════════════════════════════ */
export function DigitalCardList() {
  const [rows, setRows] = useState([]);
  const [form, setForm] = useState({ slug: "", name: "", title: "", phone: "", email: "", website: "", brand_color: "#0284C7", company_name: "Pool & Landscaping of Vistancia" });
  const [toast, setToast] = useState("");
  const load = () => api.get("/cards").then((r) => setRows(Array.isArray(r) ? r : []));
  useEffect(() => { load(); }, []);
  const save = async () => {
    try {
      await api.post("/cards", form);
      setToast("Saved");
      setForm({ slug: "", name: "", title: "", phone: "", email: "", website: "", brand_color: "#0284C7", company_name: "Pool & Landscaping of Vistancia" });
      load();
    } catch (e) { setToast(e.message); }
  };
  return (
    <div className="p-4 md:p-8 max-w-5xl mx-auto space-y-4" data-testid="card-list-page">
      <h1 className="text-3xl font-bold">Digital Business Cards</h1>

      <Card testid="card-form">
        <div className="grid grid-cols-2 gap-3">
          <input placeholder="Name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value, slug: form.slug || e.target.value.toLowerCase().replace(/\s+/g,"-") })}
                 className="px-3 py-2 rounded-lg text-sm" style={{ border: `1px solid ${colors.border}` }}
                 data-testid="card-name" />
          <input placeholder="Slug (URL)" value={form.slug} onChange={(e) => setForm({ ...form, slug: e.target.value })}
                 className="px-3 py-2 rounded-lg text-sm" style={{ border: `1px solid ${colors.border}` }}
                 data-testid="card-slug" />
          <input placeholder="Title" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })}
                 className="px-3 py-2 rounded-lg text-sm" style={{ border: `1px solid ${colors.border}` }} />
          <input placeholder="Phone" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })}
                 className="px-3 py-2 rounded-lg text-sm" style={{ border: `1px solid ${colors.border}` }} />
          <input placeholder="Email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })}
                 className="px-3 py-2 rounded-lg text-sm" style={{ border: `1px solid ${colors.border}` }} />
          <input placeholder="Website" value={form.website} onChange={(e) => setForm({ ...form, website: e.target.value })}
                 className="px-3 py-2 rounded-lg text-sm" style={{ border: `1px solid ${colors.border}` }} />
          <label className="flex items-center gap-2 text-sm">Brand color <input type="color" value={form.brand_color} onChange={(e) => setForm({ ...form, brand_color: e.target.value })} /></label>
        </div>
        <button onClick={save} className="mt-3 px-4 py-2 rounded-xl text-sm font-semibold text-white" style={{ backgroundColor: colors.brand }} data-testid="card-save">Save card</button>
      </Card>

      <Card>
        <div className="text-sm font-bold mb-3">Existing cards</div>
        {rows.length === 0 && <div className="text-sm" style={{ color: colors.onSurfaceSecondary }}>None yet.</div>}
        {rows.map((c) => (
          <div key={c.slug} className="py-2 border-b last:border-0 flex items-center justify-between" style={{ borderColor: colors.border }} data-testid={`card-row-${c.slug}`}>
            <div>
              <div className="font-semibold text-sm">{c.name}</div>
              <div className="text-xs" style={{ color: colors.onSurfaceSecondary }}>{c.title || "—"} · {c.phone}</div>
            </div>
            <div className="flex gap-3 text-xs font-semibold">
              <a href={`/public/card/${c.slug}`} target="_blank" rel="noreferrer" style={{ color: colors.brand }}>Public →</a>
              <a href={`${BASE}/api/public/cards/${c.slug}/vcard`} style={{ color: colors.brandSecondary }}>.vcf</a>
            </div>
          </div>
        ))}
      </Card>
      <Toast text={toast} />
    </div>
  );
}

export function PublicCard() {
  const { slug } = useParams();
  const [card, setCard] = useState(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    fetch(`${BASE}/api/public/cards/${slug}`).then((r) => r.ok ? r.json() : Promise.reject(r.status))
      .then(setCard).catch(() => setErr("Card not found"));
  }, [slug]);
  if (err) return <div className="min-h-screen flex items-center justify-center text-sm" style={{ color: colors.onSurfaceSecondary }}>{err}</div>;
  if (!card) return <div className="min-h-screen flex items-center justify-center text-sm" style={{ color: colors.onSurfaceSecondary }}>Loading…</div>;
  const brand = card.brand_color || "#0284C7";
  const qr = `https://api.qrserver.com/v1/create-qr-code/?size=180x180&data=${encodeURIComponent(window.location.href)}`;
  return (
    <div className="min-h-screen flex items-center justify-center p-4" style={{ background: `linear-gradient(135deg, ${brand}22 0%, #fff 100%)` }} data-testid="public-card">
      <div className="max-w-sm w-full bg-white rounded-3xl shadow-xl overflow-hidden">
        <div className="h-32" style={{ backgroundColor: brand }} />
        <div className="px-6 pb-6 -mt-16 text-center">
          {card.photo_url && <img alt="me" src={card.photo_url} className="w-32 h-32 rounded-full mx-auto border-4 border-white object-cover" />}
          <div className="mt-2 text-2xl font-bold">{card.name}</div>
          <div className="text-sm" style={{ color: colors.onSurfaceSecondary }}>{card.title}</div>
          <div className="text-xs mt-1" style={{ color: colors.onSurfaceSecondary }}>{card.company_name}</div>
          <div className="mt-4 space-y-2">
            {card.phone && <a href={`tel:${card.phone}`} className="block py-2 rounded-xl text-sm font-semibold text-white" style={{ backgroundColor: brand }} data-testid="public-card-call">📞 Call {card.phone}</a>}
            {card.email && <a href={`mailto:${card.email}`} className="block py-2 rounded-xl text-sm font-semibold" style={{ backgroundColor: colors.surfaceSecondary }} data-testid="public-card-email">✉️ {card.email}</a>}
            {card.website && <a href={card.website} target="_blank" rel="noreferrer" className="block py-2 rounded-xl text-sm font-semibold" style={{ backgroundColor: colors.surfaceSecondary }}>🌐 Website</a>}
            <a href={`${BASE}/api/public/cards/${slug}/vcard`} className="block py-2 rounded-xl text-sm font-semibold" style={{ backgroundColor: colors.brandSecondary, color: "#fff" }} data-testid="public-card-vcf">💾 Save to contacts (.vcf)</a>
          </div>
          <img alt="qr" src={qr} className="mx-auto mt-4" />
        </div>
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════
   6. Weather
   ═══════════════════════════════════════════════════════════════════ */
export function WeatherHub() {
  const [risk, setRisk] = useState(null);
  const [recs, setRecs] = useState(null);
  useEffect(() => {
    api.get("/weather/risk?lat=33.7897&lng=-112.3226&days=7").then(setRisk).catch(() => setRisk({ days: [] }));
    api.get("/weather/reschedule-recommendations").then(setRecs).catch(() => setRecs({ suggested: [] }));
  }, []);
  const badge = (rating) => ({ good: "#DCFCE7", fair: "#FEF3C7", poor: "#FEE2E2" }[rating] || "#F4F4F5");
  const fg = (rating) => ({ good: "#166534", fair: "#854D0E", poor: "#991B1B" }[rating] || "#52525B");

  return (
    <div className="p-4 md:p-8 max-w-5xl mx-auto space-y-4" data-testid="weather-page">
      <h1 className="text-3xl font-bold">Weather</h1>
      <p className="text-sm" style={{ color: colors.onSurfaceSecondary }}>7-day forecast for Vistancia · Pool-service risk score computed per day.</p>

      <Card>
        {!risk && <div className="text-sm" style={{ color: colors.onSurfaceSecondary }}>Loading…</div>}
        {risk && (
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-2">
            {risk.days.map((d) => (
              <div key={d.date} className="rounded-xl p-3 text-center" style={{ backgroundColor: badge(d.service_risk_rating), color: fg(d.service_risk_rating) }} data-testid={`weather-day-${d.date}`}>
                <div className="text-xs font-semibold">{d.date.slice(5)}</div>
                <div className="text-lg font-bold mt-1">{d.high}°/{d.low}°</div>
                <div className="text-xs mt-1">💧 {d.precip}%</div>
                <div className="text-xs">💨 {Math.round(d.wind_mph)} mph</div>
                <div className="text-[10px] font-bold uppercase mt-1">{d.service_risk_rating}</div>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card testid="weather-reschedule">
        <div className="text-sm font-bold mb-2">Reschedule recommendations</div>
        {!recs && <div className="text-sm" style={{ color: colors.onSurfaceSecondary }}>Loading…</div>}
        {recs && recs.suggested?.length === 0 && (
          <div className="text-sm" style={{ color: colors.onSurfaceSecondary }}>
            No poor-weather days in the next 3 days. 🎉
          </div>
        )}
        {recs && recs.suggested?.length > 0 && (
          <>
            <div className="text-xs mb-2" style={{ color: colors.onSurfaceSecondary }}>
              Poor days: {recs.poor_days.join(", ")}
            </div>
            {recs.suggested.slice(0, 10).map((j) => (
              <div key={j.id} className="py-2 border-b last:border-0 text-sm" style={{ borderColor: colors.border }}>
                <div className="font-semibold">{j.title || "Job"}</div>
                <div className="text-xs" style={{ color: colors.onSurfaceSecondary }}>{j.customer_name} · {(j.scheduled_date || "").slice(0, 10)} · {j.technician_name || "unassigned"}</div>
              </div>
            ))}
          </>
        )}
      </Card>
    </div>
  );
}

export function WeatherWidget() {
  const [risk, setRisk] = useState(null);
  useEffect(() => {
    api.get("/weather/risk?lat=33.7897&lng=-112.3226&days=2").then(setRisk).catch(() => {});
  }, []);
  if (!risk?.days?.length) return null;
  const tomorrow = risk.days[1] || risk.days[0];
  const bg = { good: "#DCFCE7", fair: "#FEF3C7", poor: "#FEE2E2" }[tomorrow.service_risk_rating] || "#F4F4F5";
  return (
    <div className="rounded-2xl p-4" style={{ backgroundColor: bg }} data-testid="weather-widget">
      <div className="text-xs font-semibold uppercase tracking-wider">Tomorrow · {tomorrow.date.slice(5)}</div>
      <div className="text-2xl font-bold mt-1">{tomorrow.high}° / {tomorrow.low}°</div>
      <div className="text-xs">💧 {tomorrow.precip}% · 💨 {Math.round(tomorrow.wind_mph)} mph</div>
      <div className="text-xs font-bold uppercase mt-1">Service: {tomorrow.service_risk_rating}</div>
      {tomorrow.risk_reasons?.length > 0 && (
        <div className="text-xs mt-1">{tomorrow.risk_reasons.slice(0, 2).join(" · ")}</div>
      )}
    </div>
  );
}
