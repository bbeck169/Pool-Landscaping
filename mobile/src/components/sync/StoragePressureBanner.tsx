/**
 * Phase O6 · StoragePressureBanner — shows a warning when
 * pending photos or queue entries exceed thresholds.
 */
import React from "react";
import { View, Text, StyleSheet, TouchableOpacity } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useStoragePressure } from "@/src/services/storageWatchdog";
import { triggerSyncNow } from "@/src/services/sync/queue";
import { isOnlineNow } from "@/src/services/sync/netBus";
import { font, spacing } from "@/src/theme";

export function StoragePressureBanner() {
  const pressure = useStoragePressure();

  if (pressure.level === "ok" || !pressure.message) return null;

  const isCritical = pressure.level === "critical";
  const bg = isCritical ? "#FEE2E2" : "#FEF3C7";
  const fg = isCritical ? "#991B1B" : "#854D0E";
  const icon = isCritical ? "warning" : "alert-circle-outline";

  const handleSync = () => {
    if (isOnlineNow()) {
      triggerSyncNow().catch(() => {});
    }
  };

  return (
    <View
      style={[s.container, { backgroundColor: bg }]}
      testID="storage-pressure-banner"
    >
      <Ionicons name={icon as any} size={16} color={fg} />
      <Text style={[s.text, { color: fg }]}>{pressure.message}</Text>
      {isOnlineNow() && (
        <TouchableOpacity
          testID="storage-sync-btn"
          onPress={handleSync}
          style={s.syncBtn}
        >
          <Text style={[s.syncText, { color: fg }]}>Sync</Text>
        </TouchableOpacity>
      )}
    </View>
  );
}

const s = StyleSheet.create({
  container: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
    gap: spacing.sm,
  },
  text: {
    fontFamily: font.regular,
    fontSize: 12,
    flex: 1,
  },
  syncBtn: {
    paddingHorizontal: spacing.sm,
    paddingVertical: 4,
  },
  syncText: {
    fontFamily: font.semibold,
    fontSize: 12,
    textDecorationLine: "underline",
  },
});
