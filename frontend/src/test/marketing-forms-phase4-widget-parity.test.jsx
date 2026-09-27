/**
 * CUS-Marketing-Form-Builder · Feb-2026 — Phase 4.
 *
 * Locks widget + React-shell parity with the Phase 2 (gradient +
 * overlay), Phase 3 (hero + section + column_span) additions:
 *
 *   1. ``frontend/public/widget/form.js`` — vanilla JS widget.
 *      Source-lint (regex) checks: applyTheme helper + all five
 *      --form-* CSS var emissions, font_family handling, gradient
 *      linear-gradient path, overlay opacity rgba layer, hero
 *      shape (heading_html / subheading_html innerHTML + all three
 *      background kinds), column_span grid path, section-type
 *      layout row, backwards-compat guards, XSS documentation
 *      comment, dependency-free (no import / no DOMPurify).
 *
 *   2. ``frontend/src/components/formBuilder/ThemedFormShell.jsx``
 *      — React public-renderer shell. Renders a hero band when
 *      the ``hero`` prop is set; renders exactly as Phase 2/3 when
 *      null.
 *
 *   3. ``frontend/src/pages/public/PublicLeadIntake.jsx`` — reads
 *      ``window.__TENANT_CONFIG__.form_hero`` and forwards to the
 *      shell. Column-span is NOT applied on this page (hardcoded
 *      field set — documented in the source).
 */
import React from "react";
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";

import ThemedFormShell from "@/components/formBuilder/ThemedFormShell";


// Absolute paths for source-lint reads. vitest sets ``cwd`` to
// ``/app/frontend``.
const WIDGET_PATH = path.resolve(
  process.cwd(), "public/widget/form.js",
);
const SHELL_PATH = path.resolve(
  process.cwd(), "src/components/formBuilder/ThemedFormShell.jsx",
);
const INTAKE_PATH = path.resolve(
  process.cwd(), "src/pages/public/PublicLeadIntake.jsx",
);
const readSrc = (p) => fs.readFileSync(p, "utf8");


