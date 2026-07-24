import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, FlatList, RefreshControl, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize, money } from "@/src/theme";
import { Loading, EmptyState, StatusChip } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";

export default function PortalInvoices() {
  const router = useRouter();
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      setItems(await api.get(`/quotes?doc_type=invoice`));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  return (
    <View style={styles.root}>
      <Header title="Invoices" subtitle="View & pay your invoices" back />
      {loading ? (
        <Loading testID="portal-invoices-loading" />
      ) : items.length === 0 ? (
        <EmptyState icon="receipt-outline" title="No invoices yet" subtitle="Your invoices will appear here." testID="portal-invoices-empty" />
      ) : (
        <FlatList
          testID="portal-invoices-list"
          data={items}
          keyExtractor={(i) => i.id}
          contentContainerStyle={{ padding: spacing.lg, paddingTop: spacing.sm, paddingBottom: spacing["3xl"] }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
          renderItem={({ item }) => (
            <Pressable style={styles.card} onPress={() => router.push(`/invoice/${item.id}`)} testID={`portal-invoice-${item.id}`}>
              <View style={styles.topRow}>
                <View style={styles.typeBadge}>
                  <Ionicons name="receipt-outline" size={16} color={colors.brand} />
                  <Text style={styles.typeText}>Invoice</Text>
                </View>
                <StatusChip status={item.payment_status === "paid" ? "paid" : "unpaid"} />
              </View>
              <Text style={styles.title} numberOfLines={1}>{item.title}</Text>
              <View style={styles.footer}>
                <Text style={styles.total}>{money(item.total)}</Text>
                <Ionicons name="chevron-forward" size={18} color={colors.muted} />
              </View>
            </Pressable>
          )}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  card: { backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.lg, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.md, gap: 4 },
  topRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 4 },
  typeBadge: { flexDirection: "row", alignItems: "center", gap: 5 },
  typeText: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.brand },
  title: { fontFamily: font.semibold, fontSize: fontSize.lg, color: colors.onSurface },
  footer: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginTop: spacing.sm },
  total: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface },
});
