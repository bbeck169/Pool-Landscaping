// Phase 16 · Feb-2026 — Dispatch Savings KPI + modal (Manager+).
//
// Small screen accessible from the existing Dispatch screen. Shows a
// weekly km saved KPI + simple bar-strip sparkline (no chart lib) + a
// 7d/30d toggle + a Top techs table.
import React, { useCallback, useMemo, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, RefreshControl } from "react-native";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Card, Loading, EmptyState } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";
import { RoleGate } from "@/src/components/RoleGate";

type Row = { technician_id?: string; technician_name?: string; km_saved?: number };
type Payload = {
  range?: "7d" | "30d";
  total_km_saved?: number;
  daily_km_saved?: number[];
  top_techs?: Row[];
};

export default function DispatchSavings() {
  const [range, setRange] = useState<"7d" | "30d">("7d");
  const [data, setData] = useState<Payload | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const j: any = await api.get(`/dispatch/route/savings/weekly?range=${range}`);
      setData(j || null);
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [range]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const max = useMemo(() => {
    const arr = data?.daily_km_saved || [];
    return Math.max(1, ...arr);
  }, [data]);

  return (
    <RoleGate level="dispatcher_plus">
      <View style={styles.container}>
        <Header title="Dispatch savings" />
        <ScrollView
          contentContainerStyle={styles.body}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={async () => {
              setRefreshing(true); await load(); setRefreshing(false);
            }} />
          }
        >
          <View style={styles.toggleRow}>
            {(["7d", "30d"] as const).map((r) => {
              const on = range === r;
              return (
                <Pressable
                  key={r}
                  testID={`dispatch-savings-range-${r}`}
                  accessibilityLabel={`Range ${r}`}
                  onPress={() => setRange(r)}
                  style={[styles.toggleChip, on && styles.toggleChipOn]}
                >
                  <Text style={[styles.toggleText, on && styles.toggleTextOn]}>{r}</Text>
                </Pressable>
              );
            })}
          </View>

          {loading ? (
            <Loading />
          ) : (
            <>
              <Card>
                <Text style={styles.kpiLabel}>Team saved this {range === "7d" ? "week" : "month"}</Text>
                <Text style={styles.kpiValue} testID="dispatch-savings-km">
                  {(data?.total_km_saved ?? 0).toFixed(1)} km
                </Text>
                {/* Sparkline: bar strip in plain Views */}
                <View style={styles.spark}>
                  {(data?.daily_km_saved || []).map((v, i) => (
                    <View
                      key={i}
                      style={[styles.sparkBar, {
                        height: 4 + Math.round((v / max) * 40),
                        backgroundColor: colors.brand,
                      }]}
                    />
                  ))}
                </View>
              </Card>

              <Card>
                <Text style={styles.sectionLabel}>Top techs</Text>
                {(data?.top_techs || []).length === 0 ? (
                  <EmptyState
                    icon="trophy-outline"
                    title="No savings recorded yet"
                    subtitle="Optimize a route to start the leaderboard."
                    testID="dispatch-savings-empty"
                  />
                ) : (
                  (data?.top_techs || []).slice(0, 10).map((row, i) => (
                    <View key={row.technician_id || i} style={styles.techRow}
                          testID={`dispatch-savings-tech-${i}`}>
                      <Text style={styles.techRank}>{i + 1}</Text>
                      <Text style={styles.techName}>
                        {row.technician_name || "(unnamed)"}
                      </Text>
                      <Text style={styles.techSaved}>
                        {(row.km_saved || 0).toFixed(1)} km
                      </Text>
                    </View>
                  ))
                )}
              </Card>
            </>
          )}
        </ScrollView>
      </View>
    </RoleGate>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.surface },
  body: { padding: spacing.lg, gap: spacing.md, paddingBottom: spacing["3xl"] },
  toggleRow: { flexDirection: "row", gap: 6 },
  toggleChip: { paddingHorizontal: 14, paddingVertical: 6, borderRadius: radius.pill, backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border },
  toggleChipOn: { backgroundColor: colors.brand, borderColor: colors.brand },
  toggleText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
  toggleTextOn: { color: "#FFFFFF" },
  kpiLabel: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted, textTransform: "uppercase", letterSpacing: 0.5 },
  kpiValue: { fontFamily: font.bold, fontSize: 34, color: colors.onSurface, marginTop: 4 },
  spark: { flexDirection: "row", alignItems: "flex-end", gap: 4, height: 48, marginTop: spacing.sm },
  sparkBar: { flex: 1, borderRadius: 2 },
  sectionLabel: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface, marginBottom: spacing.sm },
  techRow: { flexDirection: "row", alignItems: "center", gap: spacing.md, paddingVertical: 8, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.divider },
  techRank: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.brand, width: 28 },
  techName: { flex: 1, fontFamily: font.medium, fontSize: fontSize.base, color: colors.onSurface },
  techSaved: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.success },
});
