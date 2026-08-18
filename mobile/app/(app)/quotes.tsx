import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, FlatList, RefreshControl, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { colors, spacing, radius, font, fontSize, money } from "@/src/theme";
import { Loading, EmptyState, StatusChip } from "@/src/components/ui";
import { Header, FilterRow, IconButton, NotificationBell } from "@/src/components/widgets";

const FILTERS = [
  { key: "all", label: "All" },
  { key: "quote", label: "Quotes" },
  { key: "invoice", label: "Invoices" },
];

export default function Quotes() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin" || user?.role === "super_admin";
  const router = useRouter();
  const [items, setItems] = useState<any[]>([]);
  const [filter, setFilter] = useState("all");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async (f: string) => {
    try {
      const q = f === "all" ? "" : `?doc_type=${f}`;
      setItems(await api.get(`/quotes${q}`));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      load(filter);
    }, [filter, load])
  );

  return (
    <View style={styles.root}>
      <Header
        title={isAdmin ? "Quotes & Invoices" : "My Invoices"}
        right={
          isAdmin ? (
            <IconButton icon="add" onPress={() => router.push("/quote/new")} testID="add-quote-button" />
          ) : (
            <NotificationBell />
          )
        }
      />
      <FilterRow options={FILTERS} value={filter} onChange={setFilter} testID="quotes-filter" />
      {loading ? (
        <Loading testID="quotes-loading" />
      ) : items.length === 0 ? (
        <EmptyState icon="document-text-outline" title={isAdmin ? "No documents yet" : "No invoices yet"} subtitle={isAdmin ? "Create a quote or invoice to get started." : "Your invoices will appear here."} testID="quotes-empty" />
      ) : (
        <FlatList
          testID="quotes-list"
          data={items}
          keyExtractor={(i) => i.id}
          contentContainerStyle={{ padding: spacing.lg, paddingTop: spacing.sm, paddingBottom: spacing["3xl"] }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(filter); }} />}
          renderItem={({ item }) => (
            <Pressable style={styles.card} onPress={() => router.push(`/quote/${item.id}`)} testID={`quote-card-${item.id}`}>
              <View style={styles.topRow}>
                <View style={styles.typeBadge}>
                  <Ionicons name={item.doc_type === "invoice" ? "receipt-outline" : "document-text-outline"} size={16} color={colors.brand} />
                  <Text style={styles.typeText}>{item.doc_type === "invoice" ? "Invoice" : "Quote"}</Text>
                </View>
                <StatusChip status={item.payment_status === "paid" ? "paid" : item.status} />
              </View>
              <Text style={styles.title} numberOfLines={1}>{item.title}</Text>
              <Text style={styles.customer}>{item.customer_name}</Text>
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
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.lg,
    borderWidth: 1,
    borderColor: colors.border,
    marginBottom: spacing.md,
    gap: 4,
  },
  topRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 4 },
  typeBadge: { flexDirection: "row", alignItems: "center", gap: 5 },
  typeText: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.brand },
  title: { fontFamily: font.semibold, fontSize: fontSize.lg, color: colors.onSurface },
  customer: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted },
  footer: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginTop: spacing.sm },
  total: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface },
});
