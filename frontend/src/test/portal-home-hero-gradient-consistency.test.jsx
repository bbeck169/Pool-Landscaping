/**
 * DTP-2b · Feb-2026 — PortalHome hero gradient consistency.
 *
 * DTP-2 pilot-migrated only the hero card (line ~198) to the
 * portal-scoped ``portalGradients.navyToBlue.css`` gradient; three
 * additional sites (sticky top strip, inline request-service submit,
 * inline AI-composer send) still resolved through the legacy
 * ``gradients.navyToGreen.css`` token.  DTP-2b finishes the sweep
 * so the entire PortalHome surface reads on one consistent
 * portal-navy → brand-blue palette.  Guard: no ``navyToGreen.css``
 * token may appear in the PortalHome source.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

const SRC = fs.readFileSync(
  path.resolve(process.cwd(), "src/pages/portal/PortalHome.jsx"),
  "utf-8",
);

describe("PortalHome · DTP-2b hero gradient consistency", () => {
  it("does NOT reference gradients.navyToGreen.css anywhere in the source", () => {
    // The four hero-adjacent gradient sites (sticky strip, hero
    // card, request-service submit, AI-composer send) all resolve
    // through the portal-navy → brand-blue gradient after DTP-2b.
    expect(SRC).not.toMatch(/gradients\.navyToGreen\.css/);
  });

  it("has at least four sites bound to portalGradients.navyToBlue.css", () => {
    const matches = SRC.match(/portalGradients\.navyToBlue\.css/g) || [];
    expect(matches.length).toBeGreaterThanOrEqual(4);
  });
});
