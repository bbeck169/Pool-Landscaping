import React, { useState } from "react";
import { PenLine, Check, RefreshCw } from "lucide-react";
import { colors } from "@/theme";
import TemplateTableField from "@/components/templates/TemplateTableField";
import SignaturePadModal from "@/components/templates/SignaturePadModal";

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
    // Signature has its own subcomponent so we can host useState for the
    // modal open/close without lifting into the parent field renderer.
    return (
      <SignatureField
        field={field}
        value={value}
        onChange={onChange}
        disabled={disabled}
        currentUserName={currentUserName}
        commonInputStyle={commonInputStyle}
        testIdBase={testIdBase}
      />
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


function formatSignedAt(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    return d.toLocaleString();
  } catch {
    return iso;
  }
}

function SignatureField({ field, value, onChange, disabled, currentUserName, testIdBase }) {
  const [padOpen, setPadOpen] = useState(false);

  const sig = value && typeof value === "object" ? value : null;
  // Phase 4 shape: {image_data_url, signer_name, signed_at}
  // Legacy Phase 2 stamp shape: {name, date}
  const signerName = sig?.signer_name || sig?.name || null;
  const signedAt = sig?.signed_at || sig?.date || null;
  const imageDataUrl = sig?.image_data_url || null;
  const hasSignature = Boolean(signerName);

  const Label = () => (
    <label className="block text-xs font-bold mb-1" style={{ color: colors.onSurfaceSecondary }}>
      {field.label}
      {field.required && <span className="ml-1" style={{ color: colors.error }}>*</span>}
    </label>
  );

  return (
    <div data-testid={testIdBase}>
      <Label />
      {hasSignature ? (
        <div
          className="flex items-start justify-between gap-3 px-3 py-3 rounded-lg"
          style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}` }}
        >
          <div className="flex items-start gap-3">
            {imageDataUrl ? (
              <img
                src={imageDataUrl}
                alt={`Signature by ${signerName}`}
                className="rounded bg-white"
                style={{ maxWidth: 200, maxHeight: 80, border: `1px solid ${colors.border}` }}
                data-testid={`${testIdBase}-image`}
              />
            ) : (
              <Check size={16} style={{ color: colors.success, marginTop: 2 }} />
            )}
            <div>
              <div className="text-sm font-bold" style={{ color: colors.onSurface }}>
                Signed by {signerName}
              </div>
              <div className="text-[11px]" style={{ color: colors.muted }}>
                {formatSignedAt(signedAt)}
              </div>
            </div>
          </div>
          {!disabled && (
            <div className="flex flex-col gap-1">
              <button
                onClick={() => setPadOpen(true)}
                className="inline-flex items-center gap-1 text-xs font-semibold"
                style={{ color: colors.brand }}
                data-testid={`${testIdBase}-resign`}
              >
                <RefreshCw size={12} /> Re-sign
              </button>
              <button
                onClick={() => onChange(null)}
                className="text-xs font-semibold text-left"
                style={{ color: colors.error }}
                data-testid={`${testIdBase}-clear`}
              >
                Clear
              </button>
            </div>
          )}
        </div>
      ) : (
        <button
          onClick={() => !disabled && setPadOpen(true)}
          disabled={disabled}
          className="inline-flex items-center gap-1 px-3 py-2 rounded-lg text-sm font-bold disabled:opacity-60"
          style={{ backgroundColor: colors.brandTertiary, color: colors.brand, border: `1px solid ${colors.border}` }}
          data-testid={`${testIdBase}-sign`}
        >
          <PenLine size={14} /> Sign
        </button>
      )}

      {field.help_text && (
        <p className="text-[11px] mt-1" style={{ color: colors.muted }}>{field.help_text}</p>
      )}

      <SignaturePadModal
        open={padOpen}
        onClose={() => setPadOpen(false)}
        defaultSignerName={signerName || currentUserName || ""}
        fieldLabel={field.label}
        onSave={(payload) => {
          onChange(payload);
          setPadOpen(false);
        }}
      />
    </div>
  );
}
