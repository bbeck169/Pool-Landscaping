/**
 * Phase I1.5.c · Feb-2026 — Tenant theme CSS variable overlay.
 *
 * Bridges the API-persisted theme (from ``GET /api/tenants/me/theme``)
 * to the DOM via CSS custom properties on ``document.documentElement``.
 *
 *   • ``writeTenantCssVars(el, theme)`` — writes the full set on
 *     mount and every refetch. Idempotent + reversible.
 *   • ``clearTenantCssVars(el)``        — used on sign-out to prevent
 *     a stale tenant palette bleeding into the public login route
 *     during the next mount cycle.
 *   • ``TENANT_VAR_SPEC``               — the canonical map of
 *     slot-path → CSS custom-property name. Consumers reach for
 *     these names via ``tenantCssVar(path, fallback)``.
 *   • ``tenantCssVar(path, fallback)``  — returns
 *     ``"var(--tenant-<name>, <fallback>)"`` so any consumer that
 *     wants to opt-in to tenant overrides can drop it into an
 *     inline style without a hook subscription.
 *
 * Why CSS vars (not a hook subscription):
 *   Existing K64/K67/K70/K74/K74.1 consumers read the STATIC
 *   ``colors.*`` / ``gradients.*`` exports from ``theme.js`` at
 *   module load. Refactoring every one to subscribe to
 *   ``useTenantTheme()`` would (a) touch dozens of files and (b)
 *   break every source-grep regression test that asserts on the
 *   import shape (K64/K67/K70a/K74/K75/K76 — see the guardrail in
 *   the phase brief). CSS vars route around this: existing
 *   consumers stay untouched, and a small set of high-visibility
 *   surfaces gets an inline-style overlay that reads through the
 *   var chain with the current default as fallback.
 *
 * Gradient slots: the writer emits the full CSS gradient string
 * so a single ``background: var(--tenant-menu-bg-css, ...)``
 * covers both solid and gradient modes.
 */
import { colors, gradients } from "@/theme";


// ── Slot spec — mirrors backend ``SECTIONS`` in validate.py ──
export const TENANT_VAR_SPEC = [
  // menu
  { path: "menu.bg",           name: "menu-bg",           kind: "fill" },
  { path: "menu.text",         name: "menu-text",         kind: "solid" },
  // rail
  { path: "rail.bg",           name: "rail-bg",           kind: "fill" },
  { path: "rail.text",         name: "rail-text",         kind: "solid" },
  // tiles
  { path: "tiles.bg",          name: "tiles-bg",          kind: "fill" },
  { path: "tiles.text",        name: "tiles-text",        kind: "solid" },
  { path: "tiles.border",      name: "tiles-border",      kind: "solid" },
  // buttons
  { path: "buttons.bg",        name: "buttons-bg",        kind: "fill" },
  { path: "buttons.text",      name: "buttons-text",      kind: "solid" },
  // accents
  { path: "accents.primary",   name: "accents-primary",   kind: "fill" },
  { path: "accents.secondary", name: "accents-secondary", kind: "fill" },
  { path: "accents.text",      name: "accents-text",      kind: "solid" },
  { path: "accents.link",      name: "accents-link",      kind: "solid" },
  { path: "accents.focus_ring", name: "accents-focus-ring", kind: "solid" },
  { path: "accents.badge_bg",  name: "accents-badge-bg",  kind: "fill" },
  { path: "accents.badge_text", name: "accents-badge-text", kind: "solid" },
];


// ── I1.5.c.fix · Feb-2026 — derived surface vars ────────────────
// These are NOT full preset slots (yet) — they're semantic aliases
// derived from an existing slot at ``writeTenantCssVars`` time so
// specific surfaces can reskin along with the tenant's brand
// without adding new preset fields. Contract:
//
//   * ``--tenant-k74-identity``      ← ``accents.secondary``
//     The K74 "solid navy identity chip" (Dashboard KPI icon chip,
//     Reports 'coming soon' tile). Follows the tenant's dark
//     brand shade — default preset re-pins to ``#1B1F5C`` so
//     existing K64/K74 pixels are preserved on tenants with no
//     theme.
//   * ``--tenant-schedule-tile-bg``  ← ``accents.badge_bg``
//     The K74.1 mint schedule-tile bg (Today's Schedule list).
//     Follows the tenant's pastel accent — default preset re-pins
//     to ``#EAF7F0`` for the same reason.
const DERIVED_SURFACE_VARS = [
  { name: "k74-identity",      from: "accents.secondary", kind: "solid" },
  { name: "schedule-tile-bg",  from: "accents.badge_bg",  kind: "solid" },
];


