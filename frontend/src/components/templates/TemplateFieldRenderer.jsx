import React from "react";
import { PenLine, Check } from "lucide-react";
import { colors } from "@/theme";
import TemplateTableField from "@/components/templates/TemplateTableField";

/**
 * Renders every field type the backend ships in a template schema:
 *   header, text, long_text, number, date, checkbox, select,
 *   signature, table.
 *
 * `signature` in this phase is a "stamp" — click to record the current
 * user's name + ISO timestamp. Phase 4 will add a drawing pad.
 */
export default function TemplateFieldRenderer({ field, value, onChange, disabled = false, currentUserName = "" }) {
  const { type, key, label, help_text, required, options, min, max } = field;
  const testIdBase = `template-field-${key || label || type}`;

  const commonInputStyle = {
    border: `1px solid ${colors.border}`,
    backgroundColor: disabled ? colors.surfaceSecondary : "#fff",
  };

  if (type === "header") {
    return (
      <div className="mt-2" data-testid={testIdBase}>
        <div className="text-sm font-bold" style={{ color: colors.onSurface }}>
          {label}
        </div>
        {help_text && (
          <p className="text-xs mt-0.5" style={{ color: colors.muted }}>{help_text}</p>
        )}
      </div>
    );
  }

  const Label = () => (
    <label className="block text-xs font-bold mb-1" style={{ color: colors.onSurfaceSecondary }}>
      {label}
      {required && <span className="ml-1" style={{ color: colors.error }}>*</span>}
    </label>
  );

  const Help = () => help_text ? (
    <p className="text-[11px] mt-1" style={{ color: colors.muted }}>{help_text}</p>
  ) : null;

  if (type === "text") {
    return (
      <div data-testid={testIdBase}>
        <Label />
        <input
          type="text"
          value={value ?? ""}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
          className="w-full px-3 py-2 rounded-lg text-sm"
          style={commonInputStyle}
          data-testid={`${testIdBase}-input`}
        />
        <Help />
      </div>
    );
  }

  if (type === "long_text") {
    return (
      <div data-testid={testIdBase}>
        <Label />
        <textarea
          rows={4}
          value={value ?? ""}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
          className="w-full px-3 py-2 rounded-lg text-sm"
          style={commonInputStyle}
          data-testid={`${testIdBase}-input`}
        />
        <Help />
      </div>
    );
  }

  if (type === "number") {
    return (
      <div data-testid={testIdBase}>
        <Label />
        <input
          type="number"
          value={value ?? ""}
          min={min ?? undefined}
          max={max ?? undefined}
          disabled={disabled}
          onChange={(e) => {
            const raw = e.target.value;
            onChange(raw === "" ? "" : Number(raw));
          }}
          className="w-full px-3 py-2 rounded-lg text-sm"
          style={commonInputStyle}
          data-testid={`${testIdBase}-input`}
        />
        <Help />
      </div>
    );
  }

  if (type === "date") {
    return (
      <div data-testid={testIdBase}>
        <Label />
        <input
          type="date"
          value={value ?? ""}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
          className="w-full px-3 py-2 rounded-lg text-sm"
          style={commonInputStyle}
          data-testid={`${testIdBase}-input`}
        />
        <Help />
      </div>
    );
  }

  if (type === "checkbox") {
    return (
      <div data-testid={testIdBase} className="flex items-center gap-2">
        <input
          type="checkbox"
          checked={!!value}
          disabled={disabled}
          onChange={(e) => onChange(e.target.checked)}
          className="w-4 h-4"
          data-testid={`${testIdBase}-input`}
        />
        <span className="text-sm" style={{ color: colors.onSurface }}>
          {label}
          {required && <span className="ml-1" style={{ color: colors.error }}>*</span>}
        </span>
        {help_text && (
          <span className="text-[11px] ml-2" style={{ color: colors.muted }}>{help_text}</span>
        )}
      </div>
    );
  }

  if (type === "select") {
    return (
      <div data-testid={testIdBase}>
        <Label />
        <select
          value={value ?? ""}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
          className="w-full px-3 py-2 rounded-lg text-sm"
          style={commonInputStyle}
          data-testid={`${testIdBase}-input`}
        >
          <option value="">— Select —</option>
          {(options || []).map((opt) => (
            <option key={opt} value={opt}>{opt}</option>
          ))}
        </select>
        <Help />
      </div>
    );
  }

  if (type === "signature") {
    const sig = value && typeof value === "object" ? value : null;
    return (
      <div data-testid={testIdBase}>
        <Label />
        {sig?.name ? (
          <div
            className="flex items-center justify-between gap-3 px-3 py-2 rounded-lg text-sm"
            style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}` }}
          >
            <div className="flex items-center gap-2">
              <Check size={16} style={{ color: colors.success }} />
              <div>
                <div className="font-bold" style={{ color: colors.onSurface }}>{sig.name}</div>
                <div className="text-[11px]" style={{ color: colors.muted }}>Signed {sig.date}</div>
              </div>
            </div>
            {!disabled && (
              <button
                onClick={() => onChange(null)}
                className="text-xs font-semibold"
                style={{ color: colors.error }}
                data-testid={`${testIdBase}-clear`}
              >
                Clear
              </button>
            )}
          </div>
        ) : (
          <button
            onClick={() => {
              if (disabled) return;
              onChange({
                name: currentUserName || "Signer",
                date: new Date().toISOString(),
              });
            }}
            disabled={disabled}
            className="inline-flex items-center gap-1 px-3 py-2 rounded-lg text-sm font-bold disabled:opacity-60"
            style={{ backgroundColor: colors.brandTertiary, color: colors.brand, border: `1px solid ${colors.border}` }}
            data-testid={`${testIdBase}-sign`}
          >
            <PenLine size={14} /> Sign as {currentUserName || "me"}
          </button>
        )}
        <Help />
      </div>
    );
  }

  if (type === "table") {
    return (
      <div data-testid={testIdBase}>
        {label && <Label />}
        <TemplateTableField field={field} value={value} onChange={onChange} disabled={disabled} />
        <Help />
      </div>
    );
  }

  // Fallback for unknown types — render as plain text so we never crash.
  return (
    <div data-testid={testIdBase}>
      <Label />
      <input
        type="text"
        value={value ?? ""}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        className="w-full px-3 py-2 rounded-lg text-sm"
        style={commonInputStyle}
        data-testid={`${testIdBase}-input`}
      />
      <div className="text-[11px] mt-1" style={{ color: colors.warning }}>
        Unknown field type: <code>{type}</code>
      </div>
    </div>
  );
}
