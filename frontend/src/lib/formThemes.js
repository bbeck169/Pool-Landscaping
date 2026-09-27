/**
 * Phase K34 · Feb-2026 — Unified form-builder theme registry.
 *
 * Single source of truth for the ~5 curated presets + the ~6
 * curated system-font stacks. Every form-builder editor and every
 * form renderer imports from this file so a preset change here
 * propagates everywhere.
 *
 * Design principles
 * -----------------
 *   * System fonts ONLY — no Google Fonts, no external network.
 *   * Color roles are role-named (primary / background / text /
 *     border / accent) so a renderer that adds a new UI element
 *     just picks the appropriate role, no per-preset changes.
 *   * ``preset === "custom"`` means the caller has hand-picked
 *     colors that don't match any curated preset; the values in
 *     ``colors`` are then the source of truth.
 *   * ``coerceTheme(raw)`` fills in defaults so a renderer can
 *     always call ``t.colors.primary`` without null-checks.
 */

/** Curated system-font stacks. Keyed by an app-local id. */
export const FORM_FONT_STACKS = [
  {
    id: "system_ui",
    label: "System UI (recommended)",
    stack: "system-ui, -apple-system, BlinkMacSystemFont, \"Segoe UI\", "
            + "Roboto, Oxygen, Ubuntu, Cantarell, sans-serif",
  },
  {
    id: "modern_sans",
    label: "Modern Sans",
    stack: "-apple-system, BlinkMacSystemFont, \"Segoe UI\", Roboto, "
            + "\"Helvetica Neue\", Arial, sans-serif",
  },
  {
    id: "humanist_sans",
    label: "Humanist Sans",
    stack: "\"Segoe UI\", Tahoma, Geneva, Verdana, sans-serif",
  },
  {
    id: "editorial_serif",
    label: "Editorial Serif",
    stack: "Georgia, Cambria, \"Times New Roman\", Times, serif",
  },
  {
    id: "classic_serif",
    label: "Classic Serif",
    stack: "\"Palatino Linotype\", Palatino, \"Book Antiqua\", "
            + "\"URW Palladio L\", serif",
  },
  {
    id: "monospace",
    label: "Monospace",
    stack: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "
            + "\"Liberation Mono\", \"Courier New\", monospace",
  },
];

export function fontStackById(id) {
  return (FORM_FONT_STACKS.find(f => f.id === id) || FORM_FONT_STACKS[0]).stack;
}

/** Curated presets. Order = swatch order in the picker. */
export const FORM_THEME_PRESETS = [
  {
    key: "modern_blue",
    name: "Modern Blue",
    colors: {
      primary: "#2563eb",
      background: "#ffffff",
      text: "#111827",
      border: "#e5e7eb",
      accent: "#3b82f6",
    },
    font_family_id: "system_ui",
  },
  {
    key: "warm_earth",
    name: "Warm Earth",
    colors: {
      primary: "#b45309",
      background: "#fdf8f2",
      text: "#292524",
      border: "#e7d9c4",
      accent: "#d97706",
    },
    font_family_id: "editorial_serif",
  },
  {
    key: "bold_green",
    name: "Bold Green",
    colors: {
      primary: "#047857",
      background: "#ffffff",
      text: "#0f172a",
      border: "#d1fae5",
      accent: "#059669",
    },
    font_family_id: "modern_sans",
  },
  {
    key: "clean_neutral",
    name: "Clean Neutral",
    colors: {
      primary: "#111827",
      background: "#ffffff",
      text: "#1f2937",
      border: "#e5e7eb",
      accent: "#374151",
    },
    font_family_id: "humanist_sans",
  },
  {
    key: "elegant_dark",
    name: "Elegant Dark",
    colors: {
      primary: "#a78bfa",
      background: "#0f172a",
      text: "#e2e8f0",
      border: "#1e293b",
      accent: "#c4b5fd",
    },
    font_family_id: "classic_serif",
  },
];

export const DEFAULT_THEME_KEY = "modern_blue";

export function presetByKey(key) {
  return FORM_THEME_PRESETS.find(p => p.key === key)
    || FORM_THEME_PRESETS[0];
}

// ── CUS-Marketing-Form-Builder · Feb-2026 — Phase 2 helpers ────

/**
 * Clamp an integer between ``[lo, hi]``. Non-integers, ``null``, and
 * ``undefined`` all return ``null`` (signals "not set"). Used by
 * ``coerceTheme`` to normalise the two new optional fields
 * (``gradient.angle_deg`` and ``overlay_opacity``) without silently
 * accepting garbage — invalid input becomes a clean ``null`` /
 * clamped value at the boundary.
 */
function _clampInt(v, lo, hi) {
  if (v === null || v === undefined) return null;
  const n = Number(v);
  if (!Number.isFinite(n)) return null;
  return Math.min(hi, Math.max(lo, Math.round(n)));
}

