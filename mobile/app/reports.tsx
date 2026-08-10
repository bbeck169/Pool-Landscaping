import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, RefreshControl, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize, money } from "@/src/theme";
import { Loading , StatusChip as Chip } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";

export default function Reports() {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [selMonth, setSelMonth] = useState<{ label: string; value: number } | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await api.get("/reports"));
    } catch {
      setData(null);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  if (loading) {
    return (
      <View style={styles.root}>
        <Header title="Reports" back subtitle="Business insights" />
        <Loading testID="reports-loading" />
      </View>
    );
  }

  const d = data || {};
  const revMax = Math.max(...(d.revenue_series || []).map((x: any) => x.value), 1);
  const custMax = Math.max(...(d.top_customers || []).map((x: any) => x.value), 1);

  return (
    <View style={styles.root}>
      <Header title="Reports" back subtitle="Business insights" />
      <ScrollView
        testID="reports-scroll"
        contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
      >
        <View style={styles.grid}>
          <Kpi icon="cash-outline" label="Revenue" value={money(d.revenue)} tint={colors.brand} />
          <Kpi icon="time-outline" label="Outstanding" value={money(d.outstanding)} tint={colors.warning} />
          <Kpi icon="receipt-outline" label="Avg Ticket" value={money(d.avg_ticket)} tint={colors.brandSecondary} />
          <Kpi icon="checkmark-done-outline" label="Completion" value={`${d.completion_rate || 0}%`} tint={colors.success} />
        </View>

        {/* Revenue trend */}
        <View style={styles.card}>
          <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start" }}>
            <View>
              <Text style={styles.cardTitle}>Revenue Trend</Text>
              <Text style={styles.cardSub}>{selMonth ? "Tap a bar to inspect" : "Last 6 months"}</Text>
            </View>
            {selMonth ? (
              <View style={styles.selPill}>
                <Text style={styles.selMonthLabel}>{selMonth.label}</Text>
                <Text style={styles.selMonthValue}>{money(selMonth.value)}</Text>
              </View>
            ) : null}
          </View>
          <View style={styles.barsRow}>
            {(d.revenue_series || []).map((s: any, i: number) => {
              const isLast = i === (d.revenue_series.length - 1);
              const isSel = selMonth?.label === s.label;
              const h = Math.max(6, (s.value / revMax) * 120);
              return (
                <Pressable
                  key={s.label}
                  style={styles.barCol}
                  onPress={() => setSelMonth(isSel ? null : { label: s.label, value: s.value })}
                  testID={`report-bar-${s.label}`}
                >
                  <Text style={styles.barValue}>{s.value >= 1000 ? `${(s.value / 1000).toFixed(1)}k` : Math.round(s.value)}</Text>
                  <View style={styles.barTrack}>
                    <View style={[styles.bar, { height: h, backgroundColor: isSel ? colors.brandSecondary : isLast ? colors.brand : colors.brandTertiary }]} />
                  </View>
                  <Text style={[styles.barLabel, (isLast || isSel) && { color: isSel ? colors.brandSecondary : colors.brand, fontFamily: font.bold }]}>{s.label}</Text>
                </Pressable>
              );
            })}
          </View>
        </View>

        {/* Jobs by status */}
        {(d.jobs_by_status || []).length ? (
          <View style={styles.card}>
            <Text style={styles.cardTitle}>Jobs by Status</Text>
            <View style={styles.statusWrap}>
              {d.jobs_by_status.map((s: any) => (
                <View key={s.label} style={styles.statusItem} testID={`report-status-${s.label}`}>
                  <Chip status={s.label} />
                  <Text style={styles.statusCount}>{s.value}</Text>
                </View>
              ))}
            </View>
          </View>
        ) : null}

        {/* Revenue by Service moved to its own screen at
            ``/reports/revenue-by-service`` (Feb-2026 parity tile).
            The tile at the top of this page is the entry point. */}

        {/* Top customers */}
        {(d.top_customers || []).length ? (
          <View style={styles.card}>
            <Text style={styles.cardTitle}>Top Customers</Text>
            {d.top_customers.map((c: any) => (
              <View key={c.label} style={styles.svcRow}>
                <Text style={styles.svcLabel} numberOfLines={1}>{c.label}</Text>
                <View style={styles.svcBarTrack}>
                  <View style={[styles.svcBar, { width: `${Math.max(4, (c.value / custMax) * 100)}%`, backgroundColor: colors.brandSecondary }]} />
                </View>
                <Text style={styles.svcValue}>{money(c.value)}</Text>
              </View>
            ))}
          </View>
        ) : null}

        {/* Technician performance */}
        {(d.technician_performance || []).length ? (
          <View style={styles.card}>
            <Text style={styles.cardTitle}>Technician Performance</Text>
            {d.technician_performance.map((t: any) => (
              <View key={t.label} style={styles.techRow} testID={`report-tech-${t.label}`}>
                <View style={styles.techAvatar}>
                  <Text style={styles.techInitial}>{t.label?.charAt(0)?.toUpperCase()}</Text>
                </View>
                <Text style={styles.techName} numberOfLines={1}>{t.label}</Text>
                <View style={styles.techStat}>
                  <Ionicons name="checkmark-circle" size={14} color={colors.success} />
                  <Text style={styles.techStatText}>{t.completed} done</Text>
                </View>
                <View style={styles.techStat}>
                  <Ionicons name="flash" size={14} color={colors.brand} />
                  <Text style={styles.techStatText}>{t.active} active</Text>
                </View>
              </View>
            ))}
          </View>
        ) : null}
      </ScrollView>
    </View>
  );
}

