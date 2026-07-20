/** Platforms — Phase 3 mobile (view + toggle + sync-now). */
import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, FlatList, ActivityIndicator, TouchableOpacity, Switch, Alert, RefreshControl } from "react-native";
import { useFocusEffect } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { Header } from "@/src/components/widgets";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";
import { listPlatforms, updatePlatform, syncPlatformNow } from "@/src/api/reviews";
import { PlatformIconNative } from "@/src/components/reviews/PlatformIconNative";

const SYNC_CAPABLE = new Set(["google", "facebook", "yelp"]);

export default function ReviewsPlatformsScreen() {
  const [rows, setRows] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [syncing, setSyncing] = useState<string | null>(null);

  const reload = useCallback((silent = false) => {
    if (!silent) setLoading(true);
    listPlatforms()
      .then((d) => setRows((d as any[]).sort((a, b) => (a.sort_order || 0) - (b.sort_order || 0))))
      .catch(() => setRows([]))
      .finally(() => { setLoading(false); setRefreshing(false); });
  }, []);

  useFocusEffect(useCallback(() => { reload(); }, [reload]));

  const onToggle = async (row: any) => {
    try {
      await updatePlatform(row.id, { is_active: !row.is_active });
      reload(true);
    } catch (e: any) { Alert.alert("Error", e.message); }
  };

  const onSync = async (platform: string) => {
    setSyncing(platform);
    try {
      const summary: any = await syncPlatformNow(platform);
      const label = summary.status === "ok"
        ? `Synced ${summary.fetched_count} · +${summary.new_count} new · ${summary.updated_count} updated`
        : `${platform}: ${summary.status}${summary.detail ? " — " + summary.detail : ""}`;
      Alert.alert("Sync complete", label);
    } catch (e: any) {
      Alert.alert("Sync failed", e.message || "Unknown error");
    } finally { setSyncing(null); }
  };

  return (
    <View style={styles.root} testID="reviews-platforms">
      <Header title="Review Platforms" subtitle={`${rows.length} configured`} back />
      {loading ? <ActivityIndicator style={{ marginTop: 40 }} color={colors.brand} /> : (
        <FlatList
          data={rows}
          keyExtractor={(item) => item.id}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); reload(true); }} />}
          contentContainerStyle={{ padding: spacing.lg }}
          renderItem={({ item }) => (
            <View style={styles.row} testID={`reviews-platform-row-${item.id}`}>
              <View style={styles.rowTop}>
                <View style={{ flexDirection: "row", alignItems: "center", gap: 8, flex: 1 }}>
                  <PlatformIconNative code={item.platform} size={18} />
                  <View style={{ flex: 1 }}>
                    <Text style={styles.name} numberOfLines={1}>{item.display_name}</Text>
                    <Text style={styles.meta} numberOfLines={1}>{item.review_url}</Text>
                  </View>
                </View>
                <Switch
                  value={!!item.is_active}
                  onValueChange={() => onToggle(item)}
                  testID={`reviews-platform-toggle-${item.id}`}
                  trackColor={{ false: colors.border, true: colors.brand + "80" }}
                  thumbColor={item.is_active ? colors.brand : colors.muted}
                />
              </View>
              {SYNC_CAPABLE.has(item.platform) ? (
                <TouchableOpacity
                  testID={`reviews-platform-sync-${item.platform}`}
                  style={styles.syncBtn}
                  onPress={() => onSync(item.platform)}
                  disabled={syncing === item.platform}
                >
                  {syncing === item.platform ? <ActivityIndicator size="small" color={colors.brand} /> : (
                    <>
                      <Ionicons name="cloud-download-outline" size={13} color={colors.brand} />
                      <Text style={styles.syncBtnLabel}>Sync now</Text>
                    </>
                  )}
                </TouchableOpacity>
              ) : (
                <View style={styles.badgeManual}>
                  <Ionicons name="lock-closed-outline" size={11} color={colors.muted} />
                  <Text style={styles.badgeManualText}>Manual entry only</Text>
                </View>
              )}
            </View>
          )}
          ListEmptyComponent={<View style={styles.empty}><Ionicons name="globe-outline" size={30} color={colors.muted} /><Text style={styles.emptyText}>No platforms configured</Text><Text style={styles.emptyHint}>Add platforms via the web admin.</Text></View>}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  row: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.lg, marginBottom: spacing.sm, borderWidth: 1, borderColor: colors.border },
  rowTop: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  name: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface, textTransform: "capitalize" },
  meta: { fontFamily: font.regular, fontSize: 11, color: colors.muted, marginTop: 2 },
  syncBtn: { flexDirection: "row", alignItems: "center", gap: 4, alignSelf: "flex-start", marginTop: spacing.sm, backgroundColor: colors.brand + "18", borderRadius: 999, paddingHorizontal: 10, paddingVertical: 4 },
  syncBtnLabel: { fontFamily: font.semibold, fontSize: 11, color: colors.brand },
  badgeManual: { flexDirection: "row", alignItems: "center", gap: 4, alignSelf: "flex-start", marginTop: spacing.sm, paddingHorizontal: 8, paddingVertical: 3, borderRadius: 999, backgroundColor: colors.border + "40" },
  badgeManualText: { fontFamily: font.medium, fontSize: 10, color: colors.muted },
  empty: { alignItems: "center", paddingTop: 60, gap: 6 },
  emptyText: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  emptyHint: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
});
