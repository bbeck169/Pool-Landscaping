import React from "react";
import { Plus, Trash2 } from "lucide-react";
import { colors } from "@/theme";

/**
 * Renderer for a `table` field type.
 *
 * A table field's `columns` schema is a list of `{key, label, type?}`
 * objects. Supported cell types: text (default), number, date, checkbox.
 * The value stored in the instance is a list of row objects keyed by
 * column key.
 */
export default function TemplateTableField({ field, value, onChange, disabled = false }) {
  const cols = Array.isArray(field.columns) ? field.columns : [];
  const rows = Array.isArray(value) ? value : [];

  const setRow = (idx, patch) => {
    const next = rows.map((r, i) => (i === idx ? { ...r, ...patch } : r));
    onChange(next);
  };

  const addRow = () => onChange([...rows, {}]);
  const delRow = (idx) => onChange(rows.filter((_, i) => i !== idx));

  return (
    <div
      className="rounded-xl overflow-x-auto"
      style={{ border: `1px solid ${colors.border}` }}
      data-testid={`template-table-${field.key}`}
    >
      <table className="w-full text-sm">
        <thead>
          <tr style={{ backgroundColor: colors.surfaceSecondary }}>
            {cols.map((c) => (
              <th
                key={c.key}
                className="px-2 py-2 text-left text-[11px] font-bold uppercase tracking-wider"
                style={{ color: colors.onSurfaceSecondary, borderBottom: `1px solid ${colors.border}` }}
              >
                {c.label || c.key}
              </th>
            ))}
            {!disabled && <th style={{ width: 40, borderBottom: `1px solid ${colors.border}` }} />}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && (
            <tr>
              <td
                colSpan={cols.length + (disabled ? 0 : 1)}
                className="px-2 py-4 text-center text-xs"
                style={{ color: colors.muted }}
              >
                No rows yet.
              </td>
            </tr>
          )}
          {rows.map((row, ri) => (
            <tr key={ri} data-testid={`template-table-${field.key}-row-${ri}`}>
              {cols.map((c) => {
                const ct = c.type || "text";
                const val = row?.[c.key];
                if (ct === "checkbox") {
                  return (
                    <td key={c.key} className="px-2 py-1.5" style={{ borderBottom: `1px solid ${colors.border}` }}>
                      <input
                        type="checkbox"
                        checked={!!val}
                        disabled={disabled}
                        onChange={(e) => setRow(ri, { [c.key]: e.target.checked })}
                        data-testid={`template-table-${field.key}-cell-${ri}-${c.key}`}
                      />
                    </td>
                  );
                }
                const inputType = ct === "number" ? "number" : ct === "date" ? "date" : "text";
                return (
                  <td key={c.key} className="px-2 py-1.5" style={{ borderBottom: `1px solid ${colors.border}` }}>
                    <input
                      type={inputType}
                      value={val ?? ""}
                      disabled={disabled}
                      onChange={(e) => {
                        const v = inputType === "number"
                          ? (e.target.value === "" ? "" : Number(e.target.value))
                          : e.target.value;
                        setRow(ri, { [c.key]: v });
                      }}
                      className="w-full px-2 py-1 text-sm rounded"
                      style={{ border: `1px solid ${colors.border}`, backgroundColor: disabled ? colors.surfaceSecondary : "#fff" }}
                      data-testid={`template-table-${field.key}-cell-${ri}-${c.key}`}
                    />
                  </td>
                );
              })}
              {!disabled && (
                <td className="px-2 py-1.5 text-right" style={{ borderBottom: `1px solid ${colors.border}` }}>
                  <button
                    onClick={() => delRow(ri)}
                    className="p-1 rounded hover:bg-red-50"
                    style={{ color: colors.error }}
                    data-testid={`template-table-${field.key}-del-${ri}`}
                    aria-label="Delete row"
                  >
                    <Trash2 size={14} />
                  </button>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
      {!disabled && (
        <div className="p-2" style={{ borderTop: `1px solid ${colors.border}` }}>
          <button
            onClick={addRow}
            className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-bold"
            style={{ backgroundColor: colors.brandTertiary, color: colors.brand }}
            data-testid={`template-table-${field.key}-add`}
          >
            <Plus size={13} /> Add row
          </button>
        </div>
      )}
    </div>
  );
}
