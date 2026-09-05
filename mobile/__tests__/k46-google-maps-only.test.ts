// Phase K46 · Feb-2026 — Google-only maps migration jest guards.
//
// Locks in the K46 landing state at the Jest layer so any accidental
// re-introduction of @rnmapbox/maps or HERE surfaces fails the
// mobile test suite as well as the vitest suite. Complements
// ``frontend/src/test/phase38b-live-pins.test.jsx``.

import { readFileSync, existsSync } from "fs";
import { resolve } from "path";

const ROOT = resolve(__dirname, "..");
const R = (rel: string): string =>
  existsSync(resolve(ROOT, rel))
    ? readFileSync(resolve(ROOT, rel), "utf8")
    : "";

describe("K46 · Mapbox purge", () => {
  it("package.json no longer lists @rnmapbox/maps", () => {
    const pkg = R("package.json");
    expect(pkg).not.toMatch(/"@rnmapbox\/maps"\s*:/);
  });

  it("app.config.js no longer registers the @rnmapbox/maps plugin", () => {
    const cfg = R("app.config.js");
    // Strip line-comments before scanning — the migration note
    // legitimately mentions the removed module by name.
    const stripped = cfg.replace(/\/\/[^\n]*\n/g, "\n").replace(/\/\*[\s\S]*?\*\//g, "");
    // Either bare-string or tuple registration would fail the guard.
    expect(stripped).not.toMatch(/["'`]@rnmapbox\/maps["'`]/);
  });

  it("app.config.js no longer plumbs mapboxToken into extra", () => {
    const cfg = R("app.config.js");
    expect(cfg).not.toMatch(/mapboxToken:\s*process\.env\.EXPO_PUBLIC_MAPBOX_TOKEN/);
  });

  it("app/_layout.tsx removed the Mapbox dev-mode placeholder guard", () => {
    const layout = R("app/_layout.tsx");
    expect(layout).not.toContain("EXPO_PUBLIC_MAPBOX_TOKEN");
  });
});

describe("K46 · LiveTechPinsMap on react-native-maps", () => {
  const src = R("src/components/dispatch/LiveTechPinsMap.tsx");

  it("imports from react-native-maps with PROVIDER_GOOGLE", () => {
    expect(src).toMatch(/from\s+["']react-native-maps["']/);
    expect(src).toContain("PROVIDER_GOOGLE");
  });

  it("does not import @rnmapbox/maps or reference MapboxGL", () => {
    // Match only real import/require statements — the file docstring
    // may legitimately reference @rnmapbox/maps in the migration
    // rationale comment.
    expect(src).not.toMatch(/require\(["']@rnmapbox\/maps["']\)/);
    expect(src).not.toMatch(/from\s+["']@rnmapbox\/maps["']/);
    expect(src).not.toContain("MapboxGL");
  });

  it("uses hasGoogleMapsKey() for the missing-key guard", () => {
    expect(src).toContain("hasGoogleMapsKey");
  });

  it("cycles Google mapType values (standard / satellite / hybrid)", () => {
    expect(src).toContain("standard");
    expect(src).toContain("satellite");
    expect(src).toContain("hybrid");
  });
});

describe("K46 · LiveTechPinsWrapper static import", () => {
  const src = R("src/components/dispatch/LiveTechPinsWrapper.tsx");

  it("statically imports the map (no try/catch require)", () => {
    expect(src).toMatch(
      /import\s+LiveTechPinsMap[\s\S]*?from\s+["']@\/src\/components\/dispatch\/LiveTechPinsMap["']/,
    );
    expect(src).not.toMatch(
      /try\s*\{[\s\S]*require\(["']@\/src\/components\/dispatch\/LiveTechPinsMap["']\)/,
    );
  });
});

describe("K46 · Native nav helper wired into Navigate buttons", () => {
  it("NavigateJobButton uses openNativeNavTo", () => {
    const src = R("src/components/schedule/NavigateJobButton.tsx");
    expect(src).toContain("openNativeNavTo");
    expect(src).toMatch(/from\s+["']@\/src\/utils\/nativeNav["']/);
  });

  it("DailyRouteMap callout has a Navigate button using openNativeNavTo", () => {
    const src = R("src/components/schedule/DailyRouteMap.native.tsx");
    expect(src).toContain("openNativeNavTo");
    expect(src).toContain("schedule-daily-route-map-callout-navigate");
  });
});
