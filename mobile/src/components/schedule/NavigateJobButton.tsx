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
import { Pressable, StyleSheet, Alert, Animated } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { resolveDestination, openMaps } from "@/src/services/navigation/mapsDeepLink";
import { colors } from "@/src/theme";

type Props = {
  job: {
    id: string;
    latitude?: number | null;
    longitude?: number | null;
    address?: string;
    customer_name?: string;
  } | null;
};

export default function NavigateJobButton({ job }: Props) {
  const dest = resolveDestination(job);
  const disabled = !dest;
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
    if (disabled) {
      Alert.alert("No address on file", "This job has no address or coordinates.");
      return;
    }
    openMaps(dest!);
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
          name="navigate-outline"
          size={16}
          color={disabled ? "#9CA3AF" : colors.brand}
        />
      </Pressable>
    </Animated.View>
  );
}

const s = StyleSheet.create({
  btn: {
    width: 30,
    height: 30,
    borderRadius: 15,
    backgroundColor: "#EFF6FF",
    alignItems: "center",
    justifyContent: "center",
  },
  btnDisabled: {
    opacity: 0.45,
    backgroundColor: "#F3F4F6",
  },
});
