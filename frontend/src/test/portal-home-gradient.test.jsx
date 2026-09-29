/**
 * DTP-2 · Feb-2026 — PortalHome hero-gradient contract.
 *
 * The pre-DTP-2 hero card used the standard ``gradients.navyToGreen``
 * (blue→green) background. DTP-1 introduced ``portalGradients.navyToBlue``
 * — a portal-scoped deep-navy→blue sweep — and PortalHome now consumes
 * it so the hero reads correctly against the dark portal background.
 *
 * Source-grep contract:
 *   * PortalHome imports ``portalGradients`` from ``@/theme``.
 *   * The hero card style uses ``portalGradients.navyToBlue.css``.
 *   * The hero element carries the ``portal-hero`` testid (unchanged).
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

const SRC = fs.readFileSync(
  path.resolve(process.cwd(), "src/pages/portal/PortalHome.jsx"),
  "utf-8",
);

describe("PortalHome · DTP-2 hero uses portalGradients.navyToBlue", () => {
  it("imports portalGradients from @/theme", () => {
    expect(SRC).toMatch(
      /import\s*\{[^}]*portalGradients[^}]*\}\s*from\s*['"]@\/theme['"]/,
    );
  });

  it("hero card renders portalGradients.navyToBlue.css as its background", () => {
    // The hero <div data-testid="portal-hero"> paints
    // ``portalGradients.navyToBlue.css`` inline.
    expect(SRC).toMatch(/portalGradients\.navyToBlue\.css/);
  });

  it("retains the portal-hero testid so downstream selectors still resolve", () => {
    expect(SRC).toMatch(/data-testid=["']portal-hero["']/);
  });

  it("no longer paints the hero with the sitewide navyToGreen gradient", () => {
    // The hero styled block should NOT resolve to
    // ``gradients.navyToGreen.css`` — that gradient is reserved for
    // admin CTAs and inline hero-CTA rows further down the page.
    const heroBlock = SRC.match(
      /data-testid=["']portal-hero["'][\s\S]{0,400}/,
    );
    expect(heroBlock).toBeTruthy();
    expect(heroBlock[0]).not.toMatch(/gradients\.navyToGreen\.css/);
  });
});