// ═══════════════════════════════════════════════════════════════
// 1) public/widget/form.js — source-lint parity
// ═══════════════════════════════════════════════════════════════
describe("Phase 4 · public/widget/form.js theme + hero + column_span parity", () => {
  it("applyTheme helper is present + emits every --form-* CSS variable",
      () => {
    const src = readSrc(WIDGET_PATH);
    expect(src).toMatch(/function applyTheme\s*\(/);
    // Every K34 role — the five --form-* CSS vars.
    expect(src).toMatch(/--form-primary/);
    expect(src).toMatch(/--form-background/);
    expect(src).toMatch(/--form-text/);
    expect(src).toMatch(/--form-border/);
    expect(src).toMatch(/--form-accent/);
  });

  it("theme.font_family + gradient + overlay opacity paths present",
      () => {
    const src = readSrc(WIDGET_PATH);
    // font_family drives inline style.
    expect(src).toMatch(/theme\.font_family/);
    expect(src).toMatch(/rootEl\.style\.fontFamily/);
    // Gradient composition — linear-gradient string.
    expect(src).toMatch(/linear-gradient\(/);
    expect(src).toMatch(/theme\.gradient/);
    expect(src).toMatch(/theme\.gradient\.from/);
    expect(src).toMatch(/theme\.gradient\.to/);
    // Overlay opacity — rgba(0,0,0 pattern.
    expect(src).toMatch(/theme\.overlay_opacity/);
    expect(src).toMatch(/rgba\(0,0,0,\s*/);
    // The dedicated CSS var mirrors the Phase 2 shell.
    expect(src).toMatch(/--form-overlay-opacity/);
  });

  it("hero schema is read + rich-text is rendered via innerHTML",
      () => {
    const src = readSrc(WIDGET_PATH);
    // Hero read guard.
    expect(src).toMatch(/schema\.hero/);
    expect(src).toMatch(/function renderHero\s*\(/);
    // heading_html / subheading_html injection points via
    // ``.innerHTML = ...``.
    expect(src).toMatch(/hero\.heading_html/);
    expect(src).toMatch(/hero\.subheading_html/);
    expect(src).toMatch(/heading\.innerHTML\s*=/);
    expect(src).toMatch(/sub\.innerHTML\s*=/);
  });

  it("hero background handles all three kinds — color / image / gradient",
      () => {
    const src = readSrc(WIDGET_PATH);
    // Kind branches inside renderHero.
    expect(src).toMatch(/bg\.kind\s*===\s*["']color["']/);
    expect(src).toMatch(/bg\.kind\s*===\s*["']image["']/);
    expect(src).toMatch(/bg\.kind\s*===\s*["']gradient["']/);
    // Image kind uses background-size cover + url() interpolation.
    expect(src).toMatch(/backgroundSize\s*=\s*["']cover["']/);
    expect(src).toMatch(/url\(/);
    // Image-kind overlay pseudo-layer.
    expect(src).toMatch(/form-widget-hero-overlay/);
    // Badge — optional img positioned in the top-right.
    expect(src).toMatch(/form-widget-hero-badge/);
    expect(src).toMatch(/hero\.badge/);
  });

  it("column_span drives CSS grid columns — full=span 2, half=span 1",
      () => {
    const src = readSrc(WIDGET_PATH);
    // Grid container.
    expect(src).toMatch(/form-widget-fields-grid/);
    expect(src).toMatch(/gridTemplateColumns/);
    // Half-span field consumption.
    expect(src).toMatch(/f\.column_span\s*===\s*["']half["']/);
    expect(src).toMatch(/["']span 1["']/);
    expect(src).toMatch(/["']span 2["']/);
    // data-column-span attribute exposes the value on the field row.
    expect(src).toMatch(/data-column-span/);
  });

  it("section-type fields render a header row and skip input creation",
      () => {
    const src = readSrc(WIDGET_PATH);
    // section branch inside fieldRow.
    expect(src).toMatch(/f\.type\s*===\s*["']section["']/);
    // Section span spans the whole grid width (2 cols).
    expect(src).toMatch(/gridColumn:\s*["']span 2["']/);
    // Section HTML label injected via innerHTML.
    expect(src).toMatch(/section\.innerHTML\s*=/);
    // Section testid is present.
    expect(src).toMatch(/form-widget-section-/);
  });

  it("backwards-compat guards: null theme / null hero render exactly as pre-Phase 4",
      () => {
    const src = readSrc(WIDGET_PATH);
    // theme guard.
    expect(src).toMatch(/if\s*\(!theme\s*\|\|\s*typeof theme\s*!==\s*["']object["']\)/);
    // hero guard.
    expect(src).toMatch(/if\s*\(!hero\s*\|\|\s*typeof hero\s*!==\s*["']object["']\)/);
    // Explicit conditional apply in renderForm.
    expect(src).toMatch(/if\s*\(schema\.theme\)/);
    expect(src).toMatch(/renderHero\(schema\.hero\)/);
    // Legacy fallback CTA color path still present (brand_color +
    // #0EA5E9 hex retained inline).
    expect(src).toMatch(/#0EA5E9/);
  });

  it("XSS documentation comment references the RichTextField boundary",
      () => {
    const src = readSrc(WIDGET_PATH);
    // The security section must call out RichTextField.
    expect(src).toMatch(/SECURITY/);
    expect(src).toMatch(/RichTextField/);
    // The scheme allowlist reminder is present.
    expect(src).toMatch(/http.*https.*mailto.*tel/is);
  });

  it("widget stays dependency-free — no import / require / DOMPurify",
      () => {
    const src = readSrc(WIDGET_PATH);
    // No ESM imports.
    expect(src).not.toMatch(/^\s*import\s+/m);
    // No CommonJS requires.
    expect(src).not.toMatch(/require\s*\(\s*["']/);
    // No DOMPurify smuggling — dep-free contract. Test targets an
    // actual import/require call, NOT the negative-guidance mention
    // in the top-of-file security comment which explicitly notes
    // "DOMPurify is intentionally NOT bundled here".
    expect(src.toLowerCase()).not.toMatch(/import\s+.*dompurify/);
    expect(src.toLowerCase()).not.toMatch(/require\s*\(\s*["']dompurify/);
    // No emergent-integrations or other bundled dep imports.
    expect(src).not.toMatch(/from ["'](@\w|\.\/|\.\.\/)/);
  });
});


// ═══════════════════════════════════════════════════════════════
// 2) ThemedFormShell — hero prop renders a hero band above children
// ═══════════════════════════════════════════════════════════════
describe("Phase 4 · <ThemedFormShell> hero band parity", () => {
  it("hero == null → no hero DOM emitted (backwards-compat)", () => {
    render(
      <ThemedFormShell theme={null} testid="shell-null-hero">
        <span data-testid="child-a">hi</span>
      </ThemedFormShell>,
    );
    expect(screen.getByTestId("shell-null-hero")).toBeTruthy();
    expect(screen.getByTestId("child-a")).toBeTruthy();
    // Hero band absent.
    expect(screen.queryByTestId("themed-hero-band")).toBeNull();
    expect(screen.queryByTestId("themed-hero-heading")).toBeNull();
    cleanup();
  });

  it("color-bg hero renders heading + subheading above children", () => {
    render(
      <ThemedFormShell
        theme={null}
        hero={{
          heading_html: "<strong>Free inspection</strong>",
          subheading_html: "<p>24hr response guaranteed.</p>",
          background: { kind: "color", color: "#FEF3C7" },
          badge: null,
        }}
        testid="shell-color-hero"
      >
        <span data-testid="child-b">hi</span>
      </ThemedFormShell>,
    );
    const band = screen.getByTestId("themed-hero-band");
    expect(band).toBeTruthy();
    expect(band.getAttribute("data-hero-kind")).toBe("color");
    const heading = screen.getByTestId("themed-hero-heading");
    expect(heading.innerHTML).toContain("Free inspection");
    expect(screen.getByTestId("themed-hero-subheading")).toBeTruthy();
    // No badge, no overlay.
    expect(screen.queryByTestId("themed-hero-badge")).toBeNull();
    expect(screen.queryByTestId("themed-hero-overlay")).toBeNull();
    // Child still rendered.
    expect(screen.getByTestId("child-b")).toBeTruthy();
    cleanup();
  });

  it("image-bg hero with overlay_opacity renders an overlay layer + badge",
      () => {
    render(
      <ThemedFormShell
        theme={null}
        hero={{
          heading_html: "<p>Hi</p>",
          subheading_html: "",
          background: {
            kind: "image",
            url: "https://cdn.example.com/pool.jpg",
            overlay_opacity: 40,
          },
          badge: {
            url: "https://cdn.example.com/badge.png",
            alt_text: "20% off",
          },
        }}
        testid="shell-image-hero"
      >
        <span>x</span>
      </ThemedFormShell>,
    );
    const band = screen.getByTestId("themed-hero-band");
    expect(band.getAttribute("data-hero-kind")).toBe("image");
    const overlay = screen.getByTestId("themed-hero-overlay");
    expect(overlay.getAttribute("style")).toMatch(/rgba\(0,\s*0,\s*0,\s*0\.40?\)/);
    const badge = screen.getByTestId("themed-hero-badge");
    expect(badge.getAttribute("src")).toBe("https://cdn.example.com/badge.png");
    expect(badge.getAttribute("alt")).toBe("20% off");
    cleanup();
  });

  it("gradient-bg hero applies linear-gradient inline style", () => {
    render(
      <ThemedFormShell
        theme={null}
        hero={{
          heading_html: "<p>Hi</p>",
          subheading_html: "",
          background: {
            kind: "gradient",
            angle_deg: 45,
            from: "#0EA5E9",
            to:   "#1B1F5C",
          },
          badge: null,
        }}
        testid="shell-gradient-hero"
      >
        <span>x</span>
      </ThemedFormShell>,
    );
    const band = screen.getByTestId("themed-hero-band");
    expect(band.getAttribute("data-hero-kind")).toBe("gradient");
    expect(band.getAttribute("style"))
      .toMatch(/linear-gradient\(45deg,\s*#0EA5E9 0%,\s*#1B1F5C 100%\)/);
    cleanup();
  });

  it("source-lint · ThemedFormShell documents Phase 4 hero addition + XSS boundary",
      () => {
    const src = readSrc(SHELL_PATH);
    expect(src).toMatch(/Phase 4/);
    expect(src).toMatch(/hero/);
    expect(src).toMatch(/dangerouslySetInnerHTML/);
    expect(src).toMatch(/RichTextField/);
    // Column-span documentation — explicit note that it does NOT
    // apply on the React path.
    expect(src).toMatch(/column_span/);
  });
});


// ═══════════════════════════════════════════════════════════════
// 3) PublicLeadIntake — reads form_hero + passes it to the shell
// ═══════════════════════════════════════════════════════════════
describe("Phase 4 · PublicLeadIntake hero wiring", () => {
  it("reads form_hero from __TENANT_CONFIG__ + passes hero prop to ThemedFormShell",
      () => {
    const src = readSrc(INTAKE_PATH);
    // State + reader.
    expect(src).toMatch(/const \[hero, setHero\]\s*=\s*useState\(null\)/);
    expect(src).toMatch(/window\.__TENANT_CONFIG__\?\.form_hero/);
    // Forwards to the shell.
    expect(src).toMatch(/<ThemedFormShell[^>]*\n?\s*hero=\{hero\}/);
    // Design-note comment lives in the source and explicitly calls
    // out that column_span is NOT applied on this page.
    expect(src).toMatch(/column_span/);
    expect(src).toMatch(/hardcoded/);
  });
});
