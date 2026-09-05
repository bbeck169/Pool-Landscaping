/**
 * Phase K45b · Feb-2026 — Package-level guard for the HERE Maps
 * removal.
 *
 * K45 fixed the mobile white-screen crash on Schedule by making the
 * HERE adapter lazy-load its native module + downgrade silently to
 * Google when the SDK binaries were missing. That fix is *correct*
 * for the eager-require class of bugs, but a full new EAS build
 * shipped afterwards still white-screened on Android, so we took the
 * belt-and-suspenders route: strip HERE from the project entirely
 * at the package.json + Expo-config-plugin level.
 *
 * This suite enforces the strip so a future refactor can't quietly
 * re-add HERE without a signed-off K45c phase to do it properly.
 *
 * Invariants:
 *
 *   1. `mobile/package.json` MUST NOT list `react-native-here-explore`
 *      under `dependencies` or `devDependencies`. Autolinking picks
 *      up native modules purely on their presence in `package.json`,
 *      independent of whether any JS imports them, so this is the
 *      only durable place to draw the line.
 *
 *   2. `mobile/yarn.lock` MUST NOT resolve `react-native-here-explore`.
 *      Belt to the package.json suspenders in case someone hand-edits
 *      package.json without running `yarn install`.
 *
 *   3. `mobile/app.config.js` MUST NOT register the
 *      `react-native-here-explore` Expo config plugin. Even a guarded
 *      registration (`process.env.EXPO_PUBLIC_HERE_ACCESS_KEY_ID
 *      ? [...] : []`) is a footgun because a stray env var in an
 *      EAS build environment flips the guard on.
 *
 *   4. `mobile/src/lib/maps/hereAdapter.tsx`'s `_loadHere()` MUST
 *      throw. The provider gate at `index.ts` catches the throw and
 *      downgrades silently — this is our runtime tripwire.
 */

const fs = require("fs");
const path = require("path");

describe("K45b · package-level HERE removal", () => {
  it("mobile/package.json does not depend on react-native-here-explore", () => {
    const pkg = JSON.parse(
      fs.readFileSync(path.resolve(__dirname, "../package.json"), "utf-8"),
    );
    expect(pkg.dependencies || {}).not.toHaveProperty(
      "react-native-here-explore",
    );
    expect(pkg.devDependencies || {}).not.toHaveProperty(
      "react-native-here-explore",
    );
  });

  it("mobile/yarn.lock does not resolve react-native-here-explore", () => {
    const lock = fs.readFileSync(
      path.resolve(__dirname, "../yarn.lock"),
      "utf-8",
    );
    // yarn.lock uses `"react-native-here-explore@<range>":` as the
    // block header. A single case-insensitive match is enough to
    // fail the guard; there should be exactly zero occurrences.
    expect(lock).not.toMatch(/react-native-here-explore/i);
  });

  it("mobile/app.config.js does not register the HERE Expo plugin", () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, "../app.config.js"),
      "utf-8",
    );
    // A JS-string literal reference is the only shape that survives
    // Expo prebuild's plugin resolution. We strip line comments so
    // the K45b amendment note doesn't false-positive the guard.
    const stripped = src
      .split("\n")
      .filter((l: string) => {
        const t = l.trim();
        return !(t.startsWith("//") || t.startsWith("*") || t.startsWith("/*"));
      })
      .join("\n");
    expect(stripped).not.toMatch(/["']react-native-here-explore["']/);
  });
});

describe("K45b · hereAdapter is a hard-throw sentinel", () => {
  beforeEach(() => {
    jest.resetModules();
  });

  it("_loadHere() throws with the 'not installed in this build' message", () => {
    const mod = require("../src/lib/maps/hereAdapter");
    expect(typeof mod.__k45b_loadHere).toBe("function");
    expect(() => mod.__k45b_loadHere()).toThrow(
      /HERE Maps adapter is not installed in this build/,
    );
  });

  it("provider gate does not crash when adapter is disabled", () => {
    // K45b · Even under `provider=here` (a rogue env flip past the
    // binary-presence check) the barrel MUST still resolve without
    // throwing. Under K45b, `require("./hereAdapter")` succeeds
    // (the file loads fine) and the placeholder MapView is used
    // instead of the real HERE MapView — no `_loadHere` throw
    // fires at module load because the sentinel only throws on
    // invocation. That's the correct behavior: no crash on cold
    // boot, and any component that DOES render `<MapView/>` gets a
    // safe fallback placeholder from the hereAdapter file.
    jest.doMock("../src/lib/maps/heresdkStatus.generated", () => ({
      HERE_BINARIES_PRESENT: true,
    }));
    jest.doMock("../src/lib/maps/provider", () => ({
      __esModule: true,
      _computeProvider: () => "here",
      useMapsProvider: () => "here",
    }));
    // Stub react-native-maps so the barrel imports don't touch
    // native modules in the jest runtime.
    jest.doMock("react-native-maps", () => ({
      __esModule: true,
      default: function _GoogleMapView() { return null; },
      Marker: function _GoogleMarker() { return null; },
      Polyline: function _GooglePolyline() { return null; },
      Polygon: function _GooglePolygon() { return null; },
      Circle: function _GoogleCircle() { return null; },
      PROVIDER_GOOGLE: "google",
    }));
    // The barrel must resolve without throwing — that's the whole
    // point of the K45b hard-throw sentinel: it lives inside a
    // function body so the module load itself is side-effect-free.
    expect(() => require("../src/lib/maps")).not.toThrow();
    const maps = require("../src/lib/maps");
    expect(typeof maps.MapView).toBe("function");
  });
});
