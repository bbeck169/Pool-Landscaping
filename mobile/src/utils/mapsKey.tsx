/**
 * mapsKey.tsx — Phase K20 · Central helper for Google Maps API key
 * retrieval and graceful placeholder when the key is missing.
 *
 * Prevents native crashes on Android when the Google Maps API key
 * is absent from the AndroidManifest (react-native-maps MapView
 * init crashes fatally without it on Fabric / newArch).
 *
 * Phase K46 · Feb-2026 AMENDMENT — ``hasMapboxToken`` removed as
 * part of the Google-only maps migration. Mapbox is no longer a
 * runtime dependency of this app; every map surface now consumes
 * ``hasGoogleMapsKey()`` exclusively.
 */
import React from "react";
import { Platform, View, Text, StyleSheet } from "react-native";
import Constants from "expo-constants";
import { Ionicons } from "@expo/vector-icons";

/**
 * Returns true when the Google Maps API key is available for the
 * current platform.
 *
 * - **iOS**: Always true — `react-native-maps` defaults to Apple
 *   Maps; a Google key is only needed with `provider="google"`.
 * - **Android**: Checks `app.json → android.config.googleMaps.apiKey`
 *   (resolved at EAS build time) then falls back to env vars.
 * - **Web**: Always false (react-native-maps is not used on web).
 */
export function hasGoogleMapsKey(): boolean {
  if (Platform.OS === "web") return false;
  if (Platform.OS === "ios") return true;

  // Android — Constants.expoConfig is resolved at build time.
  const cfg: any = Constants.expoConfig || {};
  const configKey: unknown = cfg?.android?.config?.googleMaps?.apiKey;
  if (
    typeof configKey === "string" &&
    configKey.trim().length > 0 &&
    !configKey.startsWith("$")
  ) {
    return true;
  }

  // Fallback: check env vars directly (local dev / Expo Go).
  const envKey =
    process.env.EXPO_PUBLIC_GOOGLE_MAPS_ANDROID_KEY ||
    process.env.EXPO_PUBLIC_GOOGLE_MAPS_API_KEY;
  return typeof envKey === "string" && envKey.trim().length > 0;
}

/**
 * Placeholder rendered in place of a map when the required API key
 * is missing. Prevents native crashes and shows a helpful message.
 */
export function MapUnavailablePlaceholder({
  provider = "Map",
  testID,
  message,
}: {
  provider?: string;
  testID?: string;
  message?: string;
}) {
  return (
    <View
      style={s.container}
      testID={testID || "map-unavailable-placeholder"}
    >
      <Ionicons name="map-outline" size={36} color="#9CA3AF" />
      <Text style={s.title} testID="map-unavailable-title">
        {provider} unavailable
      </Text>
      <Text style={s.subtitle} testID="map-unavailable-message">
        {message || "API key not configured. Contact your administrator."}
      </Text>
    </View>
  );
}

const s = StyleSheet.create({
  container: {
    height: 200,
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    backgroundColor: "#F9FAFB",
    borderRadius: 12,
    borderWidth: 1,
    borderStyle: "dashed",
    borderColor: "#D1D5DB",
    marginBottom: 12,
  },
  title: {
    fontSize: 15,
    fontWeight: "600",
    color: "#6B7280",
  },
  subtitle: {
    fontSize: 13,
    color: "#9CA3AF",
    textAlign: "center",
    paddingHorizontal: 32,
    lineHeight: 18,
  },
});
