/**
 * WW (web cc8858980 / BE 5d105aaa3) — "Edited after completion" badge.
 *
 * POST-edit cue: callers pass `visible={job.edited_after_completion === true}`
 * (BE denorm flipped on the first post-completion mutation). Sits alongside
 * the PRE-edit TD-78b `ClosedJobEditsBanner`, never replaces it. Chip
 * geometry mirrors `StatusChip` (src/components/ui.tsx); palette = web amber.
 * Admin/tech surfaces only — no portal screen renders this.
 */
import React from "react";
import { View, Text, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { radius, font, fontSize } from "@/src/theme";

const BG = "#FEF3C7";
const FG = "#78350F";
const BORDER = "#FCD34D";

export default function EditedAfterCompletionBadge({
  visible, testID = "edited-after-completion-badge",
}: { visible: boolean; testID?: string }) {
  if (!visible) return null;
  return (
    <View style={styles.chip} testID={testID} accessibilityRole="text" accessibilityLabel="Edited after completion">
      <Ionicons name="time-outline" size={12} color={FG} />
      <Text style={styles.text}>Edited after completion</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  chip: {
    flexDirection: "row", alignItems: "center", gap: 4, alignSelf: "flex-start",
    paddingHorizontal: 10, paddingVertical: 4, borderRadius: radius.pill,
    backgroundColor: BG, borderWidth: 1, borderColor: BORDER,
  },
  text: { fontFamily: font.semibold, fontSize: fontSize.sm, color: FG },
});