function Kpi({ icon, label, value, tint }: { icon: any; label: string; value: string; tint: string }) {
  return (
    <View style={styles.kpi}>
      <View style={[styles.kpiIcon, { backgroundColor: tint + "1A" }]}>
        <Ionicons name={icon} size={18} color={tint} />
      </View>
      <Text style={styles.kpiValue} numberOfLines={1} adjustsFontSizeToFit>{value}</Text>
      <Text style={styles.kpiLabel}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.md },
  kpi: { width: "47.5%", flexGrow: 1, backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.lg, borderWidth: 1, borderColor: colors.border },
  kpiIcon: { width: 38, height: 38, borderRadius: radius.md, alignItems: "center", justifyContent: "center", marginBottom: spacing.sm },
  kpiValue: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface },
  kpiLabel: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
  card: { backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.lg, borderWidth: 1, borderColor: colors.border, marginTop: spacing.lg },
  cardTitle: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  cardSub: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 1, marginBottom: spacing.md },
  selPill: { alignItems: "flex-end", backgroundColor: colors.brandSecondary + "1A", borderRadius: radius.md, paddingHorizontal: spacing.md, paddingVertical: 6 },
  selMonthLabel: { fontFamily: font.medium, fontSize: 10, color: colors.brandSecondary },
  selMonthValue: { fontFamily: font.bold, fontSize: fontSize.base, color: colors.brandSecondary },
  barsRow: { flexDirection: "row", alignItems: "flex-end", justifyContent: "space-between", height: 170, marginTop: spacing.md },
  barCol: { flex: 1, alignItems: "center", gap: 6 },
  barValue: { fontFamily: font.medium, fontSize: 10, color: colors.muted },
  barTrack: { height: 120, justifyContent: "flex-end" },
  bar: { width: 22, borderRadius: radius.sm },
  barLabel: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted },
  statusWrap: { flexDirection: "row", flexWrap: "wrap", gap: spacing.md },
  statusItem: { flexDirection: "row", alignItems: "center", gap: 6 },
  statusCount: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  svcRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm, marginTop: spacing.sm },
  svcLabel: { width: 96, fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
  svcBarTrack: { flex: 1, height: 10, borderRadius: 5, backgroundColor: colors.surfaceTertiary, overflow: "hidden" },
  svcBar: { height: 10, borderRadius: 5, backgroundColor: colors.brand },
  svcValue: { width: 78, textAlign: "right", fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface },
  techRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm, marginTop: spacing.md },
  techAvatar: { width: 34, height: 34, borderRadius: 17, backgroundColor: colors.brandTertiary, alignItems: "center", justifyContent: "center" },
  techInitial: { fontFamily: font.bold, fontSize: fontSize.base, color: colors.brand },
  techName: { flex: 1, fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  techStat: { flexDirection: "row", alignItems: "center", gap: 4 },
  techStatText: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
});
