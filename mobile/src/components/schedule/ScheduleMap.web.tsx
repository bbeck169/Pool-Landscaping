/**
 * Schedule Map — web fallback.
 *
 * react-native-maps is native-only; on web we show a placeholder.
 */
import React from "react";
import { View, Text, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { colors, spacing, font, fontSize, radius } from "@/src/theme";

interface Job {
  id: string;
  status?: string;
  customer_name?: string;
  address?: string;
  scheduled_time?: string | null;
  location_lat?: number | null;
  location_lng?: number | null;
}

interface Props {
  jobs: Job[];
  testID?: string;
}

export default function ScheduleMap({ jobs, testID }: Props) {
  const geocoded = jobs.filter((j) => j.location_lat != null && j.location_lng != null);

  return (
    <View style={s.wrap} testID={testID || "schedule-map"}>
      <Ionicons name="map-outline" size={28} color={colors.muted} />
      <Text style={s.text}>
        {geocoded.length === 0
          ? "No mapped stops today"
          : `Map view with ${geocoded.length} pin${geocoded.length > 1 ? "s" : ""} opens in the mobile app.`}
      </Text>
    </View>
  );
}

const s = StyleSheet.create({
  wrap: {
    height: 200, alignItems: "center", justifyContent: "center", gap: spacing.sm,
    backgroundColor: colors.surface, borderRadius: radius.md, borderWidth: 1,
    borderStyle: "dashed", borderColor: colors.border, marginBottom: spacing.md,
  },
  text: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, textAlign: "center", lineHeight: 20 },
});
