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
 *
 * Phase 25 (re-issue) · web parity e2a0d8a2e — Portal HOME is now
 * intentionally dark navy (#03002e) with its text flipped to light.
 * It is exempt from the light-root rule and instead locked as
 * dark-CONSISTENT (no light-theme text tokens left in its styles,
 * i.e. no dark-on-dark).
 */
import * as fs from "fs";
import * as path from "path";
import { colors } from "@/src/theme";

const PORTAL_DIR = path.join(__dirname, "..", "app", "portal");
const DARK_HOME = path.join(PORTAL_DIR, "home.tsx");

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
      if (f === DARK_HOME) continue; // Phase 25 — intentionally dark
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

  it("Phase 25 · portal home is dark-consistent: navy root, light text, no light text tokens", () => {
    const src = fs.readFileSync(DARK_HOME, "utf8");
    expect(src).toMatch(/const PORTAL_DARK_BG = "#03002e";/);
    expect(src).toMatch(/const PORTAL_DARK_BORDER = "#1E293B";/);
    const styles = src.slice(src.indexOf("const s = StyleSheet.create({"));
    expect(styles).toMatch(/\n\s+root:\s*\{[^}]*backgroundColor:\s*PORTAL_DARK_BG/);
    expect(styles).not.toMatch(/color:\s*colors\.(onSurface|onSurfaceSecondary|muted)\b/);
    expect(styles).not.toMatch(/backgroundColor:\s*colors\.(surface|surfaceSecondary)\b/);
  });
});
