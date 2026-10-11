/**
 * Phase 39A · Income by Service Category donut — web parity
 * ``IncomeByServiceCategoryTile.jsx``. GET /admin/dashboard/
 * income-by-service-category?start&end; shares the parent's range (no
 * second filter). Same copy, states and testIDs as web.
 */
import React from "react";
import { View, Text, ActivityIndicator } from "react-native";
import { colors } from "@/src/theme";
import DonutChart, { useRangedFetch } from "@/src/components/dashboard/DonutChart";
import { tile } from "@/src/components/dashboard/RevenueByCategoryTile";

export default function IncomeByServiceCategoryTile({ range }: { range?: { start: string; end: string } | null }) {
  const { data, err } = useRangedFetch("/admin/dashboard/income-by-service-category", range);
  const items = (data?.items || []).map((it: any, i: number) => ({
    key: String(it.category || i), label: String(it.category || "Uncategorized"),
    amount: Number(it.amount || 0), color: it.color || colors.brand, count: it.count,
  }));
  return (
    <View style={tile.card} testID="income-by-service-category-tile">
      <View style={tile.head}>
        <Text style={tile.title}>Income by Service Category (paid, this month)</Text>
        {data ? (
          <Text style={tile.count} testID="income-svc-item-count">{`${items.length} unit${items.length === 1 ? "" : "s"}`}</Text>
        ) : null}
      </View>
      {err ? (
        <Text style={tile.error} testID="income-svc-error">{err}</Text>
      ) : data === null ? (
        <View style={tile.loading} testID="income-svc-loading"><ActivityIndicator color={colors.brand} /></View>
      ) : items.length === 0 ? (
        <Text style={tile.empty} testID="income-svc-empty">No invoiced revenue in this range yet.</Text>
      ) : (
        <DonutChart items={items} total={Number(data.total || 0)} prefix="income-svc" />
      )}
    </View>
  );
}
