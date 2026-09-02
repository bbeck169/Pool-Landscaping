/**
 * mapsKey.test.ts — Phase K20 · Unit tests for the map API key helpers.
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
import { hasGoogleMapsKey, hasMapboxToken } from "@/src/utils/mapsKey";

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

describe("hasMapboxToken", () => {
  beforeEach(() => {
    (Constants as any).expoConfig = null;
    delete process.env.EXPO_PUBLIC_MAPBOX_TOKEN;
  });

  it("returns false when no token is set", () => {
    expect(hasMapboxToken()).toBe(false);
  });

  it("returns true when EXPO_PUBLIC_MAPBOX_TOKEN env var is set", () => {
    process.env.EXPO_PUBLIC_MAPBOX_TOKEN = "pk.test_token";
    expect(hasMapboxToken()).toBe(true);
  });

  it("returns true when expoConfig extra has the token", () => {
    (Constants as any).expoConfig = { extra: { mapboxToken: "pk.config_token" } };
    expect(hasMapboxToken()).toBe(true);
  });

  it("returns false when token is an unresolved reference", () => {
    (Constants as any).expoConfig = { extra: { mapboxToken: "$EXPO_PUBLIC_MAPBOX_TOKEN" } };
    expect(hasMapboxToken()).toBe(false);
  });
});
