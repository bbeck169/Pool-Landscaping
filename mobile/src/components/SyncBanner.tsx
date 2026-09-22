import React, { useCallback, useEffect, useRef, useState } from "react";
import { View, Text, StyleSheet, ActivityIndicator } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";

import { font, fontSize, spacing } from "@/src/theme";
import {
  useOnline,
  pendingCount,
  pendingMutationCount,
  flushPendingMutations,
} from "@/src/offline";
import { flushPhotos } from "@/src/services/sync/photoWorker";

/**
 * Global connectivity + sync status strip shown above the staff tab bar.
 * - Offline: amber "working offline" bar (with pending count if any queued).
 * - Online + queued items: blue "syncing" bar; auto-flushes the queues.
 * Renders nothing when online and nothing is pending (no layout shift).
 */
export function SyncBanner() {
  const insets = useSafeAreaInsets();
  const online = useOnline();
  const [pending, setPending] = useState(0);
  const [syncing, setSyncing] = useState(false);
  const wasOffline = useRef(false);

  const refresh = useCallback(async () => {
    const [m, p] = await Promise.all([pendingMutationCount(), pendingCount()]);
    setPending(m + p);
  }, []);

  // Poll queue size so the count stays fresh across screens.
  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 3000);
    return () => clearInterval(t);
  }, [refresh]);

  // On reconnect, replay queued mutations + photo uploads.
  useEffect(() => {
    if (online && wasOffline.current) {
      wasOffline.current = false;
      (async () => {
        setSyncing(true);
        try {
          await flushPendingMutations();
          await flushPhotos();
        } catch {}
        await refresh();
        setSyncing(false);
      })();
    }
    if (!online) wasOffline.current = true;
  }, [online, refresh]);

  if (online && pending === 0 && !syncing) return null;

  const offline = !online;
  const bg = offline ? "#FFEDD5" : "#DBEAFE";
  const fg = offline ? "#9A3412" : "#1E40AF";

  let label = "";
  if (offline) {
    label =
      pending > 0
        ? `Offline — ${pending} change${pending > 1 ? "s" : ""} pending sync`
        : "Offline — working locally";
  } else {
    label = `Syncing ${pending} change${pending === 1 ? "" : "s"}…`;
  }

  return (
    <View style={[styles.bar, { backgroundColor: bg, paddingTop: insets.top + 6 }]} testID="sync-banner">
      {offline ? (
        <Ionicons name="cloud-offline-outline" size={16} color={fg} />
      ) : (
        <ActivityIndicator size="small" color={fg} />
      )}
      <Text style={[styles.text, { color: fg }]} numberOfLines={1}>
        {label}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  bar: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    paddingHorizontal: spacing.lg,
    paddingBottom: spacing.sm,
  },
  text: { flex: 1, fontFamily: font.semibold, fontSize: fontSize.sm },
});
