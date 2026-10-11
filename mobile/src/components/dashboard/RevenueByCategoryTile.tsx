/**
 * Phase 39A · Revenue by Category donut — web parity
 * ``RevenueByCategoryTile.jsx``. GET /admin/dashboard/revenue-by-category
 * ?start&end, refetched when the shared range changes. Same copy, states
 * and testIDs as web; ``displayCategoryLabel`` keeps web's "never render a
 * UUID as a label" contract. (Web's legend drill-down modal has no mobile
 * port yet — legend tap highlights the segment instead.)
 */
import React from "react";
import { View, Text, StyleSheet, ActivityIndicator } from "react-native";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import DonutChart, { useRangedFetch } from "@/src/components/dashboard/DonutChart";

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function displayCategoryLabel(item: any): string {
  const raw = String(item?.category_name || item?.category || "").trim();
  if (!raw || UUID_RE.test(raw)) return "Uncategorized";
  return raw;
}

export default function RevenueByCategoryTile({ range }: { range?: { start: string; end: string } | null }) {
  const { data, err } = useRangedFetch("/admin/dashboard/revenue-by-category", range);
  const items = (data?.items || []).map((it: any, i: number) => {
    const label = displayCategoryLabel(it);
    return { key: String(it.category_id || it.category || label || i), label, amount: Number(it.amount || 0), color: it.color || colors.brand, count: it.count };
  });
  return (
    <View style={tile.card} testID="revenue-by-category-tile">
      <View style={tile.head}>
        <Text style={tile.title}>Revenue by Category (paid, this month)</Text>
        {data ? (
          <Text style={tile.count} testID="revenue-cat-item-count">
            {`${items.length} categor${items.length === 1 ? "y" : "ies"}`}
          </Text>
        ) : null}
      </View>
      {err ? (
        <Text style={tile.error} testID="revenue-cat-error">{err}</Text>
      ) : data === null ? (
        <View style={tile.loading} testID="revenue-cat-loading"><ActivityIndicator color={colors.brand} /></View>
      ) : items.length === 0 ? (
        <Text style={tile.empty} testID="revenue-cat-empty">No invoiced revenue in this range yet.</Text>
      ) : (
        <DonutChart items={items} total={Number(data.total || 0)} prefix="revenue-cat" />
      )}
    </View>
  );
}

export const tile = StyleSheet.create({
  card: {
    backgroundColor: colors.surface, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.border,
    padding: spacing.md, marginBottom: spacing.md,
  },
  head: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: spacing.sm, marginBottom: spacing.sm },
  title: { flex: 1, fontFamily: font.bold, fontSize: 10, color: colors.muted, textTransform: "uppercase", letterSpacing: 1 },
  count: { fontFamily: font.regular, fontSize: fontSize.xs, color: colors.muted },
  error: { padding: spacing.sm, borderRadius: radius.md, backgroundColor: "#FEE2E2", color: "#7F1D1D", fontFamily: font.medium, fontSize: fontSize.sm },
  loading: { height: 170, alignItems: "center", justifyContent: "center", borderRadius: radius.md, backgroundColor: colors.surfaceSecondary },
  empty: { paddingVertical: spacing.xl, textAlign: "center", fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
});
