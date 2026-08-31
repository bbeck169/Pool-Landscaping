/**
 * NavigateRouteButton — Day-level "Navigate" that opens Google Maps
 * with all stops as waypoints in route order.
 *
 * URL: https://www.google.com/maps/dir/?api=1&destination=<last>&waypoints=<mid1|mid2>&travelmode=driving
 * Origin is blank — Google uses current location.
 *
 * Disabled (grey) when 0 addressable, non-terminal jobs on the day.
 */
import React from "react";
import { Pressable, Text, StyleSheet, Linking, Alert, Platform } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";

type Job = {
  id: string;
  address?: string;
  latitude?: number | null;
  longitude?: number | null;
  location_lat?: number | null;
  location_lng?: number | null;
  route_index?: number | null;
  route_order?: number | null;
  status?: string;
};

const TERMINAL = new Set([
  "completed", "cancelled", "canceled", "skipped", "could_not_service",
]);

function jobDest(j: Job): string | null {
  const lat = Number(j.latitude ?? j.location_lat);
  const lng = Number(j.longitude ?? j.location_lng);
  if (Number.isFinite(lat) && Number.isFinite(lng) && !(lat === 0 && lng === 0)) {
    return `${lat},${lng}`;
  }
  return (j.address || "").trim() || null;
}

/** Build the multi-stop Google Maps deep-link URL. Exported for testing. */
export function buildRouteUrl(jobs: Job[]): string | null {
  const stops = jobs
    .filter((j) => !TERMINAL.has((j.status || "").toLowerCase()))
    .sort(
      (a, b) =>
        (a.route_index ?? a.route_order ?? 999) -
        (b.route_index ?? b.route_order ?? 999),
    )
    .map(jobDest)
    .filter(Boolean) as string[];

  if (stops.length === 0) return null;

  const destination = stops[stops.length - 1];
  const waypoints = stops.slice(0, -1).join("|");

  const params = new URLSearchParams();
  params.set("api", "1");
  params.set("destination", destination);
  if (waypoints) params.set("waypoints", waypoints);
  params.set("travelmode", "driving");

  return `https://www.google.com/maps/dir/?${params.toString()}`;
}

const STORE_IOS = "https://apps.apple.com/app/google-maps/id585027354";
const STORE_ANDROID =
  "https://play.google.com/store/apps/details?id=com.google.android.apps.maps";

export default function NavigateRouteButton({ jobs }: { jobs: Job[] }) {
  const url = buildRouteUrl(jobs);
  const disabled = !url;
  const stopCount = jobs.filter(
    (j) => !TERMINAL.has((j.status || "").toLowerCase()) && jobDest(j),
  ).length;

  const onPress = async () => {
    if (!url) return;
    try {
      const canOpen = await Linking.canOpenURL(url);
      if (canOpen) {
        await Linking.openURL(url);
      } else {
        const storeUrl = Platform.OS === "ios" ? STORE_IOS : STORE_ANDROID;
        Alert.alert(
          "Google Maps not installed",
          "Install Google Maps to use route navigation.",
          [
            { text: "Cancel", style: "cancel" },
            { text: "Get app", onPress: () => Linking.openURL(storeUrl) },
          ],
        );
      }
    } catch {
      Alert.alert("Error", "Could not open Google Maps.");
    }
  };

  return (
    <Pressable
      onPress={onPress}
      disabled={disabled}
      style={[s.btn, disabled && s.btnDisabled]}
      testID="schedule-navigate-route-btn"
      accessibilityRole="button"
      accessibilityLabel={
        disabled
          ? "Navigate route (no stops)"
          : `Navigate route — ${stopCount} stops`
      }
    >
      <Ionicons
        name="navigate"
        size={14}
        color={disabled ? colors.muted : "#fff"}
      />
      <Text style={[s.btnText, disabled && s.btnTextDisabled]}>Navigate</Text>
    </Pressable>
  );
}

const s = StyleSheet.create({
  btn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: spacing.md,
    height: 34,
    borderRadius: radius.pill,
    backgroundColor: "#059669",
  },
  btnDisabled: { backgroundColor: colors.surfaceTertiary, opacity: 0.6 },
  btnText: { fontFamily: font.bold, fontSize: fontSize.sm, color: "#fff" },
  btnTextDisabled: { color: colors.muted },
});