// ── Default backstops — used when the API + provider aren't up ──
// Keys mirror the ``TENANT_VAR_SPEC`` ``name`` slugs. Values are
// the historical hardcoded defaults these surfaces render with
// today (so the CSS var fallback keeps existing K64/K67/K70/K74
// pixels identical when no tenant override is present).
export const TENANT_VAR_DEFAULTS = {
  "menu-bg":            colors.nav.bg,               // #1B1F5C
  "menu-bg-css":        colors.nav.bg,
  "menu-text":          colors.nav.fg,               // #FFFFFF
  "rail-bg":            colors.nav.bg,
  "rail-bg-css":        colors.nav.bg,
  "rail-text":          colors.nav.fg,
  "tiles-bg":           colors.tile.solidNavy,       // #1B1F5C
  "tiles-bg-css":       colors.tile.solidNavy,
  "tiles-text":         "#FFFFFF",
  "tiles-border":       colors.border,               // #E4E4E7
  "buttons-bg":         colors.brand,                // #0284C7
  "buttons-bg-css":     gradients.navyToGreen.css,   // K52/K67 signature
  "buttons-text":       "#FFFFFF",
  "accents-primary":    colors.brand,
  "accents-primary-css": colors.brand,
  "accents-secondary":  colors.brandSecondary,       // #16A34A
  "accents-secondary-css": colors.brandSecondary,
  "accents-text":       colors.onSurface,            // #09090B
  "accents-link":       colors.brand,
  "accents-focus-ring": colors.brand,
  "accents-badge-bg":   colors.brandTertiary,        // #E0F2FE
  "accents-badge-bg-css": colors.brandTertiary,
  "accents-badge-text": colors.onBrandTertiary,      // #0369A1
};


function _getSlot(theme, path) {
  const [section, slot] = path.split(".");
  return theme?.[section]?.[slot] || null;
}


function _slotToCss(slot) {
  if (!slot) return null;
  if (slot.mode === "gradient" && slot.gradient) {
    const { from, to, angle } = slot.gradient;
    return `linear-gradient(${angle}deg, ${from} 0%, ${to} 100%)`;
  }
  return slot.solid || null;
}


/**
 * Write every tenant CSS var to the given element. Fill slots
 * receive TWO vars — ``--tenant-<name>`` (the resolved single
 * color) and ``--tenant-<name>-css`` (the full CSS gradient
 * string or the solid hex, whichever applies). Consumers pick
 * whichever fits: ``backgroundColor`` uses the solid,
 * ``background``/``backgroundImage`` uses the CSS.
 *
 * ``theme`` shape matches the API contract (see
 * ``backend/services/theme/validate.py``). Missing sections /
 * slots are skipped — the CSS fallback keeps rendering.
 */
export function writeTenantCssVars(el, theme) {
  if (!el || !theme) return;
  for (const spec of TENANT_VAR_SPEC) {
    const slot = _getSlot(theme, spec.path);
    if (!slot) continue;
    const solid = slot.mode === "solid" ? slot.solid : null;
    if (solid) {
      el.style.setProperty(`--tenant-${spec.name}`, solid);
    }
    if (spec.kind === "fill") {
      const css = _slotToCss(slot);
      if (css) el.style.setProperty(`--tenant-${spec.name}-css`, css);
    }
  }
  // I1.5.c.fix — derived surface vars (K74 identity, K74.1 schedule
  // tile bg). Sourced from an existing slot at write-time so no new
  // preset fields are required.
  for (const der of DERIVED_SURFACE_VARS) {
    const slot = _getSlot(theme, der.from);
    if (!slot) continue;
    const solid = slot.mode === "solid" ? slot.solid : null;
    if (solid) el.style.setProperty(`--tenant-${der.name}`, solid);
  }
}


/** Remove every tenant CSS var (used on sign-out).
 *  Also clears any residual ``-css`` variants + derived surface
 *  vars introduced in I1.5.c.fix. */
export function clearTenantCssVars(el) {
  if (!el) return;
  for (const spec of TENANT_VAR_SPEC) {
    el.style.removeProperty(`--tenant-${spec.name}`);
    if (spec.kind === "fill") {
      el.style.removeProperty(`--tenant-${spec.name}-css`);
    }
  }
  for (const der of DERIVED_SURFACE_VARS) {
    el.style.removeProperty(`--tenant-${der.name}`);
  }
}


/**
 * Return a ``var(--tenant-<name>, <fallback>)`` string for a
 * given slot path. Use in inline styles when the surface should
 * follow tenant overrides. The fallback keeps existing pixels
 * identical when no provider is mounted (SSR, tests, public
 * routes).
 *
 * ``kind`` picks between the solid + css variable variants:
 *   * ``"solid"`` (default) → ``var(--tenant-menu-bg, #1B1F5C)``
 *   * ``"css"``             → ``var(--tenant-menu-bg-css, #1B1F5C)``
 *
 * Pass ``fallback`` explicitly to keep the caller's default hex
 * co-located with the consumer (helps grep / codemod work later).
 */
export function tenantCssVar(path, fallback, kind = "solid") {
  const spec = TENANT_VAR_SPEC.find((s) => s.path === path);
  const name = spec?.name || path.replace(/[.\_]/g, "-");
  const suffix = kind === "css" && spec?.kind === "fill" ? "-css" : "";
  const fb = fallback ?? TENANT_VAR_DEFAULTS[name + suffix]
                        ?? TENANT_VAR_DEFAULTS[name];
  if (!fb) return `var(--tenant-${name}${suffix})`;
  return `var(--tenant-${name}${suffix}, ${fb})`;
}
