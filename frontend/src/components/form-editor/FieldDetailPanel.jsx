// Phase 7B · Feb-2026 — Per-field style editor (right panel).
//
// Phase 7A locked the on-the-wire validation: hex ``#RRGGBB``,
// ``width_cols`` 1..12, ``padding_y`` 1..8, ``bg_alpha`` 0.0..1.0.
// These controls stay BELOW those bounds client-side so a save round
// trip never produces a 400 from style drift.
//
// Color pickers use the native ``<input type="color">`` + a native
// range slider for alpha — brief said "if the app already has a
// color-picker, use that", app currently has none; the native
// controls are universally supported and add zero npm surface.  The
// alpha swatch sits over a checkered-background PNG mimic so the
// composed result is readable against both light + dark grounds.
import React, { useCallback } from "react";
import { colors } from "@/theme";


const CHECKER_BG =
  // 8×8 repeating checker — small inline SVG, no asset round-trip.
  "url(\"data:image/svg+xml;utf8,"
  + "<svg xmlns='http://www.w3.org/2000/svg' width='16' height='16'>"
  + "<rect width='8' height='8' fill='%23E5E7EB'/>"
  + "<rect x='8' y='8' width='8' height='8' fill='%23E5E7EB'/>"
  + "<rect x='8' width='8' height='8' fill='%23FFFFFF'/>"
  + "<rect y='8' width='8' height='8' fill='%23FFFFFF'/>"
  + "</svg>\")";


function _normalizeHex(v, fallback) {
  if (typeof v !== "string") return fallback;
  const s = v.trim();
  if (/^#[0-9A-Fa-f]{6}$/.test(s)) return s;
  return fallback;
}


function ColorRow({ label, value, onChange, testid, fallback = "#FFFFFF" }) {
  const current = _normalizeHex(value, fallback);
  return (
    <label className="flex items-center justify-between gap-3 py-1.5">
      <span className="text-xs font-semibold uppercase tracking-wide"
            style={{ color: colors.onSurfaceSecondary || "#52525B" }}>
        {label}
      </span>
      <span className="flex items-center gap-2">
        <input
          type="color"
          value={current}
          onChange={(e) => onChange(e.target.value)}
          className="w-10 h-7 rounded border p-0 cursor-pointer"
          data-testid={testid}
        />
        <code className="text-xs text-slate-600 w-16 text-right">
          {current.toUpperCase()}
        </code>
      </span>
    </label>
  );
}


function SliderRow({
  label, value, min, max, step, onChange, testid, suffix,
}) {
  return (
    <label className="flex items-center justify-between gap-3 py-1.5">
      <span className="text-xs font-semibold uppercase tracking-wide"
            style={{ color: colors.onSurfaceSecondary || "#52525B" }}>
        {label}
      </span>
      <span className="flex items-center gap-2 flex-1 justify-end">
        <input
          type="range"
          min={min} max={max} step={step}
          value={value}
          onChange={(e) => onChange(Number(e.target.value))}
          className="w-40"
          data-testid={testid}
        />
        <code className="text-xs text-slate-600 w-14 text-right">
          {value}{suffix || ""}
        </code>
      </span>
    </label>
  );
}


function ColumnSpanPreview({ width }) {
  // 12-col strip visualising ``width_cols`` — small sanity preview
  // that the admin's slider position matches "what the grid will
  // actually render" so there's no surprise when they save.
  const cells = Array.from({ length: 12 }, (_, i) => i < width);
  return (
    <div className="grid grid-cols-12 gap-0.5 py-1"
         data-testid="field-detail-column-preview">
      {cells.map((on, i) => (
        <span
          key={i}
          className="h-2 rounded"
          style={{ background: on ? "#0284C7" : "#E4E4E7" }}
        />
      ))}
    </div>
  );
}


export default function FieldDetailPanel({
  field, onChange, readOnly,
}) {
  const change = useCallback((patch) => {
    if (readOnly) return;
    onChange(field.field_id, patch);
  }, [field, onChange, readOnly]);

  const style  = field.style || {};
  const bgCol  = _normalizeHex(style.bg_color,     "#FFFFFF");
  const txtCol = _normalizeHex(style.text_color,   "#111827");
  const brdCol = _normalizeHex(style.border_color, "#E5E7EB");
  const alpha  = typeof style.bg_alpha === "number" ? style.bg_alpha : 1;
  const width  = Number(style.width_cols || 12);
  const pad    = Number(style.padding_y   || 2);

  return (
    <aside
      className="rounded-lg border bg-white p-4 flex flex-col gap-2"
      data-testid="field-detail-panel"
    >
      <header className="flex items-center justify-between pb-2 border-b">
        <div>
          <div className="font-semibold" style={{ color: colors.onSurface }}>
            {field.label}
          </div>
          <div className="text-xs text-slate-500">
            {field.field_id} · {field.field_type}
          </div>
        </div>
        {field.locked_reorder ? (
          <span
            className="text-[10px] uppercase font-bold px-1.5 py-0.5 rounded-full"
            style={{ background: "#FEF3C7", color: "#92400E" }}
            data-testid="field-detail-locked-badge"
          >Locked</span>
        ) : null}
      </header>

      {/* Alpha-composed swatch — the "what the admin will see" preview. */}
      <div className="rounded border p-3"
           style={{
             backgroundImage: CHECKER_BG,
             backgroundSize: "16px 16px",
           }}
           data-testid="field-detail-swatch-wrap">
        <div
          className="h-14 rounded border flex items-center justify-center text-xs font-mono"
          style={{
            background:   bgCol,
            opacity:      alpha,
            color:        txtCol,
            borderColor:  brdCol,
          }}
          data-testid="field-detail-swatch"
        >
          Sample · {bgCol} @ {Math.round(alpha * 100)}%
        </div>
      </div>

      <ColorRow
        label="Background"
        value={bgCol}
        fallback="#FFFFFF"
        onChange={(v) => change({ style: { bg_color: v } })}
        testid="field-detail-bg-color"
      />
      <SliderRow
        label="Bg Alpha"
        value={alpha} min={0} max={1} step={0.05}
        suffix=""
        onChange={(v) => change({ style: { bg_alpha: v } })}
        testid="field-detail-bg-alpha"
      />
      <ColorRow
        label="Text"
        value={txtCol}
        fallback="#111827"
        onChange={(v) => change({ style: { text_color: v } })}
        testid="field-detail-text-color"
      />
      <ColorRow
        label="Border"
        value={brdCol}
        fallback="#E5E7EB"
        onChange={(v) => change({ style: { border_color: v } })}
        testid="field-detail-border-color"
      />
      <SliderRow
        label="Width (cols)"
        value={width} min={1} max={12} step={1}
        suffix="/12"
        onChange={(v) => change({ style: { width_cols: v } })}
        testid="field-detail-width-cols"
      />
      <ColumnSpanPreview width={width} />
      <SliderRow
        label="Padding Y"
        value={pad} min={1} max={8} step={1}
        suffix=""
        onChange={(v) => change({ style: { padding_y: v } })}
        testid="field-detail-padding-y"
      />
    </aside>
  );
}
