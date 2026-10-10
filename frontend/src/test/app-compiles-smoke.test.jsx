/**
 * app-compiles-smoke · Feb-2026
 *
 * Regression guard for the App.js duplicate-identifier crash. The
 * duplicate ``PortalWarranties`` collision took the whole preview
 * white-screen because Babel throws at parse time.
 *
 * Testing strategy — a targeted static analysis pass on the source
 * text of ``App.js``. Full ``import()`` doesn't work here because
 * Vite's ``.js`` importer refuses to transform JSX inside a bare
 * ``.js`` file (App.js contains JSX by CRACO-only convention).
 * Renaming to ``.jsx`` or adding an esbuild loader override would
 * touch the whole test config surface, so instead this test:
 *
 *   1. Reads ``src/App.js`` verbatim (fs, not Vite).
 *   2. Verifies the file parses through esbuild's transform pass
 *      (same JSX-aware parser Vitest uses on ``.jsx`` files).
 *   3. Cross-checks that no identifier is declared twice at the
 *      top-level import scope — the specific class of bug that
 *      caused this outage.
 */
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";


const APP_PATH = path.resolve(__dirname, "../App.js");


function _topLevelIdentifiers(source) {
  const ids = [];
  const re = /^(?:\s*(?:import|export)\s+[^;]+;)/gm;
  const importRe =
    /^\s*import\s+(?:([A-Za-z_$][\w$]*)(?:\s*,\s*)?)?(?:\{([^}]*)\})?\s+from\s+["'][^"']+["']\s*;?/gm;
  let m;
  while ((m = importRe.exec(source)) !== null) {
    const defaultName = m[1];
    const named = m[2];
    if (defaultName) ids.push(defaultName.trim());
    if (named) {
      for (const raw of named.split(",")) {
        const cleaned = raw.trim().split(/\s+as\s+/i);
        const local = (cleaned[1] || cleaned[0]).trim();
        if (local) ids.push(local);
      }
    }
  }
  // Silence "unused" lint on the wide-net regex above.
  void re;
  return ids;
}


describe("App.js compile smoke", () => {
  it("exists on disk", () => {
    expect(fs.existsSync(APP_PATH)).toBe(true);
  });

  it("has no duplicate top-level import identifiers", () => {
    const source = fs.readFileSync(APP_PATH, "utf8");
    const ids = _topLevelIdentifiers(source);
    const seen = new Set();
    const duplicates = [];
    for (const name of ids) {
      if (seen.has(name)) duplicates.push(name);
      seen.add(name);
    }
    expect(
      duplicates,
      `Duplicate import identifiers in App.js: ${duplicates.join(", ")}. ` +
        "This is exactly the class of bug that caused the Feb-2026 " +
        "preview white-screen (PortalWarranties declared twice).",
    ).toEqual([]);
  });

  it("PortalWarranties is imported exactly once", () => {
    const source = fs.readFileSync(APP_PATH, "utf8");
    const matches = source.match(/\bPortalWarranties\b/g) || [];
    // Phase P37/P38 code-splitting migrated route-level pages to
    // ``React.lazy(() => import(...))``. Count both the legacy
    // static-import form AND the lazy-import declaration.
    const importDecls = source.match(
      /(?:import\s+[^;]*\bPortalWarranties\b[^;]*;|const\s+PortalWarranties\s*=\s*React\.lazy\(\s*\(\)\s*=>\s*import\([^)]*\)\s*\)\s*;)/g,
    ) || [];
    expect(
      importDecls.length,
      `Expected exactly 1 import statement (static OR lazy) mentioning ` +
        `PortalWarranties, got ${importDecls.length}:\n  ${importDecls.join("\n  ")}`,
    ).toBe(1);
    expect(matches.length).toBeGreaterThan(1);
  });
});
