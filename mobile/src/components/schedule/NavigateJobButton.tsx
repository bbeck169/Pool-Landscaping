/**
 * NavigateJobButton — per-job "navigate to customer" action.
 *
 * Mirrors web NavigateJobButton.jsx:
 *   - Destination priority: lat/lng > address > disabled
 *   - Opens native maps app (iOS: Google Maps → Apple Maps, Android: Google nav)
 *   - Disabled state shows toast "No address on file"
 *   - testID: schedule-job-nav-{job_id}
 */
import React, { useRef } from "react";
import { Pressable, StyleSheet, Alert, Animated, Platform } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { openNativeNavTo } from "@/src/utils/nativeNav";

const NAV_BG = "#F97316";

type Props = {
  job: {
    id: string;
    latitude?: number | null;
    longitude?: number | null;
    location_lat?: number | null;
    location_lng?: number | null;
    address?: string;
    customer_name?: string;
  } | null;
};

/**
 * K46 · Resolve a job's destination for native navigation.
 *
 * Coord priority (finite, non-(0,0)):
 *   1. ``job.latitude`` / ``job.longitude`` (canonical shape used
 *      throughout the schedule surfaces)
 *   2. ``job.location_lat`` / ``job.location_lng`` (legacy shape
 *      still emitted by a couple of older endpoints)
 *
 * If coords are unavailable we return ``null`` — the button
 * disables itself and shows an "address on file" toast. Address-only
 * navigation is intentionally NOT supported by the K46 native-nav
 * helper (which is coord-only by design — see ``nativeNav.ts``).
 * Any consumer that needs address-based deep links should keep
 * using the legacy ``services/navigation/mapsDeepLink.ts`` path.
 */
function _resolveCoords(job: Props["job"]): { lat: number; lng: number } | null {
  if (!job) return null;
  const pairs = [
    [job.latitude, job.longitude],
    [job.location_lat, job.location_lng],
  ];
  for (const [rawLat, rawLng] of pairs) {
    const lat = Number(rawLat);
    const lng = Number(rawLng);
    if (
      Number.isFinite(lat) &&
      Number.isFinite(lng) &&
      !(lat === 0 && lng === 0)
    ) {
      return { lat, lng };
    }
  }
  return null;
}

export default function NavigateJobButton({ job }: Props) {
  const coords = _resolveCoords(job);
  const disabled = !coords;
  const customerName = job?.customer_name || "customer";
  const label = disabled
    ? "No address on file"
    : `Navigate to ${customerName}`;

  const scale = useRef(new Animated.Value(1)).current;

  const onPressIn = () => {
    if (disabled) return;
    Animated.spring(scale, { toValue: 0.85, useNativeDriver: true }).start();
  };
  const onPressOut = () => {
    Animated.spring(scale, { toValue: 1, useNativeDriver: true }).start();
  };

  const onPress = () => {
    if (!coords) {
      Alert.alert("No address on file", "This job has no coordinates to navigate to.");
      return;
    }
    // K46 · Deep-link to the platform's native navigation app via
    // the shared helper — silent fallback to the universal HTTPS
    // Google Maps URL if the native scheme fails.
    openNativeNavTo(coords.lat, coords.lng, customerName);
  };

  return (
    <Animated.View style={{ transform: [{ scale }] }}>
      <Pressable
        onPress={onPress}
        onPressIn={onPressIn}
        onPressOut={onPressOut}
        disabled={false}
        hitSlop={6}
        style={[s.btn, disabled && s.btnDisabled]}
        testID={`schedule-job-nav-${job?.id ?? "unknown"}`}
        accessibilityRole="button"
        accessibilityLabel={label}
        accessibilityHint={disabled ? undefined : "Opens driving directions in maps app"}
      >
        <Ionicons
          name="navigate"
          size={16}
          color={disabled ? "#9CA3AF" : "#FFFFFF"}
        />
      </Pressable>
    </Animated.View>
  );
}

const s = StyleSheet.create({
  btn: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: NAV_BG,
    alignItems: "center",
    justifyContent: "center",
    ...Platform.select({
      ios: { shadowColor: "#000", shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.15, shadowRadius: 4 },
      android: { elevation: 3 },
      default: { shadowColor: "#000", shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.15, shadowRadius: 4 },
    }),
  },
  btnDisabled: {
    opacity: 0.35,
    backgroundColor: "#D1D5DB",
  },
});
