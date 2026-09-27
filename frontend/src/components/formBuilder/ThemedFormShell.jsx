import React from "react";
import { themeToCssVars, coerceTheme } from "../../lib/formThemes";

/**
 * Phase K34 · Feb-2026 — shared theme applier for every public
 * form renderer. Wraps children in a div that carries the
 * ``--form-*`` CSS variables and the theme's font-family +
 * background-color as inline styles.
 *
 *   <ThemedFormShell theme={form.theme} testid="lead-intake-form">
 *     {form fields...}
 *   </ThemedFormShell>
 *
 * If ``theme`` is null/undefined, the wrapper still renders but
 * doesn't emit any CSS vars — the app's default look prevails.
 * Backwards-compatible for every form that hasn't picked a theme
 * yet.
 *
 * CUS-Marketing-Form-Builder · Feb-2026 — Phase 2 additions:
 *   - When ``theme.gradient`` is set, the wrapper's
 *     ``background-image`` is composed from the ``--form-bg-gradient``
 *     variable so the gradient layers on top of the solid
 *     ``--form-background`` fallback.
 *   - When ``theme.overlay_opacity`` is also set (non-zero), a
 *     black darkening layer is stacked ABOVE the gradient via
 *     ``linear-gradient(rgba(0,0,0, X), rgba(0,0,0, X)), <gradient>``
 *     — a single ``background-image`` composition, no extra DOM
 *     node, so existing children rendering is untouched.
 *   - Overlay WITHOUT gradient is a Phase-2 no-op (there's no rich
 *     background to darken yet — the hero background image lands
 *     in Phase 3 and re-consumes the same ``--form-overlay-opacity``
 *     variable). Var is still emitted so Phase 3 can read it.
 *
 * Zero-regression guarantee for K34 curated presets: neither
 * ``gradient`` nor ``overlay_opacity`` fires when null, so the
 * inline-style output is byte-identical to the pre-Phase-2 shape.
 */
export default function ThemedFormShell({ theme, children, testid, className }) {
  const applied = theme ? themeToCssVars(coerceTheme(theme)) : {};
  const gradient = applied["--form-bg-gradient"];
  const overlay  = applied["--form-overlay-opacity"];

  let backgroundImage;
  if (gradient) {
    if (overlay && Number(overlay) > 0) {
      // Stack a solid-black darkening layer above the gradient.
      // Both layers share the same ``background-image`` — Phase 3
      // will insert a third layer (the hero image URL) at the
      // BOTTOM of this stack.
      backgroundImage =
        `linear-gradient(rgba(0,0,0, ${overlay}), rgba(0,0,0, ${overlay})),`
        + ` ${gradient}`;
    } else {
      backgroundImage = gradient;
    }
  }

  const style = backgroundImage
    ? { ...applied, backgroundImage }
    : applied;

  return (
    <div
      data-testid={testid || "themed-form-shell"}
      data-themed={theme ? "true" : "false"}
      className={className}
      style={style}
    >
      {children}
    </div>
  );
}
