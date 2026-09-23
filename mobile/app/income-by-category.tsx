import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, RefreshControl } from "react-native";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize, money } from "@/src/theme";
import { Loading, EmptyState } from "@/src/components/ui";
import { Header, IconButton } from "@/src/components/widgets";
import { exportCsv, toCsvRow } from "@/src/utils/exportCsv";

const BAR_COLORS = ["#0284C7", "#16A34A", "#7C3AED", "#D97706", "#DB2777", "#0891B2", "#65A30D"];

export default function IncomeByCategory() {
  const [data, setData] = useState<{ total: number; rows: any[]; invoice_count: number }>({ total: 0, rows: [], invoice_count: 0 });
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try { setData(await api.get("/finances/income-by-category")); }
    catch { setData({ total: 0, rows: [], invoice_count: 0 }); }
    finally { setLoading(false); setRefreshing(false); }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const doExport = () => {
    const header = toCsvRow(["Category", "Collected", "% of total"]);
    const body = data.rows.map((r) => toCsvRow([r.category, r.amount, data.total ? `${Math.round((r.amount / data.total) * 100)}%` : "0%"]));
    exportCsv(`income_by_category_${new Date().toISOString().slice(0, 10)}.csv`, [header, ...body].join("\n"));
  };

  if (loading) return <Loading testID="income-report-loading" />;

  return (
    <View style={styles.root}>
      <Header title="Income by Category" back subtitle="Collected revenue by service type" right={<IconButton icon="download-outline" onPress={doExport} testID="income-export" />} />
      <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}>
        <View style={styles.totalCard}>
          <Text style={styles.totalVal}>{money(data.total)}</Text>
          <Text style={styles.totalLabel}>collected across {data.invoice_count} invoice{data.invoice_count === 1 ? "" : "s"}</Text>
        </View>
        {data.rows.length === 0 ? (
          <EmptyState icon="pie-chart-outline" title="No income yet" subtitle="Category totals appear as invoices get paid." testID="income-report-empty" />
        ) : (
          data.rows.map((r, i) => {
            const pct = data.total ? (r.amount / data.total) * 100 : 0;
            const color = BAR_COLORS[i % BAR_COLORS.length];
            return (
              <View key={r.category_id || r.category} style={styles.row} testID={`income-cat-${r.category_id || r.category}`}>
                <View style={styles.rowHead}>
                  <Text style={styles.rowCat} numberOfLines={1} ellipsizeMode="tail">{r.label || r.category}</Text>
                  <Text style={styles.rowAmt} numberOfLines={1}>{money(r.amount)}</Text>
                </View>
                <View style={styles.track}>
                  <View style={[styles.fill, { width: `${Math.max(3, pct)}%`, backgroundColor: color }]} />
                </View>
                <Text style={styles.rowPct}>{Math.round(pct)}% of total</Text>
              </View>
            );
          })
        )}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  totalCard: { backgroundColor: colors.surface, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, padding: spacing.lg, alignItems: "center", marginBottom: spacing.lg },
  totalVal: { fontFamily: font.bold, fontSize: fontSize["3xl"], color: colors.brand },
  totalLabel: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
  row: { backgroundColor: colors.surface, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, padding: spacing.md, marginBottom: spacing.sm },
  rowHead: { flexDirection: "row", justifyContent: "space-between", marginBottom: spacing.sm },
  rowCat: { flex: 1, fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface, marginRight: spacing.sm },
  rowAmt: { flexShrink: 0, fontFamily: font.bold, fontSize: fontSize.base, color: colors.onSurface },
  track: { height: 10, borderRadius: 5, backgroundColor: colors.surfaceSecondary, overflow: "hidden" },
  fill: { height: 10, borderRadius: 5 },
  rowPct: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 4 },
});
