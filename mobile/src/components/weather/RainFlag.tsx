/**
 * RainFlag — compact rain badge for job cards (A2).
 * Shows rain icon + % when chance >= 60 for any overlapping hour.
 */
import React from "react";
import { View, Text, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { font } from "@/src/theme";
import type { HourlyEntry } from "@/src/api/weather";

type Props = {
  jobId: string;
  scheduledDate?: string | null;
  scheduledTime?: string | null;
  hourlyData: HourlyEntry[];
};

export default function RainFlag({ jobId, scheduledDate, scheduledTime, hourlyData }: Props) {
  if (!scheduledDate || !hourlyData.length) return null;

  // Find max rain chance for hours overlapping this job's date
  const jobDateStr = scheduledDate.slice(0, 10);
  let maxRain = 0;
  for (const h of hourlyData) {
    const hDate = h.time.slice(0, 10);
    if (hDate === jobDateStr && h.chance_of_rain > maxRain) {
      maxRain = h.chance_of_rain;
    }
  }
  if (maxRain < 60) return null;

  return (
    <View testID={`job-rain-flag-${jobId}`} style={styles.badge}>
      <Ionicons name="rainy" size={11} color="#2563EB" />
      <Text style={styles.text}>{maxRain}% rain</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  badge: {
    flexDirection: "row",
    alignItems: "center",
    gap: 3,
    backgroundColor: "#DBEAFE",
    borderWidth: 1,
    borderColor: "#93C5FD",
    borderRadius: 4,
    paddingHorizontal: 5,
    paddingVertical: 2,
  },
  text: { fontFamily: font.bold, fontSize: 9, color: "#1E3A8A" },
});
