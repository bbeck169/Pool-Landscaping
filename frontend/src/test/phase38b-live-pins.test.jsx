// Phase 38b · Feb-2026 — Live Tech Pins map source-inspection.

import { readFileSync, existsSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";

const MOBILE = resolve(__dirname, "../../../mobile");
const F = (rel) => resolve(MOBILE, rel);
const R = (rel) => existsSync(F(rel)) ? readFileSync(F(rel), "utf8") : "";

const PKG_PATH = F("package.json");
const APP_JSON = F("app.json");
const ENV_FILE = F(".env");
const BOARD = F("app/(app)/dispatch/board.tsx");
const MAP = F("src/components/dispatch/LiveTechPinsMap.tsx");
const WRAP = F("src/components/dispatch/LiveTechPinsWrapper.tsx");
const RUNBOOK = F("EXPO_GO_RUNBOOK.md");

describe("Phase 38b · Mapbox dep + config", () => {
  const pkg = readFileSync(PKG_PATH, "utf8");
  const app = readFileSync(APP_JSON, "utf8");

  it("adds @rnmapbox/maps@^10.1.x to mobile/package.json", () => {
    expect(pkg).toMatch(/"@rnmapbox\/maps"\s*:\s*"\^?10\.1\./);
  });

  it("registers the @rnmapbox/maps expo config plugin in app.json", () => {
    expect(app).toContain('"@rnmapbox/maps"');
    expect(app).toContain('$EXPO_PUBLIC_MAPBOX_TOKEN');
  });

  it("exposes the token to Constants.expoConfig.extra.mapboxToken", () => {
    expect(app).toContain('"extra"');
    expect(app).toContain('"mapboxToken"');
  });

  it("adds the EXPO_PUBLIC_MAPBOX_TOKEN placeholder to mobile/.env", () => {
    const env = readFileSync(ENV_FILE, "utf8");
    expect(env).toMatch(/EXPO_PUBLIC_MAPBOX_TOKEN=/);
  });
});

describe("Phase 38b · Live pins map component (LiveTechPinsMap.tsx)", () => {
  const src = R("src/components/dispatch/LiveTechPinsMap.tsx");
  it("file exists", () => expect(existsSync(MAP)).toBe(true));
  it('imports the @rnmapbox/maps module', () => {
    expect(src).toMatch(/require\(["']@rnmapbox\/maps["']\)/);
  });
  it("cycles through three tile styles (streets / satellite / dark)", () => {
    expect(src).toContain("streets-v12");
    expect(src).toContain("satellite-streets-v12");
    expect(src).toContain("dark-v11");
  });
  it("persists the chosen style in AsyncStorage under dispatch_map_style_v1", () => {
    expect(src).toContain('"dispatch_map_style_v1"');
    expect(src).toMatch(/AsyncStorage\.(getItem|setItem)/);
  });
  it("reads the Mapbox token from EXPO_PUBLIC_MAPBOX_TOKEN or Constants.extra (never hardcoded)", () => {
    expect(src).toMatch(/EXPO_PUBLIC_MAPBOX_TOKEN/);
    expect(src).toMatch(/Constants\.expoConfig/);
    // Sanity: no obvious pk.xxxx literal that would leak a token.
    expect(src).not.toMatch(/pk\.[a-zA-Z0-9]{20,}/);
  });
  it("exposes the theme toggle testID + per-pin testIDs", () => {
    expect(src).toContain("dispatch-live-map-style-toggle");
    expect(src).toContain("dispatch-live-pin-");
  });
});

describe("Phase 38b · Wrapper (LiveTechPinsWrapper.tsx)", () => {
  const src = R("src/components/dispatch/LiveTechPinsWrapper.tsx");
  it("file exists", () => expect(existsSync(WRAP)).toBe(true));
  it("dynamic-requires the map inside try/catch (Expo Go safe)", () => {
    // Pattern: try { MapImpl = require(...) } catch { importError = ... }
    expect(src).toMatch(/try\s*\{[\s\S]*require\(["']@\/src\/components\/dispatch\/LiveTechPinsMap["']\)/);
    expect(src).toMatch(/catch\s*\(/);
  });
  it("renders the fallback banner testID when the map module is missing", () => {
    expect(src).toContain("dispatch-live-map-fallback");
    expect(src).toContain("EXPO_GO_RUNBOOK");
  });
  it("polls /gps/live-positions at 15s cadence", () => {
    expect(src).toContain("/gps/live-positions");
    expect(src).toMatch(/POLL_MS\s*=\s*15_?000/);
    expect(src).toMatch(/setInterval\(/);
  });
  it("uses useFocusEffect so polling only runs while the tab is focused", () => {
    expect(src).toMatch(/useFocusEffect\(/);
    expect(src).toMatch(/clearInterval\(/);
  });
  it("persists the collapsible expanded state under dispatch_map_expanded_v1", () => {
    expect(src).toContain('"dispatch_map_expanded_v1"');
  });
  it("carries the required testIDs (map, toggle, offline, no-token, strip)", () => {
    expect(src).toContain("dispatch-live-map");
    expect(src).toContain("dispatch-live-map-toggle");
    expect(src).toContain("dispatch-live-map-no-token");
    expect(src).toContain("dispatch-live-map-strip");
  });
  it("pin tap navigates to /dispatch/shift-route (ShiftRouteDialog)", () => {
    expect(src).toMatch(/pathname:\s*["']\/dispatch\/shift-route["']/);
  });
  it("does NOT use Alert.alert (Phase 30.4 root cause)", () => {
    expect(src).not.toMatch(/Alert\.alert\(/);
  });
});

describe("Phase 38b · Board wiring", () => {
  const src = R("app/(app)/dispatch/board.tsx");
  it("imports the wrapper", () => {
    expect(src).toContain('LiveTechPinsWrapper');
    expect(src).toContain('from "@/src/components/dispatch/LiveTechPinsWrapper"');
  });
  it("renders <LiveTechPinsWrapper /> in the board", () => {
    expect(src).toMatch(/<LiveTechPinsWrapper\b/);
  });
  it("regression: Phase 38 pieces still wired (optimize, shift, tech-load, unrouted)", () => {
    expect(src).toContain("dispatch-tools-row");
    expect(src).toContain("dispatch-open-optimize");
    expect(src).toContain("dispatch-open-shift-route");
    expect(src).toContain('from "@/src/components/dispatch/TechLoadStrip"');
    expect(src).toContain('from "@/src/components/dispatch/UnroutedPanel"');
  });
});

describe("Phase 38b · Runbook", () => {
  const src = existsSync(RUNBOOK) ? readFileSync(RUNBOOK, "utf8") : "";
  it("EXPO_GO_RUNBOOK.md exists", () => expect(existsSync(RUNBOOK)).toBe(true));
  it("documents the Phase 38b Mapbox setup steps", () => {
    expect(src).toContain("Phase 38b");
    expect(src).toContain("@rnmapbox/maps");
    expect(src).toContain("EXPO_PUBLIC_MAPBOX_TOKEN");
    expect(src).toContain("npx expo prebuild --clean");
    expect(src).toContain("eas build --profile development");
  });
});
