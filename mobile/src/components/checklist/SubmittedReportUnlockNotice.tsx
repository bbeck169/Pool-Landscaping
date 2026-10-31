/**
 * TD-g2 · inline notice for unlock-admin roles on a submitted report:
 * edits on screen are NOT saved until the report is unlocked. The button
 * runs the same save → unlock orchestration as "Save draft".
 */
import React from "react";
import { View, Text, Pressable, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { spacing, radius, font, fontSize } from "@/src/theme";

export default function SubmittedReportUnlockNotice({ onUnlock, disabled = false }: { onUnlock: () => void; disabled?: boolean }) {
  return (
    <View style={s.banner} testID="checklist-submitted-unlock-notice" accessibilityRole="text">
      <Ionicons name="lock-closed-outline" size={18} color="#92400E" />
      <Text style={s.text}>
        <Text style={s.bold}>Submitted report</Text>
        <Text> — edits save only after you unlock it with a reason.</Text>
      </Text>
      <Pressable
        onPress={onUnlock}
        disabled={disabled}
        style={[s.btn, disabled && { opacity: 0.5 }]}
        testID="checklist-unlock-to-save-btn"
        accessibilityRole="button"
      >
        <Text style={s.btnText}>Unlock</Text>
      </Pressable>
    </View>
  );
}

const s = StyleSheet.create({
  banner: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    backgroundColor: "#FEF3C7", borderWidth: 1, borderColor: "#FDE68A",
    borderRadius: radius.lg, paddingLeft: spacing.lg, paddingRight: spacing.sm, paddingVertical: spacing.sm,
    marginBottom: spacing.md,
  },
  text: { flex: 1, fontFamily: font.regular, fontSize: fontSize.sm, color: "#92400E" },
  bold: { fontFamily: font.semibold },
  btn: {
    minHeight: 44, minWidth: 44, paddingHorizontal: spacing.md, borderRadius: radius.md,
    backgroundColor: "#92400E", alignItems: "center", justifyContent: "center",
  },
  btnText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: "#fff" },
});
