// Phase 35 · Feb-2026 — Mobile Master Invoices list (P1.1 Finance Parity).
//
// Web parity: `frontend/src/pages/invoices/MasterInvoice.jsx` (MasterInvoicesList).
// Backend: GET /api/invoices/master.
// Admin / super-admin / manager only.
import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, RefreshControl,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { router, useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize, money } from "@/src/theme";
import { Loading, EmptyState } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";
import { RoleGate } from "@/src/components/RoleGate";

type Master = {
  id: string;
  number?: string;
  customer_name?: string;
  customer_id?: string;
  total_cents?: number;
  applied_payments_cents?: number;
  balance_cents?: number;
  child_count?: number;
  created_at?: string;
  status?: string;
};

export default function MasterInvoicesList() {
  const [rows, setRows] = useState<Master[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r: any = await api.get("/invoices/master");
      setRows(Array.isArray(r) ? r : r?.items || []);
    } catch {
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  return (
    <RoleGate level="strict_admin">
      <View style={styles.container} testID="master-invoices-page">
        <Header title="Master Invoices" />
        <ScrollView
          contentContainerStyle={styles.body}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={async () => {
              setRefreshing(true); await load(); setRefreshing(false);
            }} />
          }
        >
          <Text style={styles.hint} testID="master-invoices-hint">
            Parent invoices that roll up multiple child invoices for a single customer.
          </Text>
          {loading ? (
            <Loading />
          ) : rows.length === 0 ? (
            <EmptyState
              icon="albums-outline"
              title="No master invoices yet"
              subtitle="Create them on the desktop invoices page."
              testID="master-invoices-empty"
            />
          ) : (
            rows.map((r) => (
              <Pressable
                key={r.id}
                onPress={() => router.push({
                  pathname: "/finance/master-invoices/[id]",
                  params: { id: r.id },
                })}
                testID={`master-invoice-row-${r.id}`}
                style={({ pressed }) => [styles.row, pressed && { opacity: 0.8 }]}
              >
                <View style={styles.rowHead}>
                  <Text style={styles.num}>{r.number || r.id.slice(0, 8)}</Text>
                  <Ionicons name="chevron-forward" size={18} color={colors.muted} />
                </View>
                <Text style={styles.customer} numberOfLines={1}>
                  {r.customer_name || r.customer_id || "—"}
                </Text>
                <View style={styles.metaRow}>
                  <Text style={styles.meta}>{r.child_count ?? 0} children</Text>
                  <Text style={styles.total}>
                    {money((r.total_cents || 0) / 100)}
                  </Text>
                </View>
                {typeof r.balance_cents === "number" && r.balance_cents > 0 && (
                  <Text style={styles.balance}>
                    Balance {money(r.balance_cents / 100)}
                  </Text>
                )}
              </Pressable>
            ))
          )}
        </ScrollView>
      </View>
    </RoleGate>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.surface },
  body: { padding: spacing.lg, gap: spacing.md, paddingBottom: spacing["3xl"] },
  hint: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  row: {
    padding: spacing.md, borderRadius: radius.md, borderWidth: 1,
    borderColor: colors.border, backgroundColor: colors.surface, gap: spacing.xs,
  },
  rowHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  num: { fontFamily: font.bold, fontSize: fontSize.md, color: colors.onSurface },
  customer: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
  metaRow: { flexDirection: "row", justifyContent: "space-between", marginTop: spacing.xs },
  meta: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  total: { fontFamily: font.bold, fontSize: fontSize.md, color: colors.onSurface },
  balance: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.brand, marginTop: 2 },
});
