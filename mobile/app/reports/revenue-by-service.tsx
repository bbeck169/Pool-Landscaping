import React, { useCallback, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, RefreshControl, Pressable,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize, money } from "@/src/theme";
import { Loading, EmptyState } from "@/src/components/ui";
import { Header, IconButton } from "@/src/components/widgets";
import { exportCsv, toCsvRow } from "@/src/utils/exportCsv";

/**
 * Phase (Feb-2026) · mobile Revenue by Service — dedicated screen.
 *
 * Mirrors the web ``revenue-by-service-card`` inside
 * ``frontend/src/pages/reports/BusinessSummary.jsx`` (line 134). Data
 * source is the shared ``GET /api/reports`` payload — the same one
 * ``reports.tsx`` already fetches. Extracted from the inline card in
 * ``mobile/app/reports.tsx`` so the parity tile at the top of
 * Reports can tap into a full-page view (sortable rows + CSV export)
 * without duplicating the visualisation.
 */
type Row = { label: string; value: number };

export default function RevenueByServiceScreen() {
  const [rows, setRows] = useState<Row[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [sort, setSort] = useState<"value_desc" | "value_asc" | "label">("value_desc");

  const load = useCallback(async () => {
    try {
      const r = await api.get("/reports");
      setRows((r?.revenue_by_service || []) as Row[]);
    } catch {
      setRows([]);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const sorted = useMemo(() => {
    const clone = [...rows];
    if (sort === "value_desc") clone.sort((a, b) => b.value - a.value);
    else if (sort === "value_asc") clone.sort((a, b) => a.value - b.value);
    else clone.sort((a, b) => a.label.localeCompare(b.label));
    return clone;
  }, [rows, sort]);

  const total = useMemo(() => rows.reduce((a, r) => a + Number(r.value || 0), 0), [rows]);
  const max = useMemo(() => Math.max(...rows.map((r) => r.value), 1), [rows]);

  const doExport = () => {
    const header = toCsvRow(["Service", "Revenue", "% of total"]);
    const body = sorted.map((r) =>
      toCsvRow([r.label, r.value, total ? `${Math.round((r.value / total) * 100)}%` : "0%"]),
    );
    exportCsv(
      `revenue_by_service_${new Date().toISOString().slice(0, 10)}.csv`,
      [header, ...body].join("\n"),
    );
  };

  if (loading) return <Loading testID="revenue-by-service-loading" />;

  return (
    <View style={s.root} testID="revenue-by-service-page">
      <Header
        title="Revenue by Service"
        back
        subtitle="Collected revenue by service type"
        right={<IconButton icon="download-outline" onPress={doExport} testID="rbs-export" />}
      />
      <ScrollView
        contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
      >
        <View style={s.totalCard}>
          <Text style={s.totalVal}>{money(total)}</Text>
          <Text style={s.totalLabel}>collected across {rows.length} service{rows.length === 1 ? "" : "s"}</Text>
        </View>

        <View style={s.sortRow} testID="rbs-sort-row">
          {(["value_desc", "value_asc", "label"] as const).map((k) => (
            <Pressable
              key={k}
              testID={`rbs-sort-${k}`}
              onPress={() => setSort(k)}
              style={[s.sortChip, sort === k && s.sortChipActive]}
            >
              <Text style={[s.sortChipText, sort === k && { color: "#fff" }]}>
                {k === "value_desc" ? "High → Low" : k === "value_asc" ? "Low → High" : "A → Z"}
              </Text>
            </Pressable>
          ))}
        </View>

        {sorted.length === 0 ? (
          <EmptyState
            icon="bar-chart-outline"
            title="No revenue yet"
            subtitle="Service breakdown appears as invoices get paid."
            testID="revenue-by-service-empty"
          />
        ) : (
          <View style={s.card} testID="revenue-by-service-list">
            {sorted.map((r) => (
              <View key={r.label} style={s.row}>
                <Text style={s.rowLabel} numberOfLines={1}>{r.label}</Text>
                <View style={s.barTrack}>
                  <View style={[s.bar, { width: `${Math.max(4, (r.value / max) * 100)}%` }]} />
                </View>
                <Text style={s.rowValue}>{money(r.value)}</Text>
              </View>
            ))}
          </View>
        )}
      </ScrollView>
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  totalCard: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.lg,
    marginBottom: spacing.md,
    alignItems: "center",
  },
  totalVal: { fontFamily: font.bold, fontSize: fontSize["2xl"], color: colors.onSurface },
  totalLabel: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 4 },
  sortRow: { flexDirection: "row", gap: spacing.xs, marginBottom: spacing.md },
  sortChip: {
    paddingHorizontal: 12, paddingVertical: 6, borderRadius: radius.md,
    backgroundColor: colors.surfaceTertiary,
  },
  sortChipActive: { backgroundColor: colors.brand },
  sortChipText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
    gap: spacing.sm,
  },
  row: { flexDirection: "row", alignItems: "center", gap: 8 },
  rowLabel: { flex: 1, fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  barTrack: {
    flex: 1.4, height: 6, borderRadius: 999, backgroundColor: colors.surfaceTertiary, overflow: "hidden",
  },
  bar: { height: 6, borderRadius: 999, backgroundColor: colors.brand },
  rowValue: { minWidth: 78, textAlign: "right", fontFamily: font.bold, fontSize: fontSize.sm, color: colors.onSurface },
});
