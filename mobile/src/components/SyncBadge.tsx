/**
 * Phase 2 · SyncBadge — global "⤴ X items waiting to sync" badge.
 *
 * Shown in the schedule header. Taps navigate to the Sync Center.
 * Uses useSyncStatus() for reactive counts.
 * Hidden when no pending/in_flight/failed items.
 */
import React from "react";
import { Pressable, Text, StyleSheet, ActivityIndicator } from "react-native";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";

import { useSyncStatus } from "@/src/services/sync/status";
import { font, radius } from "@/src/theme";

interface Props {
  testID?: string;
}

export default function SyncBadge({ testID }: Props) {
  const router = useRouter();
  const status = useSyncStatus();

  const waitingCount = status.pending_count + status.in_flight_count;
  const failedCount = status.failed_count;
  const totalCount = waitingCount + failedCount;

  if (totalCount === 0) return null;

  const isFlushing = status.is_flushing;
  const hasFailed = failedCount > 0;

  // Amber for pending, red tint for failed, blue for actively syncing
  const bg = isFlushing ? "#DBEAFE" : hasFailed ? "#FEE2E2" : "#FEF3C7";
  const fg = isFlushing ? "#1E40AF" : hasFailed ? "#991B1B" : "#854D0E";

  let label: string;
  if (isFlushing) {
    label = `Syncing ${waitingCount}…`;
  } else if (hasFailed && waitingCount === 0) {
    label = `${failedCount} failed`;
  } else if (hasFailed) {
    label = `⤴ ${waitingCount} pending · ${failedCount} failed`;
  } else {
    label = `⤴ ${waitingCount} waiting`;
  }

  return (
    <Pressable
      testID={testID || "sync-badge"}
      style={[styles.pill, { backgroundColor: bg }]}
      onPress={() => router.push("/settings/sync-center" as any)}
      hitSlop={8}
    >
      {isFlushing ? (
        <ActivityIndicator size={10} color={fg} />
      ) : hasFailed ? (
        <Ionicons name="alert-circle" size={11} color={fg} />
      ) : (
        <Ionicons name="cloud-upload-outline" size={11} color={fg} />
      )}
      <Text style={[styles.text, { color: fg }]} numberOfLines={1}>
        {label}
      </Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  pill: {
    flexDirection: "row",
    alignItems: "center",
    gap: 3,
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: radius.pill,
    maxWidth: 180,
  },
  text: {
    fontFamily: font.semibold,
    fontSize: 10,
    flexShrink: 1,
  },
});
