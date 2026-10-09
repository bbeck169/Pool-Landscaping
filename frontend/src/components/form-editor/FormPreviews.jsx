// Phase 7B · Feb-2026 — Form Template preview mocks.
//
// Three preview variants exported from one file (scope ceiling):
//   * ServiceReportPreview     — pool/landscape SR + job_checklist_*
//   * InvoiceEstimatePreview   — estimate + invoice
//   * CadOverlayPreview        — cad_overlay (SVG grid mock)
//
// CRITICAL (brief §5): the estimate / invoice ``line_items_table``
// MUST honor the editor's styles.  Pre-Phase-7A those columns were
// renderer-locked to white; Phase 7B unlocks them in the preview
// surface so the admin sees exactly what Phase 7C will render.
//
// NONE of these components talk to the real form renderers.  Phase
// 7C will wire the saved template into the real pages; this file
// only renders a mock using the in-memory draft the editor owns.
import React from "react";
// Phase 7C · Feb-2026 — unify style mapping with the real-form
// renderers.  Pre-7C this file had its own ``_styleOf`` that
// duplicated the (bg_color, bg_alpha) → rgba composition.  The
// shared ``styleToCss`` helper is now the single source of truth
// so the editor preview can never drift from what the live form
// will actually paint.
import { styleToCss, PADDING_Y_MULTIPLIER_PX } from "@/lib/formStyle";


// ─── helpers ──────────────────────────────────────────────────────

function _styleOf(field) {
  const s = field?.style || {};
  const widthCols = Number(s.width_cols || 12);
  const paddingY  = Number(s.padding_y  || 2);
  const base = styleToCss(s);
  return {
    // Preserve the pre-7C local shape so the preview sub-components
    // can keep reading ``bgCol``, ``alpha``, etc. for their swatch
    // overlays.  All CSS values come from the shared helper.
    bgCol:   typeof s.bg_color   === "string" ? s.bg_color   : "#FFFFFF",
    txtCol:  typeof s.text_color === "string" ? s.text_color : "#111827",
    brdCol:  typeof s.border_color === "string" ? s.border_color : "#E5E7EB",
    alpha:   typeof s.bg_alpha   === "number" ? s.bg_alpha   : 1,
    widthCols,
    paddingY,
    css: {
      background:    base.backgroundColor,
      color:         base.color,
      borderColor:   base.borderColor,
      paddingTop:    base.paddingTop,
      paddingBottom: base.paddingBottom,
    },
    colSpan: base.gridColumn,
  };
}


function FieldShell({ field, children }) {
  const s = _styleOf(field);
  return (
    <div
      className="border rounded px-3"
      style={{ ...s.css, gridColumn: s.colSpan }}
      data-testid={`preview-field-${field.field_id}`}
    >
      <div className="text-[10px] uppercase font-bold tracking-wide opacity-60">
        {field.label}
      </div>
      {children}
    </div>
  );
}


// ─── Service Report / Checklist preview ───────────────────────────
//
// Lightweight mock of a form card — labels + stylised input shells
// in a 12-col grid.
export function ServiceReportPreview({ fields }) {
  return (
    <div
      className="grid grid-cols-12 gap-2"
      data-testid="preview-service-report"
    >
      {fields.map((f) => (
        <FieldShell key={f.field_id} field={f}>
          <div className="text-xs mt-1">
            {f.field_type === "checkbox" ? (
              <label className="flex items-center gap-2">
                <input type="checkbox" readOnly />
                <span>Mock input</span>
              </label>
            ) : f.field_type === "signature" ? (
              <div className="h-6 border-b italic text-slate-400">
                [signature area]
              </div>
            ) : f.field_type === "photo" ? (
              <div className="h-6 italic text-slate-400">[photo picker]</div>
            ) : (
              <div className="h-6 italic text-slate-400">[input]</div>
            )}
          </div>
        </FieldShell>
      ))}
    </div>
  );
}


