/**
 * DTP-2 · Feb-2026 — PortalVideos (shareable-videos surface)
 * shared-Lightbox wire-up guard.
 *
 * Source-grep contract:
 *   * Imports the shared ``<Lightbox>`` component.
 *   * Mounts it with ``testidPrefix="portal-video-lightbox"`` so the
 *     legacy ``portal-video-lightbox`` / ``portal-video-lightbox-video``
 *     testids continue to resolve.
 *   * No pre-DTP-2 inline modal remains in the source.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

const SRC = fs.readFileSync(
  path.resolve(process.cwd(), "src/pages/portal/PortalVideos.jsx"),
  "utf-8",
);

describe("PortalVideos · DTP-2 shared Lightbox wire-up", () => {
  it("imports Lightbox from @/components/portal/Lightbox", () => {
    expect(SRC).toMatch(
      /import\s+Lightbox\s+from\s+['"]@\/components\/portal\/Lightbox['"]/,
    );
  });

  it("mounts <Lightbox testidPrefix=\"portal-video-lightbox\">", () => {
    expect(SRC).toMatch(/testidPrefix=["']portal-video-lightbox["']/);
  });

  it("uses kind=\"video\" for every lightbox item", () => {
    expect(SRC).toMatch(/kind:\s*["']video["']/);
  });

  it("drops the pre-DTP-2 inline fixed-position modal player", () => {
    // The pre-DTP-2 wiring rendered its own ``fixed inset-0`` overlay
    // with a hand-rolled close button. After the sweep no inline
    // lightbox / modal wrapper remains.
    const legacy = SRC.match(
      /data-testid=["']portal-video-lightbox["'][^>]*>\s*<button/,
    ) || [];
    expect(legacy.length).toBe(0);
  });

  it("imports portalColors as colors (dark palette)", () => {
    expect(SRC).toMatch(
      /import\s*\{[^}]*portalColors\s+as\s+colors[^}]*\}\s*from\s*['"]@\/theme['"]/,
    );
  });
});
