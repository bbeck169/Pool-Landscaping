/**
 * Phase 19 · Feature 4 — portal page shell: FLAGGED NO-OP on mobile.
 *
 * Web Phase 18b (da5c45b74 / fa0562924 / b6b15bf96) added
 * PortalPageShell because web portal sub-pages render dark-on-dark on
 * the navy ``.portal-dark`` page background.  Mobile portal screens
 * render on the light theme tokens (``colors.surfaceSecondary`` /
 * ``colors.surface``) with ``colors.onSurface`` text, so the
 * readability bug does not exist and no shell was added.
 *
 * Regression lock: if any portal screen root ever moves to a dark
 * background, this fails and the shell question must be revisited.
 */
import * as fs from "fs";
import * as path from "path";
import { colors } from "@/src/theme";

const PORTAL_DIR = path.join(__dirname, "..", "app", "portal");

function portalScreens(dir = PORTAL_DIR, out: string[] = []): string[] {
  for (const f of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, f.name);
    if (f.isDirectory()) portalScreens(p, out);
    else if (/\.tsx$/.test(f.name) && f.name !== "_layout.tsx") out.push(p);
  }
  return out;
}

function luminance(hex: string): number {
  const h = hex.replace("#", "");
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

describe("Phase 19 · mobile portal readability (shell not needed)", () => {
  it("light theme tokens back every portal page + dark body text", () => {
    expect(luminance(colors.surfaceSecondary)).toBeGreaterThan(0.85);
    expect(luminance(colors.surface)).toBeGreaterThan(0.85);
    expect(luminance(colors.onSurface)).toBeLessThan(0.15);
  });

  it("every portal screen root uses a light surface token (no navy page bg)", () => {
    const files = portalScreens();
    expect(files.length).toBeGreaterThan(15);
    const offenders: string[] = [];
    for (const f of files) {
      const src = fs.readFileSync(f, "utf8");
      const m = src.match(/\n\s+root:\s*\{[^}]*backgroundColor:\s*([^,}\n]+)/);
      if (!m) continue; // screen without a root style (re-export / redirect)
      const bg = m[1].trim();
      if (!/^colors\.(surface|surfaceSecondary)$/.test(bg)) offenders.push(`${path.basename(f)} → ${bg}`);
    }
    expect(offenders).toEqual([]);
  });

  it("no PortalPageShell was introduced on mobile", () => {
    const hits = portalScreens().filter((f) => fs.readFileSync(f, "utf8").includes("PortalPageShell"));
    expect(hits).toEqual([]);
  });
});
