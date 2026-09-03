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
 */
export default function ThemedFormShell({ theme, children, testid, className }) {
  const applied = theme ? themeToCssVars(coerceTheme(theme)) : {};
  return (
    <div
      data-testid={testid || "themed-form-shell"}
      data-themed={theme ? "true" : "false"}
      className={className}
      style={applied}
    >
      {children}
    </div>
  );
}
