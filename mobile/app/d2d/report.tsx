import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, RefreshControl } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Loading, EmptyState } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";

export default function D2DReport() {
  const [data, setData] = useState<any>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try { setData(await api.get("/d2d/report")); } catch { setData({ totals: null, reps: [] }); }
    finally { setRefreshing(false); }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  if (!data) return <Loading testID="d2d-report-loading" />;
  const t = data.totals;

  return (
    <View style={styles.root}>
      <Header title="D2D Sales Report" back subtitle="Team canvassing performance" />
      <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}>
        {t ? (
          <View style={styles.totalRow}>
            <Total label="Knocks" value={t.knocks} color={colors.brand} />
            <Total label="Leads" value={t.leads} color="#0284C7" />
            <Total label="Sold" value={t.sold} color="#16A34A" />
            <Total label="Conv. %" value={`${t.conversion_rate}%`} color="#7C3AED" />
          </View>
        ) : null}

        <Text style={styles.sectionTitle}>By Rep</Text>
        {data.reps.length === 0 ? (
          <EmptyState icon="bar-chart-outline" title="No canvassing yet" subtitle="Rep stats appear as techs log doors." testID="d2d-report-empty" />
        ) : (
          data.reps.map((r: any) => (
            <View key={r.tech_id} style={styles.repCard} testID={`d2d-rep-${r.tech_id}`}>
              <Text style={styles.repName}>{r.tech_name}</Text>
              <View style={styles.repStats}>
                <RepStat label="Knocks" value={r.knocks} />
                <RepStat label="Leads" value={r.leads} />
                <RepStat label="Sold" value={r.sold} />
                <RepStat label="Won" value={r.conversions} />
                <RepStat label="Conv." value={`${r.conversion_rate}%`} />
              </View>
              <View style={styles.breakdown}>
                <Chip color="#16A34A" label={`${r.sold} sold`} />
                <Chip color="#0284C7" label={`${r.interested} interested`} />
                <Chip color="#A16207" label={`${r.callback} callback`} />
                <Chip color="#DC2626" label={`${r.not_interested} not int.`} />
                <Chip color="#64748B" label={`${r.not_home} not home`} />
              </View>
            </View>
          ))
        )}
      </ScrollView>
    </View>
  );
}

function Total({ label, value, color }: any) {
  return (
    <View style={styles.total}>
      <Text style={[styles.totalVal, { color }]}>{value}</Text>
      <Text style={styles.totalLabel}>{label}</Text>
    </View>
  );
}
function RepStat({ label, value }: any) {
  return (
    <View style={styles.repStat}>
      <Text style={styles.repStatVal}>{value}</Text>
      <Text style={styles.repStatLabel}>{label}</Text>
    </View>
  );
}
function Chip({ color, label }: any) {
  return (
    <View style={[styles.chip, { backgroundColor: color + "1A" }]}>
      <Text style={[styles.chipText, { color }]}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  totalRow: { flexDirection: "row", gap: spacing.sm },
  total: { flex: 1, backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: colors.border, alignItems: "center" },
  totalVal: { fontFamily: font.bold, fontSize: fontSize.xl },
  totalLabel: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
  sectionTitle: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface, marginTop: spacing.xl, marginBottom: spacing.md },
  repCard: { backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.lg, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.md },
  repName: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  repStats: { flexDirection: "row", marginTop: spacing.md },
  repStat: { flex: 1, alignItems: "center" },
  repStatVal: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.brand },
  repStatLabel: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  breakdown: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm, marginTop: spacing.md, paddingTop: spacing.md, borderTopWidth: 1, borderTopColor: colors.divider },
  chip: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: radius.pill },
  chipText: { fontFamily: font.semibold, fontSize: fontSize.sm },
});
