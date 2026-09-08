/**
 * Phase 1 Offline Read · Enhanced OfflineBadge
 *
 * When offline, shows cache freshness stats:
 *   "Offline — 5 of 5 jobs cached • last synced 7:42 AM"
 * When online, hidden (unless renderStale forces it).
 */
import React from "react";
import { View, Text, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { useOnline, getSecondsSinceLastSuccess } from "@/src/lib/offline/netStatus";
import { font, fontSize, radius, spacing } from "@/src/theme";

type CacheStats = {
  cached: number;
  total: number;
  lastSyncedAt: string; // ISO
};

type Props = {
  renderStale?: boolean;
  cacheStats?: CacheStats | null;
  testID?: string;
};

function _formatTime(iso: string): string {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  } catch {
    return "";
  }
}

export default function OfflineBadge({ renderStale = false, cacheStats, testID }: Props) {
  const online = useOnline();
  const staleForced = renderStale && getSecondsSinceLastSuccess() > 60;
  if (online && !staleForced) return null;

  const hasStats = cacheStats && cacheStats.total > 0;
  const timeStr = cacheStats?.lastSyncedAt ? _formatTime(cacheStats.lastSyncedAt) : "";

  return (
    <View style={styles.pill} testID={testID || "offline-badge"}>
      <Ionicons name="cloud-offline-outline" size={12} color="#4B5563" />
      <Text style={styles.label}>
        Offline
        {hasStats ? ` — ${cacheStats!.cached} of ${cacheStats!.total} jobs cached` : ""}
        {timeStr ? ` • synced ${timeStr}` : ""}
      </Text>
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
