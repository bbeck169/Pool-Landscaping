/**
 * Feb-2026 · Multi-body service reports (Phase 2 · web).
 *
 * Compact per-body editor rendered under the primary Pool Wizard when
 * the tech adds an extra body (Spa / Water Feature / Fountain / Other).
 * The primary body (index 0) uses the existing PoolChecklistWizard —
 * this panel only handles the trimmed non-pool shape:
 *
 *   * Reading rows filtered by the body type's allow-list
 *     (`READING_ALLOWLIST` in `lib/waterBodies.js`).
 *   * Chemicals-used rows filtered by the type's chemical allow-list
 *     (`CHEMICAL_ALLOWLIST`).
 *   * Free-text notes textarea.
 *   * Removable via the trash icon in the header. The parent enforces
 *     the "cannot remove the last remaining body" rule.
 *
 * The panel is intentionally simple — it does NOT re-implement the
 * full pool form (analyze-water-photo, AI recommendations, algae
 * observation, etc.). Those are pool-only per the Phase 2 brief.
 */
import React, { useCallback, useMemo, useState } from "react";
import { ChevronDown, ChevronUp, Trash2, AlertTriangle } from "lucide-react";

import {
  BODY_TYPE_LABELS,
  BODY_TYPE_TINTS,
  CHEMICAL_ALLOWLIST,
  CHEMICAL_LABELS,
  READING_ALLOWLIST,
  READING_LABELS,
  READING_REQUIRED,
  WATER_BODY_TYPES,
  missingRequiredReadings,
} from "@/lib/waterBodies";

const c = {
  border: "#E2E8F0", muted: "#64748B",
  surface: "#FFFFFF", surfaceAlt: "#F8FAFC",
  onSurface: "#0F172A", danger: "#DC2626",
  warnBg: "#FEF3C7", warnFg: "#92400E",
  brand: "#0EA5E9",
};


function coerceNumber(raw) {
  if (raw === "" || raw == null) return null;
  const n = Number(raw);
  return Number.isFinite(n) ? n : null;
}


function ReadingRow({ readingKey, current, required, locked, onChange }) {
  const meta = READING_LABELS[readingKey] || {
    name: readingKey.replace(/_/g, " "),
    unit: "",
    short: readingKey,
  };
  const value = current?.value;
  const [draft, setDraft] = useState(
    value === null || value === undefined ? "" : String(value),
  );
  React.useEffect(() => {
    setDraft(value === null || value === undefined ? "" : String(value));
  }, [value]);
  const commit = () => {
    if (locked) return;
    onChange(draft === "" ? null : coerceNumber(draft));
  };
  const missing = required && (draft === "" || draft == null);
  return (
    <div
      className="flex items-center gap-2"
      data-testid={`wb-reading-${readingKey}`}
    >
      <label
        className="text-xs font-medium flex-1"
        style={{ color: c.onSurface }}
      >
        {meta.name}
        {required ? (
          <span style={{ color: c.danger }} aria-hidden="true"> *</span>
        ) : null}
      </label>
      <input
        type="text"
        inputMode="decimal"
        value={draft}
        disabled={locked}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        placeholder={meta.unit || "—"}
        className="w-24 px-2 py-1 text-sm rounded border"
        style={{
          borderColor: missing ? c.danger : c.border,
          background: locked ? c.surfaceAlt : c.surface,
        }}
        data-testid={`wb-reading-input-${readingKey}`}
      />
      <span className="text-[10px] w-10" style={{ color: c.muted }}>
        {meta.unit}
      </span>
    </div>
  );
}


