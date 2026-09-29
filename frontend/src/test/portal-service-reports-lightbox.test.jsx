/**
 * DTP-2 · Feb-2026 — PortalServiceReports lightbox wire-up.
 *
 * Source-grep contract:
 *   * The detail export imports the shared ``<Lightbox>`` component.
 *   * The lightbox testid prefix ``portal-service-reports-lightbox``
 *     is present so downstream selectors keep resolving.
 *   * The photo / job-photo buttons open a shared state (no inline
 *     modal remains in the source).
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

const SRC = fs.readFileSync(
  path.resolve(process.cwd(), "src/pages/portal/PortalServiceReports.jsx"),
  "utf-8",
);

describe("PortalServiceReports · DTP-2 shared Lightbox wire-up", () => {
  it("imports the shared Lightbox component from @/components/portal", () => {
    expect(SRC).toMatch(
      /import\s+Lightbox\s+from\s+['"]@\/components\/portal\/Lightbox['"]/,
    );
  });

  it("mounts <Lightbox testidPrefix=\"portal-service-reports-lightbox\">", () => {
    expect(SRC).toMatch(/testidPrefix=["']portal-service-reports-lightbox["']/);
  });

  it("no longer contains an inline lightbox / zoom overlay", () => {
    // The pre-DTP-2 wiring rendered its own ``fixed inset-0`` modal
    // with a hand-rolled backdrop.  After the sweep every media
    // overlay flows through the shared component.
    const inlineOverlays = SRC.match(
      /className=["'][^"']*fixed\s+inset-0[^"']*["'][^>]*data-testid=["']portal-service-report-[a-z-]*(?:modal|lightbox|zoom)["']/g,
    ) || [];
    expect(inlineOverlays.length).toBe(0);
  });

  it("wires both jobPhotos and photos click handlers through the shared index state", () => {
    // A single index sequences [jobPhotos..., visitorPhotos...] so the
    // shared Lightbox addresses either grid.
    expect(SRC).toMatch(/setLightboxIdx\(i\)/);
    expect(SRC).toMatch(/setLightboxIdx\(jobPhotos\.length \+ i\)/);
  });
});
