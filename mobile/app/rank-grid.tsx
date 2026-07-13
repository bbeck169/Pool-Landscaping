import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, FlatList, RefreshControl } from "react-native";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Loading, EmptyState } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";

function rankColor(v: number) {
  if (v <= 3) return "#16A34A";
  if (v <= 7) return "#CA8A04";
  if (v <= 12) return "#EA580C";
  return "#DC2626";
}

export default function RankGrid() {
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      setItems(await api.get("/rank-grid"));
    } catch {
      setItems([]);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  return (
    <View style={styles.root}>
      <Header title="Rank Grid" back subtitle="Local SEO tracking" />
      {loading ? (
        <Loading testID="rankgrid-loading" />
      ) : items.length === 0 ? (
        <EmptyState icon="grid-outline" title="No keywords tracked" subtitle="Add keywords to monitor local rankings." testID="rankgrid-empty" />
      ) : (
        <FlatList
          testID="rankgrid-list"
          data={items}
          keyExtractor={(i) => i.id}
          contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
          renderItem={({ item }) => (
            <View style={styles.card} testID={`rank-${item.id}`}>
              <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
                <Text style={styles.keyword} numberOfLines={1}>{item.keyword}</Text>
                <View style={styles.avgPill}>
                  <Text style={styles.avgText}>Avg #{item.avg_rank}</Text>
                </View>
              </View>
              <View style={styles.gridWrap}>
                <View style={styles.grid}>
                  {(item.grid || []).map((row: number[], ri: number) => (
                    <View key={ri} style={styles.gridRow}>
                      {row.map((v, ci) => (
                        <View key={ci} style={[styles.cell, { backgroundColor: rankColor(v) }]}>
                          <Text style={styles.cellText}>{v}</Text>
                        </View>
                      ))}
                    </View>
                  ))}
                </View>
                <View style={styles.gridSide}>
                  <Text style={styles.top3Value}>{item.top3_pct}%</Text>
                  <Text style={styles.top3Label}>in top 3</Text>
                </View>
              </View>
            </View>
          )}
          ListFooterComponent={
            <View style={styles.legend}>
              {[["1–3", "#16A34A"], ["4–7", "#CA8A04"], ["8–12", "#EA580C"], ["13+", "#DC2626"]].map(([l, c]) => (
                <View key={l} style={styles.legendItem}>
                  <View style={[styles.legendDot, { backgroundColor: c }]} />
                  <Text style={styles.legendText}>{l}</Text>
                </View>
              ))}
            </View>
          }
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  card: { backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.lg, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.md },
  keyword: { flex: 1, fontFamily: font.semibold, fontSize: fontSize.lg, color: colors.onSurface, marginRight: spacing.sm },
  avgPill: { backgroundColor: colors.brandTertiary, borderRadius: radius.pill, paddingHorizontal: 10, paddingVertical: 4 },
  avgText: { fontFamily: font.bold, fontSize: fontSize.sm, color: colors.brand },
  gridWrap: { flexDirection: "row", alignItems: "center", gap: spacing.lg, marginTop: spacing.md },
  grid: { gap: 4 },
  gridRow: { flexDirection: "row", gap: 4 },
  cell: { width: 40, height: 40, borderRadius: radius.sm, alignItems: "center", justifyContent: "center" },
  cellText: { fontFamily: font.bold, fontSize: fontSize.base, color: "#fff" },
  gridSide: { flex: 1, alignItems: "center" },
  top3Value: { fontFamily: font.bold, fontSize: fontSize["2xl"], color: colors.onSurface },
  top3Label: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  legend: { flexDirection: "row", justifyContent: "center", gap: spacing.lg, marginTop: spacing.sm },
  legendItem: { flexDirection: "row", alignItems: "center", gap: 5 },
  legendDot: { width: 12, height: 12, borderRadius: 3 },
  legendText: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
});