function ChemicalRow({ slug, chem, locked, onChange, onRemove }) {
  const meta = CHEMICAL_LABELS[slug] || { name: slug, unit: "" };
  const qty = chem?.quantity ?? chem?.amount ?? "";
  const [draft, setDraft] = useState(qty === "" || qty == null ? "" : String(qty));
  React.useEffect(() => {
    setDraft(qty === "" || qty == null ? "" : String(qty));
  }, [qty]);
  const commit = () => {
    if (locked) return;
    onChange({
      product_slug: slug,
      slug,
      name: meta.name,
      unit: meta.unit,
      quantity: coerceNumber(draft),
      amount: coerceNumber(draft),
    });
  };
  return (
    <div
      className="flex items-center gap-2"
      data-testid={`wb-chem-${slug}`}
    >
      <label
        className="text-xs font-medium flex-1"
        style={{ color: c.onSurface }}
      >
        {meta.name}
      </label>
      <input
        type="text"
        inputMode="decimal"
        value={draft}
        disabled={locked}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        placeholder="0"
        className="w-20 px-2 py-1 text-sm rounded border"
        style={{
          borderColor: c.border,
          background: locked ? c.surfaceAlt : c.surface,
        }}
        data-testid={`wb-chem-input-${slug}`}
      />
      <span className="text-[10px] w-12" style={{ color: c.muted }}>
        {meta.unit}
      </span>
      {!locked && chem && (chem.quantity || chem.amount) ? (
        <button
          type="button"
          onClick={() => onRemove(slug)}
          className="p-1 rounded"
          style={{ color: c.muted, background: "transparent", border: 0 }}
          aria-label={`Clear ${meta.name}`}
          data-testid={`wb-chem-clear-${slug}`}
        >
          <Trash2 size={12} />
        </button>
      ) : (
        <div style={{ width: 20 }} />
      )}
    </div>
  );
}


