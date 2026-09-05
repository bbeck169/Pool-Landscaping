// Phase K46 · Feb-2026 — Google-only maps migration source-inspection.
//
// Locks in the K46 landing state so any accidental re-introduction
// of @rnmapbox/maps or the HERE plugin fails the suite. Was the
// Phase 38b test before K46; the Mapbox contract lock-in tests
// were flipped to "Mapbox must be absent" as part of the
// migration.
//
// NOTE — the mobile app has always used ``app.config.js`` (dynamic
// Expo config, Phase K29). ``app.json`` does not exist; the K46
// suite reads ``app.config.js`` directly.

import { readFileSync, existsSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";

const MOBILE = resolve(__dirname, "../../../mobile");
const F = (rel) => resolve(MOBILE, rel);
const R = (rel) => existsSync(F(rel)) ? readFileSync(F(rel), "utf8") : "";

const PKG_PATH = F("package.json");
const APP_CFG = F("app.config.js");
const MAP = F("src/components/dispatch/LiveTechPinsMap.tsx");
const WRAP = F("src/components/dispatch/LiveTechPinsWrapper.tsx");
const MAPS_KEY = F("src/utils/mapsKey.tsx");
const NATIVE_NAV = F("src/utils/nativeNav.ts");
const NAV_JOB_BTN = F("src/components/schedule/NavigateJobButton.tsx");
const DAILY_ROUTE_MAP = F("src/components/schedule/DailyRouteMap.native.tsx");
const ROOT_LAYOUT = F("app/_layout.tsx");

describe("Phase K46 · Mapbox dep + config fully removed", () => {
  const pkg = readFileSync(PKG_PATH, "utf8");
  const app = readFileSync(APP_CFG, "utf8");

  it("removes @rnmapbox/maps from mobile/package.json", () => {
    expect(pkg).not.toMatch(/"@rnmapbox\/maps"\s*:/);
  });

  it("removes the @rnmapbox/maps expo config plugin from app.config.js", () => {
    // Strip line-comments before scanning — the migration note
    // legitimately mentions the removed module by name.
    const stripped = app.replace(/\/\/[^\n]*\n/g, "\n").replace(/\/\*[\s\S]*?\*\//g, "");
    // A bare-string plugin like ``"@rnmapbox/maps"`` or a tuple
    // ``["@rnmapbox/maps", {...}]`` would fail the guard.
    expect(stripped).not.toMatch(/["'`]@rnmapbox\/maps["'`]/);
  });

  it("removes the mapboxToken expo-extra plumbing from app.config.js", () => {
    // The comment documents the removal; the actual `mapboxToken:`
    // assignment must be gone.
    expect(app).not.toMatch(/mapboxToken:\s*process\.env\.EXPO_PUBLIC_MAPBOX_TOKEN/);
  });

  it("keeps the Google Maps API-key plumbing intact for Android + iOS", () => {
    expect(app).toContain("EXPO_PUBLIC_GOOGLE_MAPS_ANDROID_KEY");
    expect(app).toContain("EXPO_PUBLIC_GOOGLE_MAPS_IOS_KEY");
  });
});

describe("Phase K46 · LiveTechPinsMap uses react-native-maps + Google", () => {
  const src = R("src/components/dispatch/LiveTechPinsMap.tsx");
  it("file exists", () => expect(existsSync(MAP)).toBe(true));
  it("imports react-native-maps with the Google provider", () => {
    expect(src).toMatch(/from\s+["']react-native-maps["']/);
    expect(src).toContain("PROVIDER_GOOGLE");
  });
  it("does NOT import @rnmapbox/maps any more", () => {
    // Match only real import/require statements — a comment/docstring
    // may legitimately reference the removed module for context.
    expect(src).not.toMatch(/require\(["']@rnmapbox\/maps["']\)/);
    expect(src).not.toMatch(/from\s+["']@rnmapbox\/maps["']/);
    expect(src).not.toContain("MapboxGL");
  });
  it("cycles Google mapType (standard/satellite/hybrid) — no more Mapbox style URLs", () => {
    expect(src).toContain("standard");
    expect(src).toContain("satellite");
    expect(src).toContain("hybrid");
    expect(src).not.toContain("streets-v12");
    expect(src).not.toContain("mapbox://");
  });
  it("persists the chosen style in AsyncStorage under dispatch_map_style_v1", () => {
    expect(src).toContain('"dispatch_map_style_v1"');
    expect(src).toMatch(/AsyncStorage\.(getItem|setItem)/);
  });
  it("guards missing Google Maps key via hasGoogleMapsKey()", () => {
    expect(src).toContain("hasGoogleMapsKey");
    expect(src).toContain("dispatch-live-map-no-token");
  });
  it("exposes the theme toggle testID + per-pin testIDs", () => {
    expect(src).toContain("dispatch-live-map-style-toggle");
    expect(src).toContain("dispatch-live-pin-");
  });
  it("carries no hardcoded API keys", () => {
    expect(src).not.toMatch(/pk\.[a-zA-Z0-9]{20,}/);
    expect(src).not.toMatch(/AIzaSy[a-zA-Z0-9_-]{20,}/);
  });
});

describe("Phase K46 · LiveTechPinsWrapper (dynamic-require removed)", () => {
  const src = R("src/components/dispatch/LiveTechPinsWrapper.tsx");
  it("file exists", () => expect(existsSync(WRAP)).toBe(true));
  it("statically imports LiveTechPinsMap (no more try/catch require)", () => {
    expect(src).toMatch(/import\s+LiveTechPinsMap[\s\S]*?from\s+["']@\/src\/components\/dispatch\/LiveTechPinsMap["']/);
    expect(src).not.toMatch(/try\s*\{[\s\S]*require\(["']@\/src\/components\/dispatch\/LiveTechPinsMap["']\)/);
  });
  it("no longer renders the dev-client fallback banner (react-native-maps is universal)", () => {
    expect(src).not.toContain("dispatch-live-map-fallback");
    expect(src).not.toContain("EXPO_GO_RUNBOOK");
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
  it("carries the required testIDs (map, toggle, strip)", () => {
    expect(src).toContain("dispatch-live-map");
    expect(src).toContain("dispatch-live-map-toggle");
    expect(src).toContain("dispatch-live-map-strip");
  });
  it("pin tap navigates to /dispatch/shift-route (ShiftRouteDialog)", () => {
    expect(src).toMatch(/pathname:\s*["']\/dispatch\/shift-route["']/);
  });
  it("does NOT use Alert.alert (Phase 30.4 root cause)", () => {
    expect(src).not.toMatch(/Alert\.alert\(/);
  });
});

describe("Phase K46 · mapsKey helper — Mapbox removed", () => {
  const src = R("src/utils/mapsKey.tsx");
  it("file exists", () => expect(existsSync(MAPS_KEY)).toBe(true));
  it("hasGoogleMapsKey remains exported", () => {
    expect(src).toMatch(/export function hasGoogleMapsKey/);
  });
  it("hasMapboxToken export is gone", () => {
    expect(src).not.toMatch(/export function hasMapboxToken/);
  });
});

describe("Phase K46 · nativeNav helper + wired consumers", () => {
  const nav = R("src/utils/nativeNav.ts");
  const btn = R("src/components/schedule/NavigateJobButton.tsx");
  const map = R("src/components/schedule/DailyRouteMap.native.tsx");

  it("nativeNav.ts exports openNativeNavTo", () => {
    expect(existsSync(NATIVE_NAV)).toBe(true);
    expect(nav).toMatch(/export async function openNativeNavTo/);
  });

  it("NavigateJobButton uses openNativeNavTo", () => {
    expect(existsSync(NAV_JOB_BTN)).toBe(true);
    expect(btn).toContain("openNativeNavTo");
    expect(btn).toMatch(/from\s+["']@\/src\/utils\/nativeNav["']/);
  });

  it("DailyRouteMap.native uses openNativeNavTo (callout Navigate)", () => {
    expect(existsSync(DAILY_ROUTE_MAP)).toBe(true);
    expect(map).toContain("openNativeNavTo");
    expect(map).toContain("schedule-daily-route-map-callout-navigate");
  });
});

describe("Phase K46 · root layout Mapbox guard removed", () => {
  const src = R("app/_layout.tsx");
  it("no longer references EXPO_PUBLIC_MAPBOX_TOKEN", () => {
    expect(src).not.toContain("EXPO_PUBLIC_MAPBOX_TOKEN");
  });
});

describe("Phase K46 · Board wiring (unchanged surface)", () => {
  const src = R("app/(app)/dispatch/board.tsx");
  it("imports the wrapper", () => {
    expect(src).toContain("LiveTechPinsWrapper");
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
