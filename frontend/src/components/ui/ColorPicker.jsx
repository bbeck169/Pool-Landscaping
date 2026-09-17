/**
 * Feb-2026 · Global Custom Color Picker component.
 *
 * A single-source picker that combines three colour-selection UIs:
 *   1. **Presets row** — the 12-color tech palette (source of truth
 *      stays ``@/lib/techColorsPalette``). Optionally extended to
 *      the full 24-color expansion via ``useTechColorsPalette``.
 *   2. **Recently used** — last 8 hexes the current user committed.
 *      Hydrated from ``GET /users/me/recent-colors`` on mount, and
 *      pushed to via ``POST /users/me/recent-colors`` after each
 *      successful commit (fire-and-forget, best-effort).
 *   3. **Freeform picker** — native ``<input type="color">`` for
 *      the WYSIWYG square + a hex text input. Live preview swatch
 *      reflects the current draft. Contrast guard blocks colours
 *      below WCAG 3:1 vs white; Save button is disabled + inline
 *      warning renders.
 *
 * Props:
 *   * ``value``        — current committed hex (case-insensitive).
 *   * ``onChange(hex)``— fires ONLY when the caller commits a valid
 *                        (contrast-passing) hex.
 *   * ``disabled``     — gates every interactive input.
 *   * ``testidPrefix`` — id prefix so multiple pickers can coexist
 *                        on the same page.
 *   * ``paletteHexes`` — optional override (defaults to the 12-color
 *                        constant). Pass the full 24 to expose the
 *                        expanded row.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Check, AlertTriangle } from "lucide-react";
import { api } from "@/api";
import { TECH_COLOR_PALETTE, PALETTE_HEXES } from "@/lib/techColorsPalette";
import {
  MIN_CONTRAST_VS_WHITE,
  contrastRatioVsWhite,
  validateColorHexForPin,
} from "@/lib/colorContrast";
import { colors } from "@/theme";


function _norm(hex) {
  if (!hex || typeof hex !== "string") return "";
  const s = hex.trim();
  if (!s) return "";
  return (s.startsWith("#") ? s : `#${s}`).toUpperCase();
}


export default function ColorPicker({
  value,
  onChange,
  disabled = false,
  testidPrefix = "color-picker",
  paletteHexes = PALETTE_HEXES,
}) {
  const normalized = _norm(value);
  const [draft, setDraft] = useState(normalized || "");
  const [recent, setRecent] = useState([]);
  const [saving, setSaving] = useState(false);

  useEffect(() => { setDraft(normalized || ""); }, [normalized]);

  // Hydrate recents from the API on mount. Best-effort: a fetch
  // failure just leaves the row empty — never blocks the picker.
  useEffect(() => {
    let alive = true;
    api.get("/users/me/recent-colors").then((r) => {
      if (!alive) return;
      const list = Array.isArray(r?.recent_colors) ? r.recent_colors : [];
      setRecent(list.map(_norm).filter(Boolean));
    }).catch(() => { /* silent */ });
    return () => { alive = false; };
  }, []);

  const draftValidation = useMemo(
    () => validateColorHexForPin(draft || "#000000"),
    [draft],
  );
  const commitDisabled = disabled || saving
    || !draftValidation.ok
    || _norm(draftValidation.canonical) === normalized;

  const commit = useCallback(async (hex) => {
    const validation = validateColorHexForPin(hex);
    if (!validation.ok) return;
    setSaving(true);
    try {
      const canonical = validation.canonical;
      // Parent handles the actual persistence — we just emit.
      await Promise.resolve(onChange?.(canonical));
      // Fire-and-forget recent-colors push. Failure is silent.
      api.post("/users/me/recent-colors", { color: canonical })
        .then((r) => {
          const next = Array.isArray(r?.recent_colors)
            ? r.recent_colors.map(_norm).filter(Boolean)
            : null;
          if (next) setRecent(next);
        })
        .catch(() => { /* silent */ });
    } finally {
      setSaving(false);
    }
  }, [onChange]);

  return (
    <div
      className="rounded-xl p-4 space-y-4"
      style={{ background: colors.surface,
                border: `1px solid ${colors.border}` }}
      data-testid={`${testidPrefix}-root`}
    >
      {/* Presets row */}
      <div>
        <div className="text-xs font-semibold mb-1.5"
              style={{ color: colors.muted }}>
          Presets
        </div>
        <div className="flex flex-wrap gap-2"
              role="listbox"
              aria-label="Preset color swatches"
              data-testid={`${testidPrefix}-presets`}>
          {paletteHexes.map((hex) => {
            const active = _norm(hex) === normalized;
            const validation = validateColorHexForPin(hex);
            const _tooLight = !validation.ok;
            const name = TECH_COLOR_PALETTE.find(
              (p) => _norm(p.hex) === _norm(hex))?.name || hex;
            return (
              <button
                key={hex}
                type="button"
                role="option"
                aria-selected={active}
                aria-label={`Set color to ${name}${_tooLight ? " (low contrast)" : ""}`}
                title={_tooLight
                  ? `${name} — ${hex} · too light for the map pin`
                  : `${name} — ${hex}`}
                disabled={disabled || _tooLight}
                onClick={() => commit(hex)}
                className="w-7 h-7 rounded-full inline-flex items-center justify-center"
                style={{
                  backgroundColor: hex,
                  outline: active ? `2px solid ${colors.onSurface}` : "none",
                  outlineOffset: "2px",
                  opacity: _tooLight ? 0.35 : 1,
                  cursor: (disabled || _tooLight) ? "not-allowed" : "pointer",
                }}
                data-testid={`${testidPrefix}-preset-${_norm(hex)}`}
              >
                {active ? <Check size={14} color="#fff" /> : null}
              </button>
            );
          })}
        </div>
      </div>

      {/* Recently used row */}
      {recent.length > 0 ? (
        <div data-testid={`${testidPrefix}-recent-row`}>
          <div className="text-xs font-semibold mb-1.5"
                style={{ color: colors.muted }}>
            Recently used
          </div>
          <div className="flex flex-wrap gap-2"
                role="listbox"
                aria-label="Recently used colors">
            {recent.map((hex) => {
              const active = hex === normalized;
              return (
                <button
                  key={hex}
                  type="button"
                  role="option"
                  aria-selected={active}
                  aria-label={`Set color to ${hex}`}
                  disabled={disabled}
                  onClick={() => commit(hex)}
                  className="w-7 h-7 rounded-full inline-flex items-center justify-center"
                  style={{
                    backgroundColor: hex,
                    outline: active ? `2px solid ${colors.onSurface}` : "none",
                    outlineOffset: "2px",
                    cursor: disabled ? "not-allowed" : "pointer",
                  }}
                  data-testid={`${testidPrefix}-recent-${hex}`}
                />
              );
            })}
          </div>
        </div>
      ) : null}

      {/* Freeform picker */}
      <div className="space-y-2" data-testid={`${testidPrefix}-freeform`}>
        <div className="text-xs font-semibold mb-1"
              style={{ color: colors.muted }}>
          Custom color
        </div>
        <div className="flex items-center gap-2">
          <input
            type="color"
            value={draftValidation.ok ? draft : "#000000"}
            onChange={(e) => setDraft(_norm(e.target.value))}
            disabled={disabled}
            className="w-10 h-10 rounded cursor-pointer"
            style={{ border: `1px solid ${colors.border}`, padding: 0 }}
            data-testid={`${testidPrefix}-native-input`}
            aria-label="Pick a custom color"
          />
          <input
            type="text"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="#RRGGBB"
            maxLength={7}
            disabled={disabled}
            className="flex-1 px-3 py-2 rounded-lg text-sm font-mono"
            style={{ background: colors.surfaceSecondary,
                      border: `1px solid ${colors.border}`,
                      color: colors.onSurface }}
            data-testid={`${testidPrefix}-hex-input`}
          />
          <div
            className="w-10 h-10 rounded flex-shrink-0"
            style={{
              background: draftValidation.ok ? draft : "#FFFFFF",
              border: `1px solid ${colors.border}`,
            }}
            aria-hidden="true"
            data-testid={`${testidPrefix}-preview`}
          />
        </div>
        {!draftValidation.ok && draft ? (
          <div
            className="flex items-start gap-1 text-xs"
            style={{ color: "#B91C1C" }}
            role="alert"
            data-testid={`${testidPrefix}-contrast-warning`}
          >
            <AlertTriangle size={14} style={{ marginTop: 1 }} />
            {draftValidation.reason === "contrast"
              ? "This color is too light to read on the map pin. Pick a darker shade."
              : "Enter a valid 6-digit hex color (e.g. #0EA5E9)."}
          </div>
        ) : null}
        <div className="flex justify-end">
          <button
            type="button"
            onClick={() => commit(draft)}
            disabled={commitDisabled}
            className="inline-flex items-center gap-1 px-3 py-2 rounded-lg text-sm font-bold"
            style={{
              background: commitDisabled ? "#D1D5DB" : colors.brand,
              color: commitDisabled ? "#6B7280" : "#FFFFFF",
              cursor: commitDisabled ? "not-allowed" : "pointer",
            }}
            data-testid={`${testidPrefix}-commit`}
          >
            Apply
          </button>
        </div>
      </div>
    </div>
  );
}


export { MIN_CONTRAST_VS_WHITE, contrastRatioVsWhite, validateColorHexForPin };
