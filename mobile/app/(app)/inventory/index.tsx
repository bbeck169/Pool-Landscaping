/** Phase 23 · Mobile — Inventory (read-only list for techs/admin). */
import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import AppTextInput from "@/src/components/ui/AppTextInput";

function tint(current: number, reorder: number): string {
  if (current <= 0) return "#DC2626";
  if (current <= reorder) return "#EA580C";
  if (current <= reorder * 1.5) return "#F59E0B";
  return "#059669";
}

function stockLabel(current: number, reorder: number): string {
  if (current <= 0) return "OUT";
  if (current <= reorder) return "LOW";
  return "OK";
}

export default function InventoryMobile() {
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState("");
  const [lowOnly, setLowOnly] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (q) params.set("q", q);
      if (lowOnly) params.set("low_stock", "true");
      const r = await api.get(`/inventory/items?${params.toString()}`);
      setItems(r.items || []);
    } catch {
      /* ignore */
    } finally { setLoading(false); }
  }, [q, lowOnly]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const lowCount = items.filter(
    (i) => Number(i.current_qty) <= Number(i.reorder_point),
  ).length;

  return (
    <View style={styles.root}>
      <Header title="Inventory" />
      <ScrollView contentContainerStyle={{ padding: spacing.lg,
                                             paddingBottom: spacing["3xl"] }}>
        <View style={styles.searchRow}>
          <AppTextInput
            value={q} onChangeText={setQ}
            placeholder="Search by name…"
            placeholderTextColor={colors.muted}
            style={styles.search}
            testID="inv-mobile-search" />
          <Pressable onPress={() => { setLowOnly(!lowOnly); }}
                     style={[styles.filterChip,
                              lowOnly ? styles.filterChipActive : null]}
                     testID="inv-mobile-lowfilter">
            <Ionicons name={lowOnly ? "warning" : "warning-outline"}
                       size={14}
                       color={lowOnly ? "#fff" : colors.brand} />
            <Text style={[styles.filterText,
                            lowOnly ? { color: "#fff" } : null]}>
              Low only
            </Text>
          </Pressable>
          <Pressable onPress={load} style={styles.filterChip}
                     testID="inv-mobile-refresh">
            <Ionicons name="refresh-outline" size={14} color={colors.brand} />
          </Pressable>
        </View>

        <View style={styles.summary}>
          <View style={styles.summaryPill}>
            <Text style={styles.summaryLabel}>Total</Text>
            <Text style={styles.summaryValue}>{items.length}</Text>
          </View>
          <View style={[styles.summaryPill,
                          { borderColor: "#EA580C" }]}>
            <Text style={styles.summaryLabel}>Low</Text>
            <Text style={[styles.summaryValue, { color: "#EA580C" }]}>
              {lowCount}
            </Text>
          </View>
        </View>

        {loading ? (
          <ActivityIndicator style={{ marginTop: spacing.xl }}
                              color={colors.brand} />
        ) : items.length === 0 ? (
          <View style={styles.empty}>
            <Ionicons name="cube-outline" size={36} color={colors.muted} />
            <Text style={styles.emptyText}>No items match.</Text>
          </View>
        ) : (
          items.map((it: any) => {
            const c = Number(it.current_qty || 0);
            const r = Number(it.reorder_point || 0);
            const color = tint(c, r);
            return (
              <View key={it.id} style={styles.card}
                     testID={`inv-mobile-row-${it.id}`}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.cardName}>{it.name}</Text>
                  <Text style={styles.cardMeta}>
                    {it.category} · {it.unit}
                    {it.supplier ? ` · ${it.supplier}` : ""}
                  </Text>
                </View>
                <View style={{ alignItems: "flex-end" }}>
                  <View style={[styles.pill,
                                  { backgroundColor: `${color}15` }]}>
                    <Text style={[styles.pillText, { color }]}>
                      {stockLabel(c, r)}
                    </Text>
                  </View>
                  <Text style={[styles.qty, { color }]}>
                    {c.toFixed(1)} {it.unit}
                  </Text>
                  <Text style={styles.reorder}>
                    reorder @ {r.toFixed(1)}
                  </Text>
                </View>
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
  searchRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    marginBottom: spacing.md,
  },
  search: {
    flex: 1,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    padding: spacing.md,
    color: colors.onSurface,
    fontFamily: font.regular,
    fontSize: fontSize.base,
  },
  filterChip: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.xs,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  filterChipActive: {
    backgroundColor: colors.brand,
    borderColor: colors.brand,
  },
  filterText: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.brand,
  },
  summary: {
    flexDirection: "row",
    gap: spacing.sm,
    marginBottom: spacing.md,
  },
  summaryPill: {
    flex: 1,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
    alignItems: "center",
  },
  summaryLabel: {
    fontFamily: font.regular,
    fontSize: fontSize.xs,
    color: colors.muted,
    textTransform: "uppercase",
  },
  summaryValue: {
    fontFamily: font.bold,
    fontSize: fontSize.xl,
    color: colors.onSurface,
    marginTop: 2,
  },
  card: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    padding: spacing.md,
    marginBottom: spacing.sm,
  },
  cardName: {
    fontFamily: font.bold,
    fontSize: fontSize.base,
    color: colors.onSurface,
  },
  cardMeta: {
    fontFamily: font.regular,
    fontSize: fontSize.xs,
    color: colors.muted,
    marginTop: 2,
  },
  pill: {
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: radius.pill,
    marginBottom: 4,
  },
  pillText: {
    fontFamily: font.bold,
    fontSize: 10,
  },
  qty: {
    fontFamily: font.bold,
    fontSize: fontSize.base,
  },
  reorder: {
    fontFamily: font.regular,
    fontSize: fontSize.xs,
    color: colors.muted,
    marginTop: 2,
  },
  empty: {
    marginTop: spacing.xl,
    alignItems: "center",
    padding: spacing.xl,
  },
  emptyText: {
    fontFamily: font.regular,
    fontSize: fontSize.base,
    color: colors.muted,
    marginTop: spacing.sm,
  },
});