/**
 * Validate + normalise a gradient sub-object. Returns ``null`` when
 * the input is missing or malformed; otherwise returns a fresh
 * ``{angle_deg, from, to}`` triple with the angle clamped to
 * ``[0, 360]`` and hex values passed through verbatim (frontend
 * pickers already emit valid ``#RRGGBB``).
 *
 * The full-null return is the "no gradient" contract — every
 * theme in K34 pre-Phase-2 carried a stable ``null`` here so
 * ``themeToCssVars`` omits ``--form-bg-gradient`` and the K34
 * output is byte-identical.
 */
function _coerceGradient(g) {
  if (!g || typeof g !== "object") return null;
  const angle = _clampInt(g.angle_deg, 0, 360);
  const from = typeof g.from === "string" ? g.from : "";
  const to   = typeof g.to   === "string" ? g.to   : "";
  if (angle === null || !from || !to) return null;
  return { angle_deg: angle, from, to };
}

/**
 * Normalize whatever the caller passes into a fully-populated theme
 * object.  Guarantees the shape ``{preset, colors:{5 roles}, font_family,
 * gradient, overlay_opacity}``.
 *
 * CUS-Marketing-Form-Builder · Feb-2026 — Phase 2 additions:
 *   - ``gradient`` — ``null`` or ``{angle_deg 0-360, from #hex, to #hex}``.
 *   - ``overlay_opacity`` — ``null`` or an integer clamped to ``[0, 100]``.
 *
 * Backwards-compat guarantee: every K34 curated preset round-trips
 * byte-identical through ``coerceTheme(preset)`` because both new
 * fields default to ``null`` (the "not set" sentinel) and are only
 * populated when the caller explicitly opts in.
 */
export function coerceTheme(raw) {
  const src = raw && typeof raw === "object" ? raw : {};
  const preset = src.preset === "custom" ? "custom"
    : (FORM_THEME_PRESETS.find(p => p.key === src.preset)?.key
        || (src.preset ? "custom" : DEFAULT_THEME_KEY));
  const base = preset === "custom"
    ? presetByKey(DEFAULT_THEME_KEY)
    : presetByKey(preset);
  const colors = {
    primary:    src?.colors?.primary    || base.colors.primary,
    background: src?.colors?.background || base.colors.background,
    text:       src?.colors?.text       || base.colors.text,
    border:     src?.colors?.border     || base.colors.border,
    accent:     src?.colors?.accent     || base.colors.accent,
  };
  const font_family = src.font_family || fontStackById(base.font_family_id);
  return {
    preset, colors, font_family,
    gradient:        _coerceGradient(src.gradient),
    overlay_opacity: _clampInt(src.overlay_opacity, 0, 100),
  };
}

/**
 * Turn a theme object into a ``style`` dict suitable for React's
 * ``style=`` prop on the root element.  Emits CSS variables that
 * renderers reference for consistent styling.
 *
 * CUS-Marketing-Form-Builder · Feb-2026 — Phase 2 additions:
 *   - ``--form-bg-gradient`` — emitted ONLY when the theme carries
 *     a non-null gradient. Value is the fully-composed
 *     ``linear-gradient(<angle>deg, <from> 0%, <to> 100%)`` string
 *     ready to plug into ``background-image``.
 *   - ``--form-overlay-opacity`` — emitted ONLY when the theme
 *     carries a non-null overlay_opacity. Value is a decimal in
 *     ``[0.00, 1.00]`` (int/100) suitable for ``rgba(0,0,0, var(...))``.
 *
 * Both are omitted (NOT emitted as empty strings) when null so a
 * K34 preset's ``themeToCssVars`` output is byte-identical to the
 * pre-Phase-2 shape. Consumers of the vars should treat absence as
 * "no gradient / no overlay" and fall back to the solid
 * ``--form-background``.
 */
export function themeToCssVars(theme) {
  const t = coerceTheme(theme);
  const out = {
    "--form-primary":    t.colors.primary,
    "--form-background": t.colors.background,
    "--form-text":       t.colors.text,
    "--form-border":     t.colors.border,
    "--form-accent":     t.colors.accent,
    fontFamily: t.font_family,
    backgroundColor: t.colors.background,
    color: t.colors.text,
  };
  if (t.gradient) {
    out["--form-bg-gradient"] =
      `linear-gradient(${t.gradient.angle_deg}deg, `
      + `${t.gradient.from} 0%, ${t.gradient.to} 100%)`;
  }
  if (t.overlay_opacity !== null) {
    // Decimal string with 2 fixed digits so 30 → "0.30", not "0.3"
    // — makes source-lint regexes deterministic + matches CSS
    // convention.
    out["--form-overlay-opacity"] = (t.overlay_opacity / 100).toFixed(2);
  }
  return out;
}
