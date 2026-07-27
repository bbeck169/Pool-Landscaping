/**
 * Phase 32 · SyncStatusPill
 *
 * Small pill that shows in the header area indicating sync state:
 * - ✅ Online (green dot)
 * - 🔄 Syncing (blue spinner)
 * - ⚠️ Pending (amber with count)
 * - ❌ Offline (red dot)
 */
import React from "react";
import { View, Text, StyleSheet, Pressable, ActivityIndicator } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { useSyncManager, SyncStatus } from "@/src/services/SyncManager";
import { font, fontSize, spacing, radius, colors } from "@/src/theme";

const STATUS_CFG: Record<SyncStatus, { bg: string; fg: string; icon: string; label: string }> = {
  idle: { bg: "#DCFCE7", fg: "#166534", icon: "cloud-done-outline", label: "Synced" },
  syncing: { bg: "#DBEAFE", fg: "#1E40AF", icon: "sync-outline", label: "Syncing" },
  error: { bg: "#FEF3C7", fg: "#854D0E", icon: "alert-circle-outline", label: "Retry" },
  offline: { bg: "#FEE2E2", fg: "#991B1B", icon: "cloud-offline-outline", label: "Offline" },
};

export default function SyncStatusPill() {
  const { syncStatus, outboxCount, syncNow, isOnline } = useSyncManager();
  const cfg = STATUS_CFG[syncStatus];

  const showPending = outboxCount > 0 && syncStatus !== "syncing";
  const effectiveCfg = showPending
    ? { bg: "#FEF3C7", fg: "#854D0E", icon: "time-outline", label: `${outboxCount} pending` }
    : cfg;

  return (
    <Pressable
      testID="sync-status-pill"
      style={[s.pill, { backgroundColor: effectiveCfg.bg }]}
      onPress={() => { if (isOnline) syncNow(); }}
      hitSlop={8}
    >
      {syncStatus === "syncing" ? (
        <ActivityIndicator size={12} color={effectiveCfg.fg} />
      ) : (
        <Ionicons name={effectiveCfg.icon as any} size={12} color={effectiveCfg.fg} />
      )}
      <Text style={[s.text, { color: effectiveCfg.fg }]} testID="sync-status-label">
        {effectiveCfg.label}
      </Text>
    </Pressable>
  );
}

const s = StyleSheet.create({
  pill: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: radius.pill,
  },
  text: {
    fontFamily: font.semibold,
    fontSize: 11,
  },
});
