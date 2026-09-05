/**
 * Phase K39b · Feb-2026 — provider resolver + adapter selection tests.
 */

describe("K39b · useMapsProvider / _computeProvider", () => {
  beforeEach(() => {
    jest.resetModules();
  });

  it("defaults to google when no env is set", () => {
    const { _computeProvider } = require("../src/lib/maps/provider");
    expect(_computeProvider({})).toBe("google");
  });

  it("returns here when flag=here + key present + binaries present (K45)", () => {
    // K45 · The resolver now also gates on HERE_BINARIES_PRESENT so a
    // successful "here" resolution requires all three: env flag, key,
    // and the generated binary-presence constant.
    jest.doMock("../src/lib/maps/heresdkStatus.generated", () => ({
      HERE_BINARIES_PRESENT: true,
    }));
    const { _computeProvider } = require("../src/lib/maps/provider");
    expect(
      _computeProvider({
        EXPO_PUBLIC_MAPS_PROVIDER: "here",
        EXPO_PUBLIC_HERE_ACCESS_KEY_ID: "abc",
      }),
    ).toBe("here");
  });

  it("falls back to google + warns once when flag=here + empty key", () => {
    jest.resetModules();
    const warnSpy = jest.spyOn(console, "warn").mockImplementation(() => {});
    const { _computeProvider } = require("../src/lib/maps/provider");
    const p1 = _computeProvider({
      EXPO_PUBLIC_MAPS_PROVIDER: "here",
      EXPO_PUBLIC_HERE_ACCESS_KEY_ID: "",
    });
    expect(p1).toBe("google");
    expect(warnSpy).toHaveBeenCalledTimes(1);
    expect(warnSpy.mock.calls[0][0]).toMatch(/EXPO_PUBLIC_HERE_ACCESS_KEY_ID/);
    // Second invocation must NOT re-warn.
    _computeProvider({
      EXPO_PUBLIC_MAPS_PROVIDER: "here",
      EXPO_PUBLIC_HERE_ACCESS_KEY_ID: "",
    });
    expect(warnSpy).toHaveBeenCalledTimes(1);
    warnSpy.mockRestore();
  });
});

describe("K39b · @/src/lib/maps selects the right adapter at import time", () => {
  beforeEach(() => {
    jest.resetModules();
  });

  it("re-exports the react-native-maps ``MapView`` under provider=google (default)", () => {
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
    expect(maps.MapView.name).toBe("_GoogleMapView");
    expect(maps.Marker.name).toBe("_GoogleMarker");
    expect(maps.PROVIDER_GOOGLE).toBe("google");
  });

  it("re-exports the HERE adapter under provider=here + key present", () => {
    jest.doMock("../src/lib/maps/provider", () => ({
      _computeProvider: () => "here",
      useMapsProvider: () => "here",
    }));
    // Mock the HERE SDK so hereAdapter's ``require`` succeeds.
    jest.doMock(
      "react-native-here-explore",
      () => ({
        MapView: function _HereMapView() { return null; },
        Marker: function _HereMarker() { return null; },
        Polyline: function _HerePolyline() { return null; },
        Polygon: function _HerePolygon() { return null; },
        Circle: function _HereCircle() { return null; },
      }),
      { virtual: true },
    );
    const maps = require("../src/lib/maps");
    expect(maps.MapView).toBeDefined();
    // ``MapView`` from hereAdapter is a wrapper function, not the
    // raw SDK component — assert we're NOT looking at the google
    // adapter's fake ``_GoogleMapView``.
    expect(maps.MapView.name).not.toBe("_GoogleMapView");
  });
});

describe("K39b · Schedule map imports resolve through @/src/lib/maps", () => {
  beforeEach(() => {
    jest.resetModules();
  });

  it("ScheduleMap.native imports MapView + Marker from the abstraction (not from react-native-maps)", () => {
    const fs = require("fs");
    const path = require("path");
    const src = fs.readFileSync(
      path.resolve(__dirname, "../src/components/schedule/ScheduleMap.native.tsx"),
      "utf-8",
    );
    expect(src).toMatch(/from ["']@\/src\/lib\/maps["']/);
    // Assert the raw react-native-maps import is GONE.
    expect(src).not.toMatch(/from ["']react-native-maps["']/);
  });

  it("MapCanvas.native and MeasureMap.native also migrated (K39b consumer grep)", () => {
    const fs = require("fs");
    const path = require("path");
    for (const rel of [
      "../src/components/d2d/MapCanvas.native.tsx",
      "../src/components/measure/MeasureMap.native.tsx",
    ]) {
      const src = fs.readFileSync(path.resolve(__dirname, rel), "utf-8");
      expect(src).toMatch(/from ["']@\/src\/lib\/maps["']/);
      expect(src).not.toMatch(/from ["']react-native-maps["']/);
    }
  });
});
