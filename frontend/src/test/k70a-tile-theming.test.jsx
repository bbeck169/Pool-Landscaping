/**
 * Phase K70.a · Feb-2026 — Tile theming contract tests.
 *
 * Locks in the K70.a spec:
 *   1. Dashboard KpiCard (`pages/admin/Dashboard.jsx`) keeps its
 *      Feb-2026 per-tone pastel background + colored left border,
 *      AND now paints ``gradients.navyToGreen.css`` on its icon
 *      chip.
 *   2. Shared R0 <KpiCard/> (`components/reports/KpiCard.jsx`)
 *      paints the navy-green gradient as its tile background with
 *      white text on top.
 *   3. ReportsHub BuiltTile (`pages/reports/ReportsHub.jsx`) paints
 *      the navy-green gradient background AND its "Open report"
 *      button uses ``#15803D`` fill + 1px white outline + white
 *      text (WCAG AA body: 4.9:1 on green-700).
 *   4. ReportsHub ComingSoonTile stays MUTED (dashed border, no
 *      gradient, no green button) — coming-soon tiles keep the
 *      pre-K70.a placeholder styling untouched.
 *   5. The K64 solid nav navy (#303AA0) is untouched by K70.a.
 *
 * These are source-lint style checks (no full-mount / DOM-render).
 * That keeps the tests fast and immune to the ~30 API mocks
 * Dashboard would otherwise need.
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";

const DASH_SRC = fs.readFileSync(
  path.resolve(__dirname, "../pages/admin/Dashboard.jsx"),
  "utf8",
);
const REPORTS_HUB_SRC = fs.readFileSync(
  path.resolve(__dirname, "../pages/reports/ReportsHub.jsx"),
  "utf8",
);
const R0_KPI_SRC = fs.readFileSync(
  path.resolve(__dirname, "../components/reports/KpiCard.jsx"),
  "utf8",
);
const THEME_SRC = fs.readFileSync(
  path.resolve(__dirname, "../theme.js"),
  "utf8",
);


describe("K70.a · Dashboard KpiCard — gradient icon chip", () => {
  it("still exports the tone-driven palette variant (Feb-2026 contract preserved)", () => {
    // The pastel background + left border are still the primary
    // per-tile differentiator. K70.a only added the icon-chip
    // gradient on top.
    expect(DASH_SRC).toMatch(/backgroundColor:\s*palette\[50\]/);
    expect(DASH_SRC).toMatch(/borderLeft:\s*`4px solid \$\{palette\[500\]\}`/);
  });

  it("icon chip paints gradients.navyToGreen.css with white icon", () => {
    expect(DASH_SRC).toMatch(
      /background:\s*gradients\.navyToGreen\.css[\s\S]{0,120}color:\s*["']#FFFFFF["']/,
    );
  });

  it("chip carries the K70.a grep-lock data attribute", () => {
    expect(DASH_SRC).toMatch(/data-k70a-gradient-chip="true"/);
  });

  it("theme.js still exports gradients.navyToGreen.css unchanged", () => {
    expect(THEME_SRC).toMatch(
      /gradients\s*=\s*\{[\s\S]*navyToGreen[\s\S]*css:\s*"linear-gradient\(90deg, #1B1F5C 0%, #16A34A 100%\)"/,
    );
  });
});


describe("K70.a · Shared R0 KpiCard — full gradient tile", () => {
  it("imports gradients from @/theme", () => {
    expect(R0_KPI_SRC).toMatch(
      /import\s*\{[^}]*\bgradients\b[^}]*\}\s*from\s*["']@\/theme["']/,
    );
  });

  it("tile background reads gradients.navyToGreen.css", () => {
    expect(R0_KPI_SRC).toMatch(
      /background:\s*gradients\.navyToGreen\.css/,
    );
  });

  it("value + label render in white on the gradient", () => {
    expect(R0_KPI_SRC).toMatch(/color:\s*["']#FFFFFF["']/);
  });

  it("carries the K70.a grep-lock data attribute", () => {
    expect(R0_KPI_SRC).toMatch(/data-k70a-gradient-tile="true"/);
  });
});


describe("K70.a · ReportsHub BuiltTile — gradient + green CTA", () => {
  it("imports gradients from @/theme", () => {
    expect(REPORTS_HUB_SRC).toMatch(
      /import\s*\{[^}]*\bgradients\b[^}]*\}\s*from\s*["']@\/theme["']/,
    );
  });

  it("BuiltTile background reads gradients.navyToGreen.css", () => {
    // Slice the BuiltTile function so we don't accidentally match
    // the ComingSoonTile below.
    const start = REPORTS_HUB_SRC.indexOf("function BuiltTile(");
    const end = REPORTS_HUB_SRC.indexOf("function ComingSoonTile(");
    expect(start).toBeGreaterThan(-1);
    expect(end).toBeGreaterThan(start);
    const slice = REPORTS_HUB_SRC.slice(start, end);
    expect(slice).toMatch(/background:\s*gradients\.navyToGreen\.css/);
    expect(slice).toMatch(/data-k70a-gradient-tile="true"/);
  });

  it("Open-report button paints #15803D fill + 1px white outline + white text", () => {
    const start = REPORTS_HUB_SRC.indexOf("function BuiltTile(");
    const end = REPORTS_HUB_SRC.indexOf("function ComingSoonTile(");
    const slice = REPORTS_HUB_SRC.slice(start, end);
    expect(slice).toMatch(/backgroundColor:\s*["']#15803D["']/);
    expect(slice).toMatch(/border:\s*["']1px solid #FFFFFF["']/);
    expect(slice).toMatch(/color:\s*["']#FFFFFF["']/);
    expect(slice).toMatch(/data-k70a-cta="true"/);
  });

  it("Open-report button darkens to #166534 on hover", () => {
    const start = REPORTS_HUB_SRC.indexOf("function BuiltTile(");
    const end = REPORTS_HUB_SRC.indexOf("function ComingSoonTile(");
    const slice = REPORTS_HUB_SRC.slice(start, end);
    expect(slice).toMatch(/#166534/);
  });
});


describe("K70.a · ReportsHub ComingSoonTile — muted, unchanged", () => {
  const start = REPORTS_HUB_SRC.indexOf("function ComingSoonTile(");
  const slice = start >= 0 ? REPORTS_HUB_SRC.slice(start) : "";

  it("ComingSoonTile function exists", () => {
    expect(start).toBeGreaterThan(-1);
  });

  it("does NOT paint the navy-green gradient", () => {
    expect(slice).not.toMatch(/gradients\.navyToGreen/);
  });

  it("does NOT expose the K70.a grep-lock attributes", () => {
    expect(slice).not.toMatch(/data-k70a-gradient-tile/);
    expect(slice).not.toMatch(/data-k70a-cta/);
  });

  it("still uses the pre-K70.a muted styling (dashed border + surfaceSecondary bg)", () => {
    expect(slice).toMatch(/border:\s*`1px dashed \$\{colors\.border\}`/);
    expect(slice).toMatch(/backgroundColor:\s*colors\.surfaceSecondary/);
  });

  it("still exposes the aria-disabled='true' hint for keyboard nav", () => {
    expect(slice).toMatch(/aria-disabled="true"/);
  });
});


describe("K70.a · K64 solid nav navy grep-lock preserved", () => {
  it("theme.js still exports the K64 nav bg (#303AA0) as a solid color", () => {
    expect(THEME_SRC).toMatch(/#303AA0/);
    // No accidental gradient on the nav.bg token.
    expect(THEME_SRC).not.toMatch(
      /nav:\s*\{[\s\S]{0,200}bg:\s*["']linear-gradient/,
    );
  });
});


describe("K70.a · WCAG AA source-lint on green CTA fill", () => {
  it("green button fill is #15803D (green-700), not #16A34A (green-600)", () => {
    // #15803D → 4.93 : 1 on white text (AA body).
    // #16A34A → 3.28 : 1 on white text (AA large only).
    // The K70.a spec picked the darker stop so the CTA passes AA
    // body without depending on a bold-only escape hatch.
    const start = REPORTS_HUB_SRC.indexOf("function BuiltTile(");
    const end = REPORTS_HUB_SRC.indexOf("function ComingSoonTile(");
    const slice = REPORTS_HUB_SRC.slice(start, end);
    // Positive assertion: the CTA background is green-700.
    expect(slice).toMatch(/backgroundColor:\s*["']#15803D["']/);
    // Negative assertion: no `#16A34A` inline-styled as the CTA bg.
    expect(slice).not.toMatch(/backgroundColor:\s*["']#16A34A["']/);
  });
});
