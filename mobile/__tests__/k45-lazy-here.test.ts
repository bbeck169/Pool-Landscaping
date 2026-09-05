/**
 * Phase K45 · Feb-2026 — Regression coverage for the mobile
 * white-screen crash on Schedule with assigned jobs.
 *
 * Guards the four boot-time invariants that broke K39b:
 *
 *   1. ``hereAdapter.tsx`` MUST NOT call ``require("react-native-here-explore")``
 *      at module scope. The require has to live inside a function
 *      body (the ``_loadHere`` lazy loader) so it only runs when a
 *      HERE component is actually rendered — never at import time.
 *
 *   2. ``@/src/lib/maps/index.ts`` MUST NOT statically import
 *      ``./hereAdapter``. It may only reference it via a
 *      conditional ``require()`` inside a provider gate.
 *
 *   3. When ``EXPO_PUBLIC_MAPS_PROVIDER=here`` but the generated
 *      ``HERE_BINARIES_PRESENT`` constant is ``false``, the provider
 *      resolver MUST downgrade to ``google`` (silent + logged once).
 *
 *   4. When the tree is loaded in provider=google mode, requiring
 *      ``@/src/lib/maps`` MUST NOT resolve ``react-native-here-explore``
 *      — the eager resolution was the actual K45 crash root cause.
 */

describe("K45 · hereAdapter has no top-level require", () => {
  it("does not call require(\"react-native-here-explore\") at module scope", () => {
    const fs = require("fs");
    const path = require("path");
    const src = fs.readFileSync(
      path.resolve(__dirname, "../src/lib/maps/hereAdapter.tsx"),
      "utf-8",
    );
    // Strip line comments so a "we used to do X" note in a doc
    // block doesn't false-positive the check.
    const stripped = src
      .split("\n")
      .filter((l: string) => {
        const t = l.trim();
        return !(t.startsWith("//") || t.startsWith("*") || t.startsWith("/*"));
      })
      .join("\n");
    // K45b · The K45 lazy `require("react-native-here-explore")` was
    // removed entirely — the adapter is now a hard-throw sentinel
    // (see `mobile/__tests__/k45b-here-removed.test.ts`). The
    // invariant this test was originally guarding — "no require at
    // module scope" — still holds trivially: the require was moved
    // out AND then deleted. Belt-and-suspenders assert on the
    // absence of the require call anywhere in the file.
    expect(stripped).not.toMatch(/require\(["']react-native-here-explore["']\)/);
  });
});

describe("K45 · index.ts has no static import of hereAdapter", () => {
  it("does not use ``import ... from \"./hereAdapter\"`` at module scope", () => {
    const fs = require("fs");
    const path = require("path");
    const src = fs.readFileSync(
      path.resolve(__dirname, "../src/lib/maps/index.ts"),
      "utf-8",
    );
    // Grep for the static import pattern — must be absent.
    expect(src).not.toMatch(/^\s*import .*from ["']\.\/hereAdapter["']/m);
    // A gated ``require("./hereAdapter")`` inside a conditional
    // block IS allowed and is what the K45 fix uses.
    expect(src).toMatch(/require\(["']\.\/hereAdapter["']\)/);
  });
});

describe("K45 · provider downgrades here → google when binaries missing", () => {
  beforeEach(() => {
    jest.resetModules();
  });

  it("returns google even when flag=here + key present, if binaries absent", () => {
    // Mock the generated status constant to simulate "binaries missing".
    jest.doMock("../src/lib/maps/heresdkStatus.generated", () => ({
      HERE_BINARIES_PRESENT: false,
    }));
    const warnSpy = jest.spyOn(console, "warn").mockImplementation(() => {});
    const { _computeProvider } = require("../src/lib/maps/provider");
    const p = _computeProvider({
      EXPO_PUBLIC_MAPS_PROVIDER: "here",
      EXPO_PUBLIC_HERE_ACCESS_KEY_ID: "abc",
    });
    expect(p).toBe("google");
    // Must warn once so ops can spot the misconfig in logs.
    expect(warnSpy).toHaveBeenCalledTimes(1);
    expect(warnSpy.mock.calls[0][0]).toMatch(/K45/);
    warnSpy.mockRestore();
  });

  it("returns here when flag=here + key present + binaries present", () => {
    jest.doMock("../src/lib/maps/heresdkStatus.generated", () => ({
      HERE_BINARIES_PRESENT: true,
    }));
    const { _computeProvider } = require("../src/lib/maps/provider");
    const p = _computeProvider({
      EXPO_PUBLIC_MAPS_PROVIDER: "here",
      EXPO_PUBLIC_HERE_ACCESS_KEY_ID: "abc",
    });
    expect(p).toBe("here");
  });
});

describe("K45 · @/src/lib/maps does NOT touch react-native-here-explore in google mode", () => {
  beforeEach(() => {
    jest.resetModules();
  });

  it("importing the maps barrel in google mode does not resolve the HERE JS module", () => {
    // If any code path in ``@/src/lib/maps`` reached
    // ``require("react-native-here-explore")`` at module scope this
    // factory would fire and flip the flag to ``true`` — which is
    // exactly the K45 regression we're guarding against.
    let hereWasResolved = false;
    jest.doMock(
      "react-native-here-explore",
      () => {
        hereWasResolved = true;
        return {};
      },
      { virtual: true },
    );
    // Force google mode via env (default anyway) and a "no
    // binaries" status so a stray here-branch would also downgrade.
    jest.doMock("../src/lib/maps/heresdkStatus.generated", () => ({
      HERE_BINARIES_PRESENT: false,
    }));
    // Stub react-native-maps so importing the barrel doesn't try
    // to touch native modules in the jest runtime.
    jest.doMock("react-native-maps", () => ({
      __esModule: true,
      default: function _GoogleMapView() { return null; },
      Marker: function _GoogleMarker() { return null; },
      Polyline: function _GooglePolyline() { return null; },
      Polygon: function _GooglePolygon() { return null; },
      Circle: function _GoogleCircle() { return null; },
      PROVIDER_GOOGLE: "google",
    }));
    const maps = require("../src/lib/maps");
    expect(maps.MapView).toBeDefined();
    expect(hereWasResolved).toBe(false);
  });
});
