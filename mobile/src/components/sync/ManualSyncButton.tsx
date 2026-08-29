/**
 * Phase O6 · ManualSyncButton — a "Sync now" button for the
 * More/Settings screen. Shows last sync time and triggers flush.
 */
import React, { useState } from "react";
import { View, Text, StyleSheet, TouchableOpacity, ActivityIndicator, Alert } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useSyncStatus } from "@/src/services/sync/status";
import { triggerSyncNow } from "@/src/services/sync/queue";
import { retryAllStalled } from "@/src/services/sync/photoWorker";
import { font, fontSize, spacing, radius, colors } from "@/src/theme";

export function ManualSyncButton() {
  const { pending_count, failed_count, last_sync_at, is_online, is_flushing } = useSyncStatus();
  const [syncing, setSyncing] = useState(false);

  const total = pending_count + failed_count;

  const handleSync = async () => {
    if (!is_online) {
      Alert.alert("Offline", "Cannot sync while offline. Please reconnect.");
      return;
    }
    setSyncing(true);
    try {
      const [queueResult] = await Promise.all([
        triggerSyncNow(),
        retryAllStalled().catch(() => {}),
      ]);
      if (queueResult.failed > 0) {
        Alert.alert(
          "Sync completed with errors",
          `${queueResult.succeeded} synced, ${queueResult.failed} failed.`,
        );
      } else if (queueResult.succeeded > 0) {
        Alert.alert("Sync complete", `${queueResult.succeeded} change${queueResult.succeeded > 1 ? "s" : ""} synced.`);
      } else {
        Alert.alert("All synced", "No pending changes.");
      }
    } catch (e: any) {
      Alert.alert("Sync error", e?.message || "Unknown error");
    } finally {
      setSyncing(false);
    }
  };

  const lastSyncLabel = last_sync_at
    ? `Last sync: ${new Date(last_sync_at).toLocaleTimeString()}`
    : "Never synced";

  return (
    <View style={s.container} testID="manual-sync-section">
      <View style={s.row}>
        <View style={s.left}>
          <View style={s.iconWrap}>
            <Ionicons name="sync" size={20} color={colors.brand} />
          </View>
          <View>
            <Text style={s.title}>Sync Status</Text>
            <Text style={s.subtitle}>
              {total > 0
                ? `${total} change${total > 1 ? "s" : ""} pending`
                : "All changes synced"}
            </Text>
            <Text style={s.meta}>{lastSyncLabel}</Text>
          </View>
        </View>
      </View>
      <TouchableOpacity
        testID="manual-sync-btn"
        style={[s.btn, (!is_online || syncing || is_flushing) && s.btnDisabled]}
        onPress={handleSync}
        disabled={!is_online || syncing || is_flushing}
      >
        {syncing || is_flushing ? (
          <ActivityIndicator size={14} color="#fff" />
        ) : (
          <Ionicons name="cloud-upload" size={14} color="#fff" />
        )}
        <Text style={s.btnText}>
          {syncing || is_flushing ? "Syncing..." : "Sync now"}
        </Text>
      </TouchableOpacity>
    </View>
  );
}

const s = StyleSheet.create({
  container: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    padding: spacing.lg,
    borderWidth: 1,
    borderColor: colors.border,
  },
  row: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  left: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
  },
  iconWrap: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: colors.brandTertiary,
    justifyContent: "center",
    alignItems: "center",
  },
  title: {
    fontFamily: font.semibold,
    fontSize: fontSize.base,
    color: colors.onSurface,
  },
  subtitle: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
    marginTop: 2,
  },
  meta: {
    fontFamily: font.regular,
    fontSize: 11,
    color: colors.surfaceTertiary,
    marginTop: 2,
  },
  btn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    backgroundColor: colors.brand,
    paddingVertical: spacing.sm + 2,
    paddingHorizontal: spacing.lg,
    borderRadius: radius.sm,
    marginTop: spacing.md,
  },
  btnDisabled: {
    opacity: 0.5,
  },
  btnText: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: "#fff",
  },
});