// ─── Estimate / Invoice preview ───────────────────────────────────
//
// Renders a mock line-items table + totals row.  The ``line_items_table``
// field's own style drives the table body cells (NOT a hardcoded white)
// — this is the "billable/payment unlock" called out in the brief.
export function InvoiceEstimatePreview({ fields, formType }) {
  const findField = (id) => fields.find((f) => f.field_id === id);
  const liField   = findField("line_items_table");
  const liStyle   = liField ? _styleOf(liField) : null;

  const liCellStyle = liStyle ? {
    background:  liStyle.bgCol,
    opacity:     liStyle.alpha,
    color:       liStyle.txtCol,
    borderColor: liStyle.brdCol,
  } : {};

  return (
    <div
      className="flex flex-col gap-3"
      data-testid={`preview-${formType || "invoice-estimate"}`}
    >
      {/* Header + top-level fields rendered in-grid, line_items_table
          handled separately so the table itself can honor the field
          style.  Totals row (subtotal / taxes / total) rendered after
          the table so it visually matches the real estimate / invoice
          layout. */}
      <div className="grid grid-cols-12 gap-2">
        {fields
          .filter((f) => !["line_items_table", "subtotal", "taxes",
                            "total", "total_due", "payment_status"]
                            .includes(f.field_id))
          .map((f) => (
            <FieldShell key={f.field_id} field={f}>
              <div className="h-6 italic text-slate-400">[input]</div>
            </FieldShell>
          ))}
      </div>

      {liField ? (
        <div
          className="rounded overflow-hidden border"
          style={{ borderColor: liStyle.brdCol }}
          data-testid="preview-line-items-table"
        >
          <table className="w-full text-xs">
            <thead>
              <tr style={{ ...liCellStyle, fontWeight: 600 }}>
                <th className="px-2 py-1 text-left"
                    data-testid="preview-li-col-item">Item</th>
                <th className="px-2 py-1 text-right"
                    data-testid="preview-li-col-qty">Qty / Hr</th>
                <th className="px-2 py-1 text-right"
                    data-testid="preview-li-col-unit">Unit</th>
                <th className="px-2 py-1 text-right"
                    data-testid="preview-li-col-total">Total</th>
              </tr>
            </thead>
            <tbody>
              <tr style={liCellStyle} data-testid="preview-li-row-1">
                <td className="px-2 py-1">Weekly Pool Service</td>
                <td className="px-2 py-1 text-right">4</td>
                <td className="px-2 py-1 text-right">$45.00</td>
                <td className="px-2 py-1 text-right">$180.00</td>
              </tr>
              <tr style={liCellStyle} data-testid="preview-li-row-2">
                <td className="px-2 py-1">Chlorine</td>
                <td className="px-2 py-1 text-right">2</td>
                <td className="px-2 py-1 text-right">$18.50</td>
                <td className="px-2 py-1 text-right">$37.00</td>
              </tr>
            </tbody>
          </table>
        </div>
      ) : null}

      {/* Totals row — 4 / 4 / 4 columns per Phase 7A seed. */}
      <div className="grid grid-cols-12 gap-2">
        {["subtotal", "taxes", "total", "total_due", "payment_status"]
          .map((id) => findField(id))
          .filter(Boolean)
          .map((f) => (
            <FieldShell key={f.field_id} field={f}>
              <div className="h-6 italic text-slate-400">
                {f.field_type === "currency" ? "$0.00" : "[field]"}
              </div>
            </FieldShell>
          ))}
      </div>
    </div>
  );
}


// ─── CAD Overlay preview ──────────────────────────────────────────
//
// The real CAD editor is a canvas tool — this preview is a STATIC
// SVG grid mock, flagged in the brief.  Shows the configured bg +
// grid opacity + snap-grid cell size so an admin can preview how
// their overlay changes feel without hooking the real canvas.
export function CadOverlayPreview({ fields }) {
  const bg = fields.find((f) => f.field_id === "overlay_bg");
  const op = fields.find((f) => f.field_id === "grid_opacity");
  const sz = fields.find((f) => f.field_id === "snap_grid_size");
  const bgStyle = _styleOf(bg || {});
  const gridOpacity = Math.max(0, Math.min(1,
    (Number(op?.style?.bg_alpha) || 0.5)));
  // ``snap_grid_size`` is a numeric field without a real stored value
  // here — Phase 7B uses ``width_cols`` as the proxy for the mock
  // cell size (admins get a visual sanity check).
  const cell = Math.max(4, Math.min(32,
    Number(sz?.style?.width_cols || 8) * 2));

  const lines = [];
  for (let x = 0; x <= 160; x += cell) {
    lines.push(
      <line key={`v-${x}`} x1={x} y1={0} x2={x} y2={96}
            stroke="#0284C7" strokeOpacity={gridOpacity} strokeWidth={0.5} />,
    );
  }
  for (let y = 0; y <= 96; y += cell) {
    lines.push(
      <line key={`h-${y}`} x1={0} y1={y} x2={160} y2={y}
            stroke="#0284C7" strokeOpacity={gridOpacity} strokeWidth={0.5} />,
    );
  }

  return (
    <div
      className="rounded border overflow-hidden"
      style={{ background: bgStyle.bgCol, borderColor: bgStyle.brdCol }}
      data-testid="preview-cad-overlay"
    >
      <svg viewBox="0 0 160 96" width="100%" height="200"
           data-testid="preview-cad-overlay-svg">
        <rect width="160" height="96" fill={bgStyle.bgCol}
              fillOpacity={bgStyle.alpha} />
        {lines}
      </svg>
      <div className="text-[10px] px-2 py-1 text-slate-500">
        Phase 7A placeholder — real CAD canvas hooked in Phase 7B+C.
        <span data-testid="preview-cad-grid-opacity"
              className="ml-1">opacity={gridOpacity.toFixed(2)}</span>
        <span data-testid="preview-cad-cell-size"
              className="ml-1">cell={cell}px</span>
      </div>
    </div>
  );
}
