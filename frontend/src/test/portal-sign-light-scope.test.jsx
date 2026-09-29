/**
 * DTP-2b · Feb-2026 — PortalSign light-scope carve-out guard.
 *
 * PortalSign is the print-oriented signature capture surface — the
 * pad + PDF preview must render on a white background so signatures
 * are legible on the printed page. The sweep migration explicitly
 * skipped this page and instead added a ``.portal-sign-scope`` CSS
 * carve-out inside ``portal-dark.css`` so, even if a future revision
 * mounts the signature page INSIDE the portal shell, the pad opts
 * BACK to the light palette.
 *
 * Three source-grep contracts:
 *   1. PortalSign is NOT bound to ``portalColors``.
 *   2. The ``.portal-sign-scope`` marker class IS wired on the root.
 *   3. ``portal-dark.css`` carries a matching carve-out rule.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

const SIGN_SRC = fs.readFileSync(
  path.resolve(process.cwd(), "src/pages/portal/PortalSign.jsx"),
  "utf-8",
);
const CSS_SRC = fs.readFileSync(
  path.resolve(process.cwd(), "src/styles/portal-dark.css"),
  "utf-8",
);

describe("PortalSign · DTP-2b light-scope carve-out", () => {
  it("stays on the light ``colors`` binding (no portalColors alias)", () => {
    expect(SIGN_SRC).not.toMatch(/portalColors\s+as\s+colors/);
    // And the file still consumes the light ``colors`` token so
    // signatures render on a white surface.
    expect(SIGN_SRC).toMatch(
      /import\s*\{[^}]*(^|[,\s{])colors\b[^}]*\}\s*from\s*['"]@\/theme['"]/,
    );
  });

  it("wires the ``portal-sign-scope`` marker class on the root", () => {
    expect(SIGN_SRC).toMatch(/portal-sign-scope/);
  });

  it("portal-dark.css defines a ``.portal-sign-scope`` white-background rule", () => {
    // Match either ``background: #FFFFFF`` (with or without ``!important``)
    // or ``background: white`` inside the ``.portal-sign-scope`` block.
    const rule = CSS_SRC.match(
      /\.portal-dark\s+\.portal-sign-scope\s*\{[^}]*background\s*:\s*(#FFFFFF|white)[^}]*\}/i,
    );
    expect(rule).not.toBeNull();
  });
});