export default function WaterBodyPanel({
  body,
  index,
  locked,
  canRemove,
  onChange,
  onRemove,
}) {
  const [open, setOpen] = useState(true);
  const [confirmingRemove, setConfirmingRemove] = useState(false);
  const bodyType = body?.type || "pool";
  const allowedReadings = READING_ALLOWLIST[bodyType] || [];
  const allowedChems = CHEMICAL_ALLOWLIST[bodyType] || [];
  const requiredKeys = READING_REQUIRED[bodyType] || [];
  const requiredSet = useMemo(() => new Set(requiredKeys), [requiredKeys]);
  const tint = BODY_TYPE_TINTS[bodyType] || BODY_TYPE_TINTS.other;
  const label = (body?.label || BODY_TYPE_LABELS[bodyType] || "Body");
  const missingReq = useMemo(() => missingRequiredReadings(body || {}),
                              [body]);

  const readingsByKey = useMemo(() => {
    const m = new Map();
    for (const r of (body?.readings || [])) {
      if (r && r.key) m.set(String(r.key).toLowerCase(), r);
    }
    return m;
  }, [body?.readings]);

  const chemicalsBySlug = useMemo(() => {
    const m = new Map();
    for (const c_ of (body?.chemicals_used || body?.chemicals_added || [])) {
      const slug = String(c_?.product_slug || c_?.slug || "").toLowerCase();
      if (slug) m.set(slug, c_);
    }
    return m;
  }, [body?.chemicals_used, body?.chemicals_added]);

  const updateReading = useCallback((key, value) => {
    const existing = readingsByKey.get(key);
    const meta = READING_LABELS[key] || {};
    const next = (body?.readings || []).filter(
      (r) => String(r?.key || "").toLowerCase() !== key,
    );
    // Preserve the row when the user types 0; drop it only when
    // explicitly cleared to null AND it was never populated.
    if (value !== null || existing) {
      next.push({
        key,
        name: (existing && existing.name) || meta.name || key,
        unit: (existing && existing.unit) || meta.unit || "",
        value,
        ts: existing ? existing.ts : null,
      });
    }
    onChange({ ...body, readings: next });
  }, [body, onChange, readingsByKey]);

  const updateChemical = useCallback((slug, patch) => {
    const next = (body?.chemicals_used || body?.chemicals_added || [])
      .filter((c_) => {
        const s = String(c_?.product_slug || c_?.slug || "").toLowerCase();
        return s !== slug;
      });
    // Drop the row when quantity is null/0 AND not previously set.
    const qty = patch?.quantity ?? patch?.amount;
    if (qty !== null && qty !== 0 && qty !== undefined) {
      next.push(patch);
    }
    onChange({ ...body, chemicals_used: next });
  }, [body, onChange]);

  const clearChemical = useCallback((slug) => {
    const next = (body?.chemicals_used || body?.chemicals_added || [])
      .filter((c_) => {
        const s = String(c_?.product_slug || c_?.slug || "").toLowerCase();
        return s !== slug;
      });
    onChange({ ...body, chemicals_used: next });
  }, [body, onChange]);

  const changeType = (nextType) => {
    if (locked) return;
    if (!READING_ALLOWLIST[nextType]) return;
    onChange({
      ...body,
      type: nextType,
      // Reset label to the type default only if the tech hasn't
      // customized it (label matches the previous type's default).
      label: (body?.label === BODY_TYPE_LABELS[body?.type])
              ? BODY_TYPE_LABELS[nextType]
              : (body?.label || BODY_TYPE_LABELS[nextType]),
      // Drop readings + chemicals that aren't allowed under the new
      // type (server would 422 otherwise).
      readings: (body?.readings || []).filter((r) => {
        const k = String(r?.key || "").toLowerCase();
        return nextType === "other"
                || (READING_ALLOWLIST[nextType] || []).includes(k);
      }),
      chemicals_used: (body?.chemicals_used || body?.chemicals_added || [])
        .filter((c_) => {
          const s = String(c_?.product_slug || c_?.slug || "").toLowerCase();
          return nextType === "other"
                  || (CHEMICAL_ALLOWLIST[nextType] || []).includes(s);
        }),
    });
  };

  const changeLabel = (nextLabel) => {
    if (locked) return;
    onChange({ ...body, label: nextLabel });
  };

  const changeNotes = (nextNotes) => {
    if (locked) return;
    onChange({ ...body, notes: nextNotes });
  };

  const handleRemove = () => {
    // Confirm if the body has any entered data.
    const hasReadings = (body?.readings || []).some((r) => {
      const v = r?.value;
      return v !== null && v !== undefined && v !== "";
    });
    const hasChems = (body?.chemicals_used || body?.chemicals_added || []).some(
      (c_) => (c_?.quantity ?? c_?.amount)
    );
    const hasNotes = !!(body?.notes || "").trim();
    if (hasReadings || hasChems || hasNotes) {
      setConfirmingRemove(true);
      return;
    }
    onRemove();
  };

  return (
    <div
      className="rounded-lg overflow-hidden"
      style={{
        border: `1px solid ${tint.border}`,
        background: c.surface,
      }}
      data-testid={`water-body-panel-${index}`}
      data-body-type={bodyType}
    >
      {/* Header: type badge + optional label input + collapse + remove */}
      <div
        className="flex items-center gap-2 px-3 py-2"
        style={{ background: tint.bg, borderBottom: open ? `1px solid ${tint.border}` : "none" }}
      >
        <span
          className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-bold"
          style={{ background: c.surface, color: tint.fg, border: `1px solid ${tint.border}` }}
          data-testid={`water-body-type-badge-${index}`}
        >
          {BODY_TYPE_LABELS[bodyType]}
        </span>
        <select
          value={bodyType}
          disabled={locked}
          onChange={(e) => changeType(e.target.value)}
          className="text-xs px-2 py-1 rounded border"
          style={{ borderColor: tint.border, background: c.surface }}
          data-testid={`water-body-type-select-${index}`}
          aria-label="Body type"
        >
          {WATER_BODY_TYPES.map((t) => (
            <option key={t.value} value={t.value}>{t.label}</option>
          ))}
        </select>
        <input
          type="text"
          value={body?.label || ""}
          disabled={locked}
          onChange={(e) => changeLabel(e.target.value)}
          placeholder="Optional label (e.g., Backyard Pool)"
          className="flex-1 text-xs px-2 py-1 rounded border"
          style={{ borderColor: tint.border, background: c.surface }}
          data-testid={`water-body-label-${index}`}
        />
        <button
          type="button"
          onClick={() => setOpen(!open)}
          className="p-1 rounded"
          style={{ background: "transparent", border: 0, color: tint.fg }}
          aria-label={open ? "Collapse body" : "Expand body"}
          data-testid={`water-body-toggle-${index}`}
        >
          {open ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
        </button>
        {!locked ? (
          <button
            type="button"
            onClick={handleRemove}
            disabled={!canRemove}
            className="p-1 rounded"
            style={{
              background: "transparent", border: 0,
              color: canRemove ? c.danger : "#CBD5E1",
              cursor: canRemove ? "pointer" : "not-allowed",
            }}
            aria-label={`Remove ${label}`}
            title={canRemove ? "Remove this body" : "At least one body is required"}
            data-testid={`water-body-remove-${index}`}
          >
            <Trash2 size={14} />
          </button>
        ) : null}
      </div>

      {confirmingRemove ? (
        <div
          className="px-3 py-2 text-xs"
          style={{ background: c.warnBg, color: c.warnFg, borderBottom: `1px solid ${tint.border}` }}
          data-testid={`water-body-confirm-remove-${index}`}
        >
          <div className="flex items-center gap-2 flex-wrap">
            <AlertTriangle size={14} />
            <span>This body has entered data. Remove anyway?</span>
            <button
              type="button"
              onClick={() => { setConfirmingRemove(false); onRemove(); }}
              className="ml-auto px-2 py-1 rounded text-xs font-bold"
              style={{ background: c.danger, color: "#fff", border: 0 }}
              data-testid={`water-body-confirm-remove-yes-${index}`}
            >
              Yes, remove
            </button>
            <button
              type="button"
              onClick={() => setConfirmingRemove(false)}
              className="px-2 py-1 rounded text-xs"
              style={{ background: c.surface, color: c.warnFg, border: `1px solid ${tint.border}` }}
              data-testid={`water-body-confirm-remove-no-${index}`}
            >
              Cancel
            </button>
          </div>
        </div>
      ) : null}

      {open ? (
        <div className="px-3 py-3 space-y-4" data-testid={`water-body-body-${index}`}>
          {/* Readings */}
          <section>
            <div
              className="text-xs font-bold uppercase tracking-wider mb-2"
              style={{ color: c.muted }}
            >
              Chemistry
              {requiredKeys.length === 0 ? (
                <span className="ml-2 font-normal" style={{ color: c.muted }}>
                  (all optional)
                </span>
              ) : null}
            </div>
            <div className="space-y-1.5">
              {allowedReadings.map((key) => (
                <ReadingRow
                  key={key}
                  readingKey={key}
                  current={readingsByKey.get(key)}
                  required={requiredSet.has(key)}
                  locked={locked}
                  onChange={(v) => updateReading(key, v)}
                />
              ))}
            </div>
            {missingReq.length > 0 && requiredKeys.length > 0 ? (
              <div
                className="mt-2 text-xs px-2 py-1 rounded"
                style={{ background: c.warnBg, color: c.warnFg }}
                data-testid={`water-body-required-warning-${index}`}
              >
                Missing required: {missingReq.map((k) => (READING_LABELS[k]?.short || k)).join(", ")}
              </div>
            ) : null}
          </section>

          {/* Chemicals used */}
          <section>
            <div
              className="text-xs font-bold uppercase tracking-wider mb-2"
              style={{ color: c.muted }}
            >
              Chemicals Used
            </div>
            <div className="space-y-1.5">
              {allowedChems.map((slug) => (
                <ChemicalRow
                  key={slug}
                  slug={slug}
                  chem={chemicalsBySlug.get(slug)}
                  locked={locked}
                  onChange={(patch) => updateChemical(slug, patch)}
                  onRemove={clearChemical}
                />
              ))}
            </div>
          </section>

          {/* Notes */}
          <section>
            <label
              className="text-xs font-bold uppercase tracking-wider block mb-2"
              style={{ color: c.muted }}
            >
              Notes
            </label>
            <textarea
              rows={2}
              value={body?.notes || ""}
              disabled={locked}
              onChange={(e) => changeNotes(e.target.value)}
              placeholder="Anything worth noting about this body"
              className="w-full text-sm rounded border p-2"
              style={{ borderColor: c.border, background: locked ? c.surfaceAlt : c.surface }}
              data-testid={`water-body-notes-${index}`}
            />
          </section>
        </div>
      ) : null}
    </div>
  );
}
