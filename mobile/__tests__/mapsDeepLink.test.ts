/**
 * __tests__/mapsDeepLink.test.ts
 *
 * Tests for the maps deep-link URL generation per platform:
 *   - iOS: Google Maps preferred, falls back to Apple Maps
 *   - Android: Google Maps native intent preferred, falls back to https
 *   - Web: always https universal URL
 */
import { Platform, Linking } from "react-native";

/* ── Mocks ────────────────────────────────────────────── */
const mockCanOpenURL = jest.fn();
const mockOpenURL = jest.fn();
jest.spyOn(Linking, "canOpenURL").mockImplementation(mockCanOpenURL);
jest.spyOn(Linking, "openURL").mockImplementation(mockOpenURL);

import {
  resolveDestination,
  buildGoogleMapsUrl,
  openMaps,
} from "@/src/services/navigation/mapsDeepLink";
import type { Destination } from "@/src/services/navigation/mapsDeepLink";

const DEST_COORDS: Destination = { kind: "coords", value: "33.77,-112.34" };
const DEST_ADDR: Destination = { kind: "address", value: "12 Main St, Phoenix, AZ" };

describe("mapsDeepLink · buildGoogleMapsUrl", () => {
  it("builds a universal Google Maps URL with coords", () => {
    const url = buildGoogleMapsUrl(DEST_COORDS);
    expect(url).toBe(
      "https://www.google.com/maps/dir/?api=1&destination=33.77%2C-112.34",
    );
    console.log("✅ MDL-T1: universal URL with coords");
  });

  it("builds a universal Google Maps URL with address", () => {
    const url = buildGoogleMapsUrl(DEST_ADDR);
    expect(url).toContain("destination=12+Main+St%2C+Phoenix%2C+AZ");
    console.log("✅ MDL-T2: universal URL with address");
  });
});

describe("mapsDeepLink · openMaps (web)", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    // Default platform is "web" in test environment (JSDOM)
    Object.defineProperty(Platform, "OS", { get: () => "web" });
  });

  it("web: always uses https universal URL", async () => {
    mockOpenURL.mockResolvedValue(true);
    await openMaps(DEST_COORDS);
    expect(mockOpenURL).toHaveBeenCalledTimes(1);
    const url = mockOpenURL.mock.calls[0][0];
    expect(url).toMatch(/^https:\/\/www\.google\.com\/maps\/dir\//);
    console.log("✅ MDL-T3: web → https universal URL");
  });
});

describe("mapsDeepLink · openMaps (iOS)", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    Object.defineProperty(Platform, "OS", { get: () => "ios" });
  });

  it("iOS: prefers Google Maps when installed", async () => {
    mockCanOpenURL.mockResolvedValue(true);
    mockOpenURL.mockResolvedValue(true);
    await openMaps(DEST_COORDS);
    expect(mockCanOpenURL).toHaveBeenCalledWith(
      expect.stringContaining("comgooglemaps://"),
    );
    expect(mockOpenURL).toHaveBeenCalledWith(
      expect.stringContaining("comgooglemaps://"),
    );
    console.log("✅ MDL-T4: iOS → Google Maps preferred");
  });

  it("iOS: falls back to Apple Maps when Google Maps not installed", async () => {
    mockCanOpenURL.mockResolvedValue(false);
    mockOpenURL.mockResolvedValue(true);
    await openMaps(DEST_COORDS);
    expect(mockOpenURL).toHaveBeenCalledWith(
      expect.stringContaining("maps://"),
    );
    console.log("✅ MDL-T5: iOS → Apple Maps fallback");
  });
});

describe("mapsDeepLink · openMaps (Android)", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    Object.defineProperty(Platform, "OS", { get: () => "android" });
  });

  it("Android: prefers Google Maps native intent", async () => {
    mockCanOpenURL.mockResolvedValue(true);
    mockOpenURL.mockResolvedValue(true);
    await openMaps(DEST_COORDS);
    expect(mockCanOpenURL).toHaveBeenCalledWith(
      expect.stringContaining("google.navigation:"),
    );
    expect(mockOpenURL).toHaveBeenCalledWith(
      expect.stringContaining("google.navigation:"),
    );
    console.log("✅ MDL-T6: Android → Google Maps native intent");
  });

  it("Android: falls back to https when native intent fails", async () => {
    mockCanOpenURL.mockResolvedValue(false);
    mockOpenURL.mockResolvedValue(true);
    await openMaps(DEST_COORDS);
    const url = mockOpenURL.mock.calls[0][0];
    expect(url).toMatch(/^https:\/\/www\.google\.com\/maps\/dir\//);
    console.log("✅ MDL-T7: Android → https fallback");
  });
});
