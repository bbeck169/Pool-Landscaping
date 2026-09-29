/**
 * DTP-2b · Feb-2026 — PortalWalkthrough Lightbox-wiring audit.
 *
 * The DTP-2b brief listed PortalWalkthrough alongside the shared
 * ``<Lightbox>`` migration. On inspection the file is a 12-step
 * guided-tour engine that renders spotlight overlays over anchor
 * elements — there are NO photo / video grids inside the tour
 * chrome to feed into the shared lightbox.  This test records the
 * audit outcome so the per-page Lightbox sweep is complete and the
 * contract is grep-locked: if any future revision adds a photo
 * grid to the tour, one of these assertions will flip and force
 * a follow-up phase to wire the shared component.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

const SRC = fs.readFileSync(
  path.resolve(process.cwd(), "src/pages/portal/PortalWalkthrough.jsx"),
  "utf-8",
);

describe("PortalWalkthrough · DTP-2b Lightbox audit", () => {
  it("is a tour engine — declares a STEPS array of step descriptors", () => {
    expect(SRC).toMatch(/const\s+STEPS\s*=\s*\[/);
  });

  it("renders spotlight + tooltip chrome, not a media grid", () => {
    expect(SRC).toMatch(/data-testid=["']portal-tour-spotlight["']/);
    expect(SRC).toMatch(/data-testid=["']portal-tour-tooltip["']/);
  });

  it("does NOT wire the shared <Lightbox> — no photo/video grid to display", () => {
    // If a future revision adds photo/video grids to the tour, this
    // assertion is the trigger to wire the shared component with
    // ``testidPrefix="portal-walkthrough-lightbox"``.
    expect(SRC).not.toMatch(
      /from\s+['"]@\/components\/portal\/Lightbox['"]/,
    );
    expect(SRC).not.toMatch(/<img|jobPhotos|visitorPhotos|<video/);
  });

  it("carries no bare ``colors`` import — page rides Tailwind atomics remapped by portal-dark.css", () => {
    // Sweep contract escape-hatch — Tailwind-only pages satisfy the
    // grep guard via ``portal-dark.css`` remaps rather than a
    // ``portalColors as colors`` import.
    expect(SRC).not.toMatch(
      /import\s*\{[^}]*(^|[,\s{])colors\b[^}]*\}\s*from\s*['"]@\/theme['"]/,
    );
  });
});
