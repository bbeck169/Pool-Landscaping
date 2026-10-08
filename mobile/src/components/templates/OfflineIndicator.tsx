/**
 * Templates Library — Phase 3 (Mobile) · offline / sync indicator.
 * Visible only when the device is offline or this instance has queued
 * (unsynced) edits.
 */
import React from "react";
import { View, Text, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { font } from "@/src/theme";

export default function OfflineIndicator({ online, hasPending, testID = "template-offline-indicator" }: {
  online: boolean;
  hasPending: boolean;
  testID?: string;
}) {
  if (online && !hasPending) return null;
  const label = "Offline — will sync";
  return (
    <View style={styles.pill} testID={testID} accessibilityRole="text" accessibilityLabel={label}>
      <Ionicons name="cloud-offline-outline" size={14} color="#A16207" />
      <Text style={styles.text}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  pill: {
    flexDirection: "row", alignItems: "center", gap: 4, alignSelf: "flex-start",
    backgroundColor: "#FEF9C3", borderColor: "#FDE68A", borderWidth: 1,
    paddingHorizontal: 8, paddingVertical: 3, borderRadius: 999,
  },
  text: { fontSize: 11, fontFamily: font.bold, color: "#A16207" },
});
