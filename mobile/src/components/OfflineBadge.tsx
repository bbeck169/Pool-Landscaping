/**
 * Feb-2026 · Phase 1 offline foundation — offline badge pill.
 *
 * Renders a compact "Offline" pill in a screen header when either
 *   • ``netinfo`` reports ``isConnected === false``, OR
 *   • ``markApiSuccess()`` hasn't been called in the last 60 s AND
 *     the caller passes ``renderStale``
 *
 * Consumers embed it in the header row of Schedule / Job Detail /
 * Checklist screens.  Non-intrusive — muted grey, single icon +
 * one-word label.
 */
import React from "react";
import { View, Text, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { useOnline, getSecondsSinceLastSuccess } from "@/src/lib/offline/netStatus";
import { font, fontSize, radius, spacing } from "@/src/theme";


type Props = {
  /** Optional — when true, the badge also shows if the last
   *  successful API call was >60 s ago even when netinfo says
   *  online. Default false. */
  renderStale?: boolean;
  testID?: string;
};


export default function OfflineBadge({ renderStale = false, testID }: Props) {
  const online = useOnline();
  const staleForced = renderStale && getSecondsSinceLastSuccess() > 60;
  if (online && !staleForced) return null;

  return (
    <View style={styles.pill} testID={testID || "offline-badge"}>
      <Ionicons name="cloud-offline-outline" size={12} color="#4B5563" />
      <Text style={styles.label}>Offline</Text>
    </View>
  );
}


const styles = StyleSheet.create({
  pill: {
    flexDirection: "row",
    alignItems: "center",
    alignSelf: "flex-start",
    gap: 4,
    backgroundColor: "#E5E7EB",
    borderColor: "#D1D5DB",
    borderWidth: 1,
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
    borderRadius: radius.sm,
  },
  label: {
    fontFamily: font.bold,
    fontSize: fontSize.xs || 10,
    color: "#4B5563",
    letterSpacing: 0.4,
  },
});
