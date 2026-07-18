import React from "react";
import { View, Text, StyleSheet } from "react-native";
import { colors, font } from "@/src/theme";

const META: Record<string, { label: string; bg: string; fg: string }> = {
  draft: { label: "Draft", bg: "#FEF9C3", fg: "#A16207" },
  finalized: { label: "Finalized", bg: "#DCFCE7", fg: "#166534" },
};

export default function TemplateStatusPill({ status = "draft" }: { status?: string }) {
  const meta = META[status] || { label: status, bg: colors.surfaceTertiary, fg: colors.onSurfaceSecondary };
  return (
    <View
      testID={`template-status-pill-${status}`}
      style={[styles.pill, { backgroundColor: meta.bg }]}
    >
      <Text style={[styles.text, { color: meta.fg }]}>{meta.label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  pill: {
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 999,
  },
  text: {
    fontSize: 10,
    fontFamily: font.bold,
    textTransform: "uppercase",
    letterSpacing: 0.5,
  },
});
