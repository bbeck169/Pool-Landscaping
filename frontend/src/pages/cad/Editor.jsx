import React, { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "@/api";
import { colors } from "@/theme";
import { useIsNarrow } from "@/hooks/useIsNarrow";

/* ═══════════════════════════════════════════════════════════════════
   CAD Studio — Editor surface.

   Extracted verbatim from ``pages/aitools/AiToolsPages.jsx`` as its
   own module so Phase CAD-1 can bolt map-backdrop + scale tooling
   on top without churning the shared AI-tools module. This is the
   refactor-only checkpoint — behavior + testids are identical to
   the inline copy that used to live in ``AiToolsPages.jsx``.
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
];


export default function CadEditor() {
  const { id } = useParams();
  const [design, setDesign] = useState(null);
  const [tool, setTool] = useState("pointer");
  const [_dragging, _setDragging] = useState(null);
  const [toast, setToast] = useState("");
  const canvasRef = useRef(null);
  // Phase Hygiene B · Feb-2026 — mobile guard for the drawing surface
  // migrated from an inline ``window.innerWidth < 768`` check (which
  // was single-shot on render and never re-evaluated on orientation
  // change / DevTools breakpoint swap) to the shared ``useIsNarrow``
  // hook. Same 768px threshold, now backed by matchMedia so a rotate
  // out of portrait immediately reveals the desktop editor.
  const isNarrow = useIsNarrow(768);

  useEffect(() => {
    if (!id) return;
    api.get(`/designs/${id}`).then(setDesign).catch(() => setToast("Failed to load"));
  }, [id]);

  const canvasSize = { w: 800, h: 500 };
  const _scale = design ? (canvasSize.w / (design.canvas_w_ft || 60)) : 12;

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
