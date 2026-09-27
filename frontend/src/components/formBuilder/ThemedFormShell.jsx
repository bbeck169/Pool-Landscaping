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
 *
 * CUS-Marketing-Form-Builder · Feb-2026 — Phase 4 addition:
 *   - Optional ``hero`` prop mirrors ``schema.hero`` from the widget.
 *     When set, a hero band is rendered ABOVE ``children`` with
 *     rich-text heading / sub-heading, background (color | image |
 *     gradient), and optional badge. Consumers pass the raw hero
 *     object; ``ThemedFormShell`` handles the rendering.
 *   - ``hero == null`` → no hero DOM emitted (byte-identical to
 *     Phase 2/3 output).
 *   - ``PublicLeadIntake`` is the primary consumer, mirroring how
 *     it already lifts ``form_theme`` from ``window.__TENANT_CONFIG__``.
 *     ``column_span`` is NOT applied on the React path because the
 *     page renders a hardcoded field set (name / email / phone /
 *     address / interest / notes) rather than iterating over
 *     ``schema.fields`` — see the recon note in the phase-4 commit
 *     message.
 */
export default function ThemedFormShell({ theme, hero, children, testid, className }) {
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
      {hero ? <ThemedHeroBand hero={hero} /> : null}
      {children}
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════
// CUS-Marketing-Form-Builder · Feb-2026 — Phase 4.
//
// React-side mirror of the widget's ``renderHero`` helper (see
// ``frontend/public/widget/form.js``). Kept as a local component
// so ``ThemedFormShell`` has a single import and consumers pass
// only the raw hero object.
//
// XSS containment: rich-text HTML (``heading_html``, ``subheading_html``)
// is injected via ``dangerouslySetInnerHTML``. Boundary is the
// ``RichTextField`` extension whitelist in the admin editor
// (StarterKit + Underline + TextStyle + Link with http/https/
// mailto/tel scheme allowlist). See
// ``frontend/src/components/formBuilder/RichTextField.jsx`` for the
// documented XSS boundary + list of extensions that MUST NOT be
// added without a DOMPurify hardening pass on the widget render
// path.
// ═══════════════════════════════════════════════════════════════
function ThemedHeroBand({ hero }) {
  if (!hero || typeof hero !== "object") return null;
  const bg = hero.background || { kind: "color", color: "#F8FAFC" };
  const wrapStyle = {
    position: "relative",
    padding: "32px 24px",
    borderRadius: "12px 12px 0 0",
    color: "#0F172A",
    overflow: "hidden",
  };
  if (bg.kind === "color") {
    wrapStyle.background = bg.color || "#F8FAFC";
  } else if (bg.kind === "gradient") {
    const angle = typeof bg.angle_deg === "number" ? bg.angle_deg : 135;
    wrapStyle.backgroundImage =
      `linear-gradient(${angle}deg, ${bg.from || "#0EA5E9"} 0%, ${bg.to || "#1B1F5C"} 100%)`;
    wrapStyle.color = "#FFFFFF";
  } else if (bg.kind === "image") {
    if (bg.url) {
      wrapStyle.backgroundImage = `url(${bg.url})`;
      wrapStyle.backgroundSize = "cover";
      wrapStyle.backgroundPosition = "center";
      wrapStyle.color = "#FFFFFF";
    } else {
      wrapStyle.background = "#F8FAFC";
    }
  }

  const showOverlay = bg.kind === "image"
    && typeof bg.overlay_opacity === "number"
    && bg.overlay_opacity > 0
    && bg.url;
  const overlayAlpha = showOverlay ? (bg.overlay_opacity / 100).toFixed(2) : null;

  return (
    <div
      data-testid="themed-hero-band"
      data-hero-kind={bg.kind || "color"}
      style={wrapStyle}
    >
      {showOverlay ? (
        <div
          data-testid="themed-hero-overlay"
          style={{
            position: "absolute",
            top: 0, left: 0, right: 0, bottom: 0,
            background: `rgba(0,0,0, ${overlayAlpha})`,
            pointerEvents: "none",
          }}
        />
      ) : null}
      <div style={{ position: "relative", zIndex: 1 }}>
        {hero.heading_html ? (
          <div
            data-testid="themed-hero-heading"
            style={{ fontSize: "24px", fontWeight: 700, marginBottom: "8px" }}
            // XSS containment via RichTextField schema whitelist —
            // see the security comment on ThemedHeroBand above.
            dangerouslySetInnerHTML={{ __html: hero.heading_html }}
          />
        ) : null}
        {hero.subheading_html ? (
          <div
            data-testid="themed-hero-subheading"
            style={{ fontSize: "14px", opacity: 0.9 }}
            dangerouslySetInnerHTML={{ __html: hero.subheading_html }}
          />
        ) : null}
      </div>
      {hero.badge && hero.badge.url ? (
        <img
          data-testid="themed-hero-badge"
          src={hero.badge.url}
          alt={hero.badge.alt_text || ""}
          style={{
            position: "absolute",
            top: "12px",
            right: "12px",
            width: "60px",
            height: "60px",
            objectFit: "contain",
            zIndex: 2,
          }}
        />
      ) : null}
    </div>
  );
}
