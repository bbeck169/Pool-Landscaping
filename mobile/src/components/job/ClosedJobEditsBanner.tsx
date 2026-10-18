/**
 * TD-78b (web c1cb22dcc) — "Closed job — edits logged" banner.
 *
 * Non-dismissible notice rendered ONLY when the job is completed AND
 * the viewer holds K6 unlock (they can actually edit) — callers gate on
 * `canEditCompletedJob(role, job)`. Hidden for customers and non-K6
 * roles. Copy + palette match web JobDetail (surfaceSecondary bg,
 * border, brand info icon, bold "Closed job" + muted remainder).
 */
import React from "react";
import { View, Text, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { colors, spacing, radius, font, fontSize } from "@/src/theme";

export default function ClosedJobEditsBanner({ testID = "job-closed-edits-logged-banner" }: { testID?: string }) {
  return (
    <View style={styles.banner} testID={testID} accessibilityRole="text">
      <Ionicons name="information-circle-outline" size={18} color={colors.brand} />
      <Text style={styles.text}>
        <Text style={styles.bold}>Closed job</Text>
        <Text style={styles.muted}> — edits are logged to the audit history on this job.</Text>
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  banner: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border,
    borderRadius: radius.lg, paddingHorizontal: spacing.lg, paddingVertical: spacing.md,
    marginBottom: spacing.md,
  },
  text: { flex: 1, fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurface },
  bold: { fontFamily: font.semibold, color: colors.onSurface },
  muted: { color: colors.muted },
});
