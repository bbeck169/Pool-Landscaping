// Phase 35 · Feb-2026 — Mobile Master Invoice detail (P1.1 Finance Parity).
//
// Web parity: `frontend/src/pages/invoices/MasterInvoice.jsx` (MasterInvoiceDetail).
// Backend: GET /api/invoices/master/{id}, POST /api/invoices/master/{id}/apply-payment.
// Admin / super-admin only.
import React, { useCallback, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, RefreshControl } from "react-native";
import { useFocusEffect, useLocalSearchParams } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize, money } from "@/src/theme";
import { Card, Loading, EmptyState, PrimaryButton } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";
import { formatCustomerName } from "@/src/utils/formatCustomerName";
import { RoleGate } from "@/src/components/RoleGate";
import { showConfirm } from "@/src/components/ConfirmModal";
import AppTextInput from "@/src/components/ui/AppTextInput";

type Child = {
  id: string;
  number?: string;
  total_cents?: number;
  balance_cents?: number;
  status?: string;
};

type MasterDetail = {
  id: string;
  number?: string;
  customer_name?: string;
  customer_id?: string;
  total_cents?: number;
  applied_payments_cents?: number;
  balance_cents?: number;
  children?: Child[];
  created_at?: string;
};

export default function MasterInvoiceDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const [doc, setDoc] = useState<MasterDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [amount, setAmount] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    try {
      const r: any = await api.get(`/invoices/master/${id}`);
      setDoc(r);
    } catch {
      setDoc(null);
    } finally {
      setLoading(false);
    }
  }, [id]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const balance = useMemo(() => (doc?.balance_cents ?? 0) / 100, [doc]);
  const parsedAmount = Number(amount) || 0;

  const applyPayment = useCallback(() => {
    if (!doc || parsedAmount <= 0) return;
    showConfirm({
      title: `Apply ${money(parsedAmount)} to ${doc.number || doc.id}?`,
      description:
        "Cascades across the child invoices in order. This is not reversible from mobile.",
      confirmLabel: "Apply payment",
      testID: "master-apply-confirm",
      onConfirm: async () => {
        setBusy(true);
        try {
          await api.post(
            `/invoices/master/${doc.id}/apply-payment`,
            { amount: parsedAmount },
          );
          setAmount("");
          await load();
        } catch { /* ignore */ } finally {
          setBusy(false);
        }
      },
    });
  }, [doc, parsedAmount, load]);

  return (
    <RoleGate level="strict_admin">
      <View style={styles.container} testID="master-invoice-detail-page">
        <Header title={doc?.number || "Master Invoice"} />
        {loading ? (
          <Loading />
        ) : !doc ? (
          <EmptyState
            icon="alert-circle-outline"
            title="Not found"
            subtitle="This master invoice could not be loaded."
            testID="master-invoice-not-found"
          />
        ) : (
          <ScrollView
            contentContainerStyle={styles.body}
            refreshControl={
              <RefreshControl refreshing={refreshing} onRefresh={async () => {
                setRefreshing(true); await load(); setRefreshing(false);
              }} />
            }
          >
            <Card style={styles.summary}>
              <Text style={styles.summaryLabel}>{formatCustomerName(doc)}</Text>
              <View style={styles.summaryRow}>
                <View style={styles.summaryCell}>
                  <Text style={styles.summaryHead}>Total</Text>
                  <Text style={styles.summaryVal}>{money((doc.total_cents || 0) / 100)}</Text>
                </View>
                <View style={styles.summaryCell}>
                  <Text style={styles.summaryHead}>Applied</Text>
                  <Text style={styles.summaryVal}>{money((doc.applied_payments_cents || 0) / 100)}</Text>
                </View>
                <View style={styles.summaryCell}>
                  <Text style={styles.summaryHead}>Balance</Text>
                  <Text style={[styles.summaryVal, balance > 0 && { color: colors.brand }]}>
                    {money(balance)}
                  </Text>
                </View>
              </View>
            </Card>

            {balance > 0 && (
              <View style={styles.applyBox} testID="master-apply-box">
                <Text style={styles.applyLabel}>Apply payment</Text>
                <AppTextInput
                  value={amount}
                  onChangeText={setAmount}
                  placeholder="0.00"
                  keyboardType="decimal-pad"
                  style={styles.input}
                  testID="master-apply-amount"
                />
                <PrimaryButton
                  label={busy ? "Applying…" : "Apply"}
                  onPress={applyPayment}
                  disabled={busy || parsedAmount <= 0}
                  testID="master-apply-submit"
                />
              </View>
            )}

            <Text style={styles.section}>Child invoices ({(doc.children || []).length})</Text>
            {(doc.children || []).length === 0 ? (
              <Text style={styles.emptyChildren} testID="master-children-empty">
                No child invoices linked yet.
              </Text>
            ) : (
              (doc.children || []).map((c) => (
                <View key={c.id} style={styles.child} testID={`master-child-${c.id}`}>
                  <Text style={styles.childNum}>{c.number || c.id.slice(0, 8)}</Text>
                  <Text style={styles.childStatus}>{(c.status || "").toUpperCase()}</Text>
                  <Text style={styles.childAmount}>{money((c.total_cents || 0) / 100)}</Text>
                </View>
              ))
            )}
          </ScrollView>
        )}
      </View>
    </RoleGate>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.surface },
  body: { padding: spacing.lg, gap: spacing.md, paddingBottom: spacing["3xl"] },
  summary: { gap: spacing.sm },
  summaryLabel: { fontFamily: font.semibold, fontSize: fontSize.md, color: colors.onSurface },
  summaryRow: { flexDirection: "row", justifyContent: "space-between", marginTop: spacing.xs },
  summaryCell: { flex: 1 },
  summaryHead: { fontFamily: font.medium, fontSize: 10, textTransform: "uppercase", color: colors.muted, letterSpacing: 0.5 },
  summaryVal: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface, marginTop: 2 },
  applyBox: {
    padding: spacing.md, borderRadius: radius.md, borderWidth: 1,
    borderColor: colors.border, backgroundColor: colors.surface, gap: spacing.sm,
  },
  applyLabel: { fontFamily: font.semibold, fontSize: fontSize.md, color: colors.onSurface },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.sm,
    padding: spacing.sm, fontFamily: font.regular, fontSize: fontSize.md,
  },
  section: { fontFamily: font.semibold, fontSize: fontSize.md, color: colors.onSurface, marginTop: spacing.sm },
  emptyChildren: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  child: {
    flexDirection: "row", justifyContent: "space-between", alignItems: "center",
    padding: spacing.sm, borderWidth: 1, borderColor: colors.border,
    borderRadius: radius.sm, backgroundColor: colors.surface,
  },
  childNum: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface, flex: 1 },
  childStatus: { fontFamily: font.bold, fontSize: 10, color: colors.muted, letterSpacing: 0.5, marginRight: spacing.sm },
  childAmount: { fontFamily: font.bold, fontSize: fontSize.sm, color: colors.onSurface },
});
