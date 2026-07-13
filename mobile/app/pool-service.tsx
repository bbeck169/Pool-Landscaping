import React, { useCallback, useMemo, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, RefreshControl } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Loading, EmptyState } from "@/src/components/ui";
import { Header, IconButton } from "@/src/components/widgets";
import { exportCsv, toCsvRow } from "@/src/utils/exportCsv";

function iso(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
function weekRange(offset: number) {
  const now = new Date();
  const monday = new Date(now);
  monday.setDate(now.getDate() - ((now.getDay() + 6) % 7) + offset * 7);
  const sunday = new Date(monday);
  sunday.setDate(monday.getDate() + 6);
  return { from: iso(monday), to: iso(sunday) };
}
const pretty = (s: string) => { try { return new Date(s + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" }); } catch { return s; } };

export default function PoolServiceReport() {
  const [offset, setOffset] = useState(0);
  const range = useMemo(() => weekRange(offset), [offset]);
  const [data, setData] = useState<any>({ rows: [], total_completed: 0, total_skipped: 0 });
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try { setData(await api.get(`/reports/pool-service?date_from=${range.from}&date_to=${range.to}`)); }
    catch { setData({ rows: [], total_completed: 0, total_skipped: 0 }); }
    finally { setLoading(false); setRefreshing(false); }
  }, [range.from, range.to]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const doExport = () => {
    const header = toCsvRow(["Technician", "Pools Completed", "Skipped"]);
    const body = (data.rows || []).map((r: any) => toCsvRow([r.technician_name, r.completed, r.skipped]));
    exportCsv(`pool_service_${range.from}_${range.to}.csv`, [header, ...body].join("\n"));
  };

  if (loading) return <Loading testID="pool-report-loading" />;

  return (
    <View style={styles.root}>
      <Header title="Pool Service Report" back subtitle="Pools completed per tech (excl. skips)" right={<IconButton icon="download-outline" onPress={doExport} testID="pool-export" />} />

      <View style={styles.weekNav}>
        <Pressable style={styles.navBtn} onPress={() => { setLoading(true); setOffset((o) => o - 1); }} testID="pool-prev-week"><Ionicons name="chevron-back" size={20} color={colors.brand} /></Pressable>
        <Text style={styles.weekLabel}>{pretty(range.from)} – {pretty(range.to)}{offset === 0 ? " · This week" : ""}</Text>
        <Pressable style={styles.navBtn} onPress={() => { setLoading(true); setOffset((o) => o + 1); }} disabled={offset >= 0} testID="pool-next-week"><Ionicons name="chevron-forward" size={20} color={offset >= 0 ? colors.muted : colors.brand} /></Pressable>
      </View>

      <View style={styles.totals}>
        <View style={styles.totalBox}><Text style={styles.totalNum}>{data.total_completed}</Text><Text style={styles.totalLabel}>Completed</Text></View>
        <View style={styles.totalBox}><Text style={[styles.totalNum, { color: colors.muted }]}>{data.total_skipped}</Text><Text style={styles.totalLabel}>Skipped</Text></View>
      </View>

      {(!data.rows || data.rows.length === 0) ? (
        <EmptyState icon="water-outline" title="No service this week" subtitle="Completed pool visits will appear here." testID="pool-report-empty" />
      ) : (
        <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingTop: 0 }} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}>
          {data.rows.map((r: any) => (
            <View key={r.technician_id} style={styles.card} testID={`pool-tech-${r.technician_id}`}>
              <View style={styles.avatar}><Ionicons name="person" size={16} color="#fff" /></View>
              <Text style={styles.techName}>{r.technician_name}</Text>
              <View style={{ alignItems: "flex-end" }}>
                <Text style={styles.count}>{r.completed} pools</Text>
                {r.skipped > 0 ? <Text style={styles.skipped}>{r.skipped} skipped</Text> : null}
              </View>
            </View>
          ))}
        </ScrollView>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  weekNav: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.lg, paddingVertical: spacing.md },
  navBtn: { width: 40, height: 40, borderRadius: 20, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, alignItems: "center", justifyContent: "center" },
  weekLabel: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  totals: { flexDirection: "row", gap: spacing.md, paddingHorizontal: spacing.lg, marginBottom: spacing.md },
  totalBox: { flex: 1, backgroundColor: colors.surface, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, padding: spacing.md, alignItems: "center" },
  totalNum: { fontFamily: font.bold, fontSize: fontSize["2xl"], color: colors.brand },
  totalLabel: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted },
  card: { flexDirection: "row", alignItems: "center", gap: spacing.md, backgroundColor: colors.surface, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, padding: spacing.md, marginBottom: spacing.sm },
  avatar: { width: 34, height: 34, borderRadius: 17, backgroundColor: colors.brand, alignItems: "center", justifyContent: "center" },
  techName: { flex: 1, fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  count: { fontFamily: font.bold, fontSize: fontSize.base, color: colors.onSurface },
  skipped: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
});
