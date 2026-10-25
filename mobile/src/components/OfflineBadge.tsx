/**
 * Phase 1 Offline Read · Enhanced OfflineBadge
 *
 * Fix 3 — Honest sync status:
 *   - "Offline — 5 of 5 jobs cached • synced 7:42 AM" (clean sync)
 *   - "Offline — 3 of 5 jobs cached • partial sync 7:42 AM" (partial)
 *   - "Partial sync: 3 of 5" (when online but partial)
 *   - "Sync failed — retry" (when nothing cached)
 */
import React from "react";
import { View, Text, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { useOnline, getSecondsSinceLastSuccess } from "@/src/lib/offline/netStatus";
import { font, fontSize, radius, spacing } from "@/src/theme";
import { TECH_NOT_LINKED_COPY } from "@/src/lib/syncErrors";

type SyncStatus = "synced" | "partial" | "failed" | "idle" | "tech_not_linked";

type CacheStats = {
  cached: number;
  total: number;
  lastSyncedAt: string; // ISO
  syncStatus?: SyncStatus;
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
  const status = cacheStats?.syncStatus || "idle";

  // Show when offline, stale, or sync is partial/failed/tech-not-linked (even online)
  const showPartialOnline = online && (status === "partial" || status === "failed" || status === "tech_not_linked");
  if (online && !staleForced && !showPartialOnline) return null;

  const hasStats = cacheStats && cacheStats.total > 0;
  const timeStr = cacheStats?.lastSyncedAt ? _formatTime(cacheStats.lastSyncedAt) : "";
  const offline = !online;

  // ── Determine pill style + label ────────────────────────────────────
  let bg = "#E5E7EB";
  let fg = "#4B5563";
  let icon: "cloud-offline-outline" | "alert-circle" | "sync-outline" | "checkmark-circle-outline" | "information-circle" = "cloud-offline-outline";
  let label = "";

  if (status === "tech_not_linked") {
    // TD-mobile-sync-tech-not-linked · admin-action state (BE 409), not a
    // transient failure: amber + info icon, no "retry" wording. Online or offline.
    bg = "#FEF3C7";
    fg = "#92400E";
    icon = "information-circle";
    label = TECH_NOT_LINKED_COPY;
  } else if (offline) {
    if (status === "failed" || (hasStats && cacheStats!.cached === 0)) {
      bg = "#FEE2E2";
      fg = "#991B1B";
      icon = "alert-circle";
      label = "Offline — sync failed";
      if (hasStats) label += ` (0 of ${cacheStats!.total})`;
    } else if (status === "partial" && hasStats) {
      bg = "#FEF3C7";
      fg = "#92400E";
      icon = "cloud-offline-outline";
      label = `Offline — ${cacheStats!.cached} of ${cacheStats!.total} jobs cached`;
      if (timeStr) label += ` • partial ${timeStr}`;
    } else {
      // synced or idle
      label = "Offline";
      if (hasStats) label += ` — ${cacheStats!.cached} of ${cacheStats!.total} jobs cached`;
      if (timeStr) label += ` • synced ${timeStr}`;
    }
  } else {
    // Online but partial/failed
    if (status === "failed") {
      bg = "#FEE2E2";
      fg = "#991B1B";
      icon = "alert-circle";
      label = "Sync failed — retry";
    } else if (status === "partial" && hasStats) {
      bg = "#FEF3C7";
      fg = "#92400E";
      icon = "sync-outline";
      label = `Partial sync: ${cacheStats!.cached} of ${cacheStats!.total}`;
    }
  }

  if (!label) return null;

  return (
    <View style={[styles.pill, { backgroundColor: bg }]} testID={testID || "offline-badge"}>
      <Ionicons name={icon} size={12} color={fg} />
      <Text style={[styles.label, { color: fg }]} testID="offline-badge-label">
        {label}
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
    borderColor: "#D1D5DB",
    borderWidth: 1,
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
    borderRadius: radius.sm,
  },
  label: {
    fontFamily: font.bold,
    fontSize: fontSize.xs || 10,
    letterSpacing: 0.4,
  },
});
