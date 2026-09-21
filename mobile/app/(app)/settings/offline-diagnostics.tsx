/**
 * Phase 1 Offline Read · Offline Diagnostics Screen
 *
 * Hidden settings screen showing cache status, byte size, job count,
 * last hydrate timestamp, and a "Rebuild cache" button.
 *
 * Route: /(app)/settings/offline-diagnostics
 * Access: long-press on Settings → "Offline diagnostics" row.
 */
import React, { useEffect, useState, useCallback } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable,
  ActivityIndicator, Alert,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { useAuth } from "@/src/auth";
import { useOnline } from "@/src/offline";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { countCacheKeys, cacheByteSize, clearAllCache } from "@/src/services/readCache";
import {
  getHydrationMeta,
  restoreHydrationMeta,
  hydrateToday,
} from "@/src/services/routeHydrator";
import type { HydrationMeta } from "@/src/services/routeHydrator";

function _fmtBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1048576).toFixed(1)} MB`;
}

function _fmtTime(iso: string): string {
  if (!iso) return "Never";
  try { return new Date(iso).toLocaleString(); } catch { return iso; }
}

export default function OfflineDiagnosticsScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const online = useOnline();
  const [meta, setMeta] = useState<HydrationMeta | null>(null);
  const [totalKeys, setTotalKeys] = useState(0);
  const [jobKeys, setJobKeys] = useState(0);
  const [bytes, setBytes] = useState(0);
  const [refreshing, setRefreshing] = useState(false);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    try {
      if (user?.id) await restoreHydrationMeta(user.id);
      setMeta(getHydrationMeta());
      setTotalKeys(await countCacheKeys());
      setJobKeys(await countCacheKeys("job:"));
      setBytes(await cacheByteSize());
    } catch {} finally { setRefreshing(false); }
  }, [user?.id]);

  useEffect(() => { refresh(); }, [refresh]);

  const handleRebuild = async () => {
    if (!user?.id) return;
    if (!online) {
      Alert.alert("Offline", "Connect to the internet to rebuild cache.");
      return;
    }
    setRefreshing(true);
    const isTechRole = user.role === "technician" || (user.role as string) === "tech";
    const techScope = isTechRole ? { role: user.role, technicianId: user.technician_id ?? null } : undefined;
    await hydrateToday(user.id, techScope);
    await refresh();
    setRefreshing(false);
    showToast("Cache rebuilt from server.");
  };

  const handlePurge = () => {
    Alert.alert("Purge cache?", "This will remove all cached data. You'll need connectivity to refetch.", [
      { text: "Cancel", style: "cancel" },
      {
        text: "Purge", style: "destructive", onPress: async () => {
          await clearAllCache().catch(() => {});
          await refresh();
        },
      },
    ]);
  };

  return (
    <ScrollView style={styles.root} contentContainerStyle={styles.content}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} style={styles.backBtn} testID="diag-back">
          <Ionicons name="chevron-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.title}>Offline Diagnostics</Text>
      </View>

      <View style={styles.card} testID="offline-diag-card">
        <Row label="Status" value={online ? "🟢 Online" : "🔴 Offline"} testID="diag-status" />
        <Row label="Total cache entries" value={String(totalKeys)} testID="diag-total-keys" />
        <Row label="Job cache entries" value={String(jobKeys)} testID="diag-job-keys" />
        <Row label="Cache size" value={_fmtBytes(bytes)} testID="diag-cache-size" />
        <Row label="Jobs on route" value={String(meta?.totalJobs ?? 0)} testID="diag-route-total" />
        <Row label="Jobs cached" value={String(meta?.cachedJobs ?? 0)} testID="diag-route-cached" />
        <Row label="Last hydrated" value={_fmtTime(meta?.lastSyncedAt || "")} testID="diag-last-synced" />
        <Row label="Hydration active" value={meta?.inProgress ? "Yes" : "No"} testID="diag-in-progress" />
      </View>

      <View style={styles.actions}>
        <Pressable style={[styles.actionBtn, { backgroundColor: colors.brand }]} onPress={handleRebuild} disabled={refreshing} testID="diag-rebuild-btn">
          {refreshing ? <ActivityIndicator color="#fff" size="small" /> : <Ionicons name="refresh" size={16} color="#fff" />}
          <Text style={styles.actionText}>Rebuild cache</Text>
        </Pressable>

        <Pressable style={[styles.actionBtn, { backgroundColor: "#DC2626" }]} onPress={handlePurge} testID="diag-purge-btn">
          <Ionicons name="trash-outline" size={16} color="#fff" />
          <Text style={styles.actionText}>Purge cache</Text>
        </Pressable>
      </View>

      {refreshing ? (
        <View style={{ alignItems: "center", marginTop: spacing.md }}>
          <ActivityIndicator size="small" color={colors.brand} />
          <Text style={{ fontFamily: font.regular, fontSize: fontSize.xs, color: colors.muted, marginTop: 4 }}>Refreshing…</Text>
        </View>
      ) : null}
    </ScrollView>
  );
}

function Row({ label, value, testID }: { label: string; value: string; testID: string }) {
  return (
    <View style={styles.row} testID={testID}>
      <Text style={styles.rowLabel}>{label}</Text>
      <Text style={styles.rowValue}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  content: { paddingBottom: 60 },
  header: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    paddingHorizontal: spacing.md, paddingTop: 56, paddingBottom: spacing.md,
  },
  backBtn: { width: 36, height: 36, alignItems: "center", justifyContent: "center" },
  title: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface },
  card: {
    marginHorizontal: spacing.md, borderRadius: radius.md,
    backgroundColor: colors.surfaceSecondary, borderWidth: 1,
    borderColor: colors.border, overflow: "hidden",
  },
  row: {
    flexDirection: "row", justifyContent: "space-between", alignItems: "center",
    paddingHorizontal: spacing.md, paddingVertical: 12,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border,
  },
  rowLabel: { fontFamily: font.medium, fontSize: fontSize.base, color: colors.onSurface },
  rowValue: { fontFamily: font.bold, fontSize: fontSize.base, color: colors.muted },
  actions: {
    flexDirection: "row", gap: spacing.sm, marginTop: spacing.lg,
    paddingHorizontal: spacing.md,
  },
  actionBtn: {
    flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: 6, paddingVertical: 14, borderRadius: radius.md,
  },
  actionText: { fontFamily: font.bold, fontSize: fontSize.base, color: "#fff" },
});
