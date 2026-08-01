/**
 * Phase 18 · Feb-2026 — Mobile · Tech "My Inventory".
 *
 * Read-only per-tech on-hand list. Hits ``GET /api/inventory/my-inventory``
 * which strips wholesale cost data on the backend. Never surfaces cost
 * fields to a tech user (per user's locked visibility decision).
 *
 * Also shows a "You used" panel of the tech's last-30-day chemical
 * usage, quantities only — no dollar figures.
 */
import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, ActivityIndicator, RefreshControl,
} from "react-native";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";

function badgeStyle(item: any) {
  if (item.out_of_stock) return { bg: "#FEE2E2", fg: "#B91C1C", label: "OUT" };
  if (item.low_stock) return { bg: "#FFEDD5", fg: "#C2410C", label: "LOW" };
  return { bg: "#DCFCE7", fg: "#166534", label: "OK" };
}

export default function MyInventoryMobile() {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [err, setErr] = useState<string>("");

  const load = useCallback(async () => {
    setErr("");
    try {
      const r = await api.get("/inventory/my-inventory");
      setData(r);
    } catch (e: any) {
      setErr(e?.message || "Failed to load");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  if (loading && !data) {
    return (
      <View style={styles.root}>
        <Header title="My Inventory" />
        <ActivityIndicator size="large" style={{ marginTop: spacing["3xl"] }} />
      </View>
    );
  }

  const items = data?.items || [];
  const usage = data?.my_recent_usage || [];

  return (
    <View style={styles.root}>
      <Header title="My Inventory" />
      <ScrollView
        testID="my-inventory-scroll"
        contentContainerStyle={{ padding: spacing.lg,
                                 paddingBottom: spacing["3xl"] }}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={() => { setRefreshing(true); load(); }}
          />
        }
      >
        {err ? (
          <View style={styles.errorBox} testID="my-inventory-error">
            <Text style={styles.errorText}>{err}</Text>
          </View>
        ) : null}

        {/* Summary strip */}
        <View style={styles.summaryRow}>
          <View style={[styles.summaryCard, { backgroundColor: "#F1F5F9" }]}
                testID="summary-total">
            <Text style={styles.summaryLabel}>Total SKUs</Text>
            <Text style={styles.summaryValue}>{data?.total_items ?? 0}</Text>
          </View>
          <View style={[styles.summaryCard, { backgroundColor: "#FFEDD5" }]}
                testID="summary-low">
            <Text style={styles.summaryLabel}>Low</Text>
            <Text style={styles.summaryValue}>
              {data?.low_stock_count ?? 0}
            </Text>
          </View>
          <View style={[styles.summaryCard, { backgroundColor: "#FEE2E2" }]}
                testID="summary-out">
            <Text style={styles.summaryLabel}>Out</Text>
            <Text style={styles.summaryValue}>
              {data?.out_of_stock_count ?? 0}
            </Text>
          </View>
        </View>

        {/* On-hand list — sorted OUT first, then LOW, then OK */}
        <Text style={styles.sectionH}>On-hand</Text>
        {items.map((it: any) => {
          const b = badgeStyle(it);
          return (
            <View style={styles.itemCard} key={it.id}
                  testID={`inv-item-${it.sku || it.id}`}>
              <View style={{ flex: 1 }}>
                <Text style={styles.itemName}>{it.name}</Text>
                <Text style={styles.itemMeta}>
                  {it.current_qty} {it.unit}
                  {it.reorder_point !== null && it.reorder_point !== undefined
                    ? ` · reorder at ${it.reorder_point}`
                    : ""}
                  {it.department ? ` · ${it.department}` : ""}
                </Text>
              </View>
              <View style={[styles.badge,
                { backgroundColor: b.bg }]}>
                <Text style={[styles.badgeTxt, { color: b.fg }]}>
                  {b.label}
                </Text>
              </View>
            </View>
          );
        })}

        {/* Personal usage panel — quantities only, NO cost */}
        <Text style={[styles.sectionH, { marginTop: spacing.xl }]}>
          You used (last 30 days)
        </Text>
        {usage.length === 0 ? (
          <Text style={styles.emptyText}>
            No chemicals recorded on your service reports yet.
          </Text>
        ) : (
          usage.map((u: any) => (
            <View style={styles.usageRow} key={u.product_slug}
                  testID={`usage-row-${u.product_slug}`}>
              <Text style={styles.usageName}>{u.name}</Text>
              <Text style={styles.usageQty}>
                {Number(u.quantity_used).toFixed(2)} {u.unit || ""}
                {"  ·  "}
                {u.event_count} visit{u.event_count !== 1 ? "s" : ""}
              </Text>
            </View>
          ))
        )}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  summaryRow: { flexDirection: "row", gap: spacing.sm,
                 marginBottom: spacing.lg },
  summaryCard: { flex: 1, padding: spacing.md, borderRadius: radius.md },
  summaryLabel: { color: "#475569", fontSize: fontSize.xs,
                   fontFamily: font.regular },
  summaryValue: { color: "#0F172A", fontSize: fontSize.xl,
                   fontFamily: font.bold, marginTop: 4 },
  sectionH: { fontSize: fontSize.md, fontFamily: font.bold,
              color: colors.onSurface, marginTop: spacing.md,
              marginBottom: spacing.sm },
  itemCard: { flexDirection: "row", alignItems: "center",
              gap: spacing.md, padding: spacing.md,
              backgroundColor: colors.surface, borderRadius: radius.md,
              marginBottom: spacing.xs,
              borderWidth: 1, borderColor: colors.border },
  itemName: { fontSize: fontSize.md, fontFamily: font.bold,
              color: colors.onSurface },
  itemMeta: { fontSize: fontSize.sm, color: colors.muted,
              fontFamily: font.regular, marginTop: 2 },
  badge: { paddingHorizontal: spacing.sm, paddingVertical: 4,
           borderRadius: radius.pill },
  badgeTxt: { fontSize: fontSize.xs, fontFamily: font.bold },
  usageRow: { flexDirection: "row", justifyContent: "space-between",
               padding: spacing.md, backgroundColor: colors.surface,
               borderRadius: radius.md, marginBottom: spacing.xs,
               borderWidth: 1, borderColor: colors.border },
  usageName: { fontSize: fontSize.sm, fontFamily: font.bold,
               color: colors.onSurface },
  usageQty: { fontSize: fontSize.sm, color: colors.muted,
              fontFamily: font.regular },
  emptyText: { color: colors.muted, fontFamily: font.regular,
               fontSize: fontSize.sm, marginBottom: spacing.md,
               fontStyle: "italic" },
  errorBox: { backgroundColor: "#FEE2E2", padding: spacing.md,
              borderRadius: radius.md, marginBottom: spacing.md },
  errorText: { color: "#B91C1C", fontFamily: font.regular,
                fontSize: fontSize.sm },
});
