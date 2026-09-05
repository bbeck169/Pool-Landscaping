/**
 * mapsKey.test.ts — Phase K20 · Unit tests for the Google Maps key
 * helper.
 *
 * Phase K46 · Feb-2026 AMENDMENT — ``hasMapboxToken`` tests removed
 * along with the helper itself; Mapbox is no longer a runtime
 * dependency of this app.
 */
import { Platform } from "react-native";

jest.mock("expo-constants", () => ({
  __esModule: true,
  default: {
    expoConfig: null as any,
  },
}));

jest.mock("@expo/vector-icons", () => ({
  Ionicons: "Ionicons",
}));

import Constants from "expo-constants";
import { hasGoogleMapsKey } from "@/src/utils/mapsKey";

// We need to swap Platform.OS at runtime. Jest-expo defaults to "ios".
const originalOS = Platform.OS;

describe("hasGoogleMapsKey", () => {
  beforeEach(() => {
    (Constants as any).expoConfig = null;
    delete process.env.EXPO_PUBLIC_GOOGLE_MAPS_ANDROID_KEY;
    delete process.env.EXPO_PUBLIC_GOOGLE_MAPS_API_KEY;
  });

  afterEach(() => {
    Object.defineProperty(Platform, "OS", { value: originalOS, writable: true });
  });

  it("returns true on iOS regardless (Apple Maps default)", () => {
    Object.defineProperty(Platform, "OS", { value: "ios", writable: true });
    expect(hasGoogleMapsKey()).toBe(true);
  });

  it("returns false on web", () => {
    Object.defineProperty(Platform, "OS", { value: "web", writable: true });
    expect(hasGoogleMapsKey()).toBe(false);
  });

  it("returns false on Android when no key is set anywhere", () => {
    Object.defineProperty(Platform, "OS", { value: "android", writable: true });
    expect(hasGoogleMapsKey()).toBe(false);
  });

  it("returns true on Android when EXPO_PUBLIC_GOOGLE_MAPS_ANDROID_KEY env var is set", () => {
    Object.defineProperty(Platform, "OS", { value: "android", writable: true });
    process.env.EXPO_PUBLIC_GOOGLE_MAPS_ANDROID_KEY = "AIzaSy_test_key";
    expect(hasGoogleMapsKey()).toBe(true);
  });

  it("returns true on Android with fallback EXPO_PUBLIC_GOOGLE_MAPS_API_KEY", () => {
    Object.defineProperty(Platform, "OS", { value: "android", writable: true });
    process.env.EXPO_PUBLIC_GOOGLE_MAPS_API_KEY = "AIzaSy_fallback";
    expect(hasGoogleMapsKey()).toBe(true);
  });

  it("returns true on Android when expoConfig has the key", () => {
    Object.defineProperty(Platform, "OS", { value: "android", writable: true });
    (Constants as any).expoConfig = {
      android: { config: { googleMaps: { apiKey: "AIzaSy_config" } } },
    };
    expect(hasGoogleMapsKey()).toBe(true);
  });

  it("returns false when expoConfig key is an unresolved EAS reference", () => {
    Object.defineProperty(Platform, "OS", { value: "android", writable: true });
    (Constants as any).expoConfig = {
      android: {
        config: {
          googleMaps: { apiKey: "$EXPO_PUBLIC_GOOGLE_MAPS_ANDROID_KEY" },
        },
      },
    };
    expect(hasGoogleMapsKey()).toBe(false);
  });
});

// Phase K46 · Feb-2026 — Regression guard: ``hasMapboxToken`` must
// no longer be exported from the helper. This test would fail at
// import time if the symbol were re-added.
describe("K46 · Mapbox helper removed", () => {
  it("does not export hasMapboxToken any more", () => {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const mod = require("@/src/utils/mapsKey");
    expect(mod.hasMapboxToken).toBeUndefined();
  });
});
