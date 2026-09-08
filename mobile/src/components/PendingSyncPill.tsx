/**
 * Phase 2 · PendingSyncPill — per-item "pending sync" indicator.
 *
 * Small inline pill that shows "⤴ Pending" on a job card
 * when that entity has queued writes.
 */
import React from "react";
import { View, Text, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { font, radius } from "@/src/theme";

interface Props {
  count?: number;
  testID?: string;
}

export default function PendingSyncPill({ count = 1, testID }: Props) {
  if (count <= 0) return null;

  return (
    <View style={styles.pill} testID={testID || "pending-sync-pill"}>
      <Ionicons name="cloud-upload-outline" size={9} color="#854D0E" />
      <Text style={styles.text}>
        {count === 1 ? "Pending sync" : `${count} pending`}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  pill: {
    flexDirection: "row",
    alignItems: "center",
    alignSelf: "flex-start",
    gap: 3,
    backgroundColor: "#FEF3C7",
    borderColor: "#FDE68A",
    borderWidth: 1,
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: radius.sm,
    marginTop: 3,
  },
  text: {
    fontFamily: font.bold,
    fontSize: 9,
    color: "#854D0E",
    letterSpacing: 0.3,
  },
});
