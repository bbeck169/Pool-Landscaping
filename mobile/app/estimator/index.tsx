import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, FlatList, RefreshControl, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize, money } from "@/src/theme";
import { Loading, EmptyState } from "@/src/components/ui";
import { Header, IconButton } from "@/src/components/widgets";

export default function EstimatorList() {
  const router = useRouter();
  const [estimates, setEstimates] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      setEstimates(await api.get("/estimates"));
    } catch {
      setEstimates([]);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  return (
    <View style={styles.root}>
      <Header
        title="Estimator"
        back
        subtitle="Cost-based, profit-aware quotes"
        right={<IconButton icon="add" onPress={() => router.push("/estimator/new")} testID="estimator-new" />}
      />

      <View style={styles.quickRow}>
        <Pressable style={styles.quickBtn} onPress={() => router.push("/estimator/templates")} testID="estimator-templates-link">
          <Ionicons name="albums-outline" size={16} color={colors.brand} />
          <Text style={styles.quickText}>Templates</Text>
        </Pressable>
        <Pressable style={styles.quickBtn} onPress={() => router.push("/estimator/settings")} testID="estimator-settings-link">
          <Ionicons name="options-outline" size={16} color={colors.brand} />
          <Text style={styles.quickText}>Defaults</Text>
        </Pressable>
      </View>

      {loading ? (
        <Loading testID="estimates-loading" />
      ) : estimates.length === 0 ? (
        <EmptyState icon="calculator-outline" title="No estimates yet" subtitle="Tap + to build your first profit-aware estimate." testID="estimates-empty" />
      ) : (
        <FlatList
          testID="estimates-list"
          data={estimates}
          keyExtractor={(e) => e.id}
          contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
          renderItem={({ item }) => {
            const converted = item.status === "converted";
            return (
              <Pressable style={styles.card} onPress={() => router.push(`/estimator/${item.id}`)} testID={`estimate-${item.id}`}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.cardTitle} numberOfLines={1}>{item.title}</Text>
                  <Text style={styles.cardMeta} numberOfLines={1}>{item.customer_name} · GM {item.gross_margin_pct}%</Text>
                </View>
                <View style={{ alignItems: "flex-end", gap: 4 }}>
                  <Text style={styles.price}>{money(item.sell_price)}</Text>
                  <View style={[styles.badge, { backgroundColor: (converted ? "#16A34A" : "#64748B") + "1A", borderColor: converted ? "#16A34A" : "#64748B" }]}>
                    <Text style={[styles.badgeText, { color: converted ? "#16A34A" : "#64748B" }]}>{converted ? "CONVERTED" : "DRAFT"}</Text>
                  </View>
                </View>
              </Pressable>
            );
          }}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  quickRow: { flexDirection: "row", gap: spacing.sm, paddingHorizontal: spacing.lg, paddingTop: spacing.md },
  quickBtn: { flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, paddingHorizontal: spacing.md, height: 40 },
  quickText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.brand },
  card: { flexDirection: "row", alignItems: "center", gap: spacing.md, backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.sm },
  cardTitle: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  cardMeta: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
  price: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  badge: { paddingHorizontal: spacing.sm, height: 22, borderRadius: radius.pill, borderWidth: 1, alignItems: "center", justifyContent: "center" },
  badgeText: { fontFamily: font.bold, fontSize: 10, letterSpacing: 0.3 },
});
