import React from "react";
import { View, Text, StyleSheet } from "react-native";
import { font } from "@/src/theme";

const STATUS_COLOURS: Record<string, { bg: string; fg: string; border: string }> = {
  queued: { bg: "#EFF6FF", fg: "#1D4ED8", border: "#BFDBFE" },
  sent: { bg: "#DCFCE7", fg: "#166534", border: "#86EFAC" },
  mocked: { bg: "#FEF9C3", fg: "#854D0E", border: "#FDE68A" },
  failed: { bg: "#FEE2E2", fg: "#991B1B", border: "#FECACA" },
  opted_out: { bg: "#F3F4F6", fg: "#374151", border: "#D1D5DB" },
  missing_key: { bg: "#FFEDD5", fg: "#9A3412", border: "#FDBA74" },
};

const FALLBACK = { bg: "#F4F4F5", fg: "#71717A", border: "#E4E4E7" };

export default function SendStatusPill({ status }: { status?: string }) {
  const s = STATUS_COLOURS[status || ""] || FALLBACK;
  return (
    <View
      testID={`send-status-${status || "unknown"}`}
      style={[
        styles.pill,
        { backgroundColor: s.bg, borderColor: s.border },
      ]}
    >
      <Text style={[styles.label, { color: s.fg }]}>
        {String(status || "unknown").replace(/_/g, " ")}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  pill: {
    alignSelf: "flex-start",
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
    borderWidth: 1,
  },
  label: {
    fontSize: 10,
    fontFamily: font.bold,
    textTransform: "uppercase",
    letterSpacing: 0.6,
  },
});
