/**
 * DTP-2 · Feb-2026 — PortalVideosPage (service-report videos)
 * shared-Lightbox wire-up guard.
 *
 * Source-grep contract:
 *   * Imports the shared ``<Lightbox>`` component.
 *   * Mounts it with ``testidPrefix="portal-video-modal"`` so the
 *     legacy ``portal-video-modal`` / ``portal-video-modal-close``
 *     testids continue to resolve.
 *   * No inline modal player remains in the source.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

const SRC = fs.readFileSync(
  path.resolve(process.cwd(), "src/pages/portal/PortalVideosPage.jsx"),
  "utf-8",
);

describe("PortalVideosPage · DTP-2 shared Lightbox wire-up", () => {
  it("imports Lightbox from @/components/portal/Lightbox", () => {
    expect(SRC).toMatch(
      /import\s+Lightbox\s+from\s+['"]@\/components\/portal\/Lightbox['"]/,
    );
  });

  it("mounts <Lightbox testidPrefix=\"portal-video-modal\">", () => {
    expect(SRC).toMatch(/testidPrefix=["']portal-video-modal["']/);
  });

  it("uses kind=\"video\" for every lightbox item", () => {
    expect(SRC).toMatch(/kind:\s*["']video["']/);
  });

  it("drops the pre-DTP-2 inline modal player", () => {
    // The pre-DTP-2 wiring rendered its own ``fixed inset-0`` overlay.
    // After the sweep, the only ``<Lightbox>`` mount is the shared
    // component below.
    const legacy = SRC.match(
      /data-testid=["']portal-video-modal["'][^>]*>\s*<button/,
    ) || [];
    expect(legacy.length).toBe(0);
  });

  it("imports portalColors as colors (dark palette)", () => {
    expect(SRC).toMatch(
      /import\s*\{[^}]*portalColors\s+as\s+colors[^}]*\}\s*from\s*['"]@\/theme['"]/,
    );
  });
});
