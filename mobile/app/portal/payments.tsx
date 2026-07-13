import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, FlatList, RefreshControl } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize, money } from "@/src/theme";
import { Loading, EmptyState } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";

export default function PortalPayments() {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      setData(await api.get(`/me/payments`));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const payments = data?.payments || [];

  return (
    <View style={styles.root}>
      <Header title="Payments" subtitle="Your payment history" back />
      {loading ? (
        <Loading testID="portal-payments-loading" />
      ) : (
        <FlatList
          testID="portal-payments-list"
          data={payments}
          keyExtractor={(i: any) => i.id}
          contentContainerStyle={{ padding: spacing.lg, paddingTop: spacing.md, paddingBottom: spacing["3xl"] }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
          ListHeaderComponent={
            <View style={styles.summary}>
              <Text style={styles.summaryLabel}>Total Paid</Text>
              <Text style={styles.summaryValue} testID="portal-total-paid">{money(data?.total_paid || 0)}</Text>
              <Text style={styles.summaryMeta}>{data?.count || 0} payment{data?.count === 1 ? "" : "s"}</Text>
            </View>
          }
          ListEmptyComponent={
            <EmptyState icon="card-outline" title="No payments yet" subtitle="Paid invoices will show up here." testID="portal-payments-empty" />
          }
          renderItem={({ item }) => (
            <View style={styles.row} testID={`portal-payment-${item.id}`}>
              <View style={styles.rowIcon}>
                <Ionicons name="checkmark-circle" size={20} color={colors.success} />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.rowTitle} numberOfLines={1}>{item.title}</Text>
                <Text style={styles.rowMeta}>{(item.paid_at || "").slice(0, 10)} · {item.method}</Text>
              </View>
              <Text style={styles.rowAmount}>{money(item.amount)}</Text>
            </View>
          )}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  summary: { backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.lg, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.md, alignItems: "center" },
  summaryLabel: { fontFamily: font.medium, fontSize: fontSize.base, color: colors.muted },
  summaryValue: { fontFamily: font.bold, fontSize: 34, color: colors.onSurface, marginTop: 2 },
  summaryMeta: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.md, backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.sm },
  rowIcon: { width: 40, height: 40, borderRadius: radius.md, backgroundColor: colors.success + "12", alignItems: "center", justifyContent: "center" },
  rowTitle: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  rowMeta: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 1 },
  rowAmount: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
});
