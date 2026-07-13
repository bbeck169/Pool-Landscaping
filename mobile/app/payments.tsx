import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, FlatList, RefreshControl } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize, money } from "@/src/theme";
import { Loading, EmptyState } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";

function fmtDate(iso?: string) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  } catch {
    return "—";
  }
}

export default function Payments() {
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      setItems(await api.get("/payments"));
    } catch {
      setItems([]);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const total = items.reduce((s, p) => s + (p.amount || 0), 0);

  return (
    <View style={styles.root}>
      <Header title="Payments" back subtitle="Collected payments" />
      {loading ? (
        <Loading testID="payments-loading" />
      ) : items.length === 0 ? (
        <EmptyState icon="card-outline" title="No payments yet" subtitle="Collected invoice payments appear here." testID="payments-empty" />
      ) : (
        <FlatList
          testID="payments-list"
          data={items}
          keyExtractor={(i) => i.id}
          ListHeaderComponent={
            <View style={styles.totalCard}>
              <Text style={styles.totalLabel}>Total Collected</Text>
              <Text style={styles.totalValue}>{money(total)}</Text>
            </View>
          }
          contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
          renderItem={({ item }) => (
            <View style={styles.row} testID={`payment-${item.id}`}>
              <View style={styles.icon}>
                <Ionicons name="checkmark-circle" size={20} color={colors.success} />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.name}>{item.customer_name}</Text>
                <Text style={styles.sub}>{item.title} · {fmtDate(item.paid_at)}</Text>
              </View>
              <Text style={styles.amount}>{money(item.amount)}</Text>
            </View>
          )}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  totalCard: { backgroundColor: colors.brand, borderRadius: radius.lg, padding: spacing.lg, marginBottom: spacing.md },
  totalLabel: { fontFamily: font.medium, fontSize: fontSize.base, color: "rgba(255,255,255,0.85)" },
  totalValue: { fontFamily: font.bold, fontSize: 30, color: "#fff", marginTop: 2 },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.md, backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.sm },
  icon: { width: 40, height: 40, borderRadius: radius.md, backgroundColor: "#DCFCE7", alignItems: "center", justifyContent: "center" },
  name: { fontFamily: font.semibold, fontSize: fontSize.lg, color: colors.onSurface },
  sub: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
  amount: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.success },
});
