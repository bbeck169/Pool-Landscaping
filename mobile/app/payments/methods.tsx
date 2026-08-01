// Phase 16 · Feb-2026 — Mobile payment-methods list.
//
// Customer role → their own cards. Admin+ → picker to select a customer
// first, then their cards. Add card opens the web portal via
// expo-web-browser — native card capture with Stripe Elements is
// intentionally out of scope this phase (documented in the deliverables).
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, TextInput,
  RefreshControl, Alert,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import * as WebBrowser from "expo-web-browser";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Card, EmptyState, PrimaryButton } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";
import { RoleGate, isCustomer, isAdminPlus } from "@/src/components/RoleGate";
import { useAuth } from "@/src/auth";

type Pm = {
  provider_payment_method_id: string;
  brand?: string;
  last4?: string;
  exp_month?: number;
  exp_year?: number;
  is_default?: boolean;
};

function _webPortalUrl(): string {
  const base = (process.env.EXPO_PUBLIC_WEB_BASE_URL || "").replace(/\/$/, "");
  return `${base || ""}/portal/payment-methods`;
}

export default function PaymentMethods() {
  const { user } = useAuth();
  const [customerId, setCustomerId] = useState<string>("");
  const [pms, setPms] = useState<Pm[]>([]);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [customers, setCustomers] = useState<{ id: string; name: string }[]>([]);
  const [q, setQ] = useState("");

  // For customers, use their own linked customer_id.
  useEffect(() => {
    if (isCustomer(user) && user?.customer_id) {
      setCustomerId(user.customer_id);
    }
  }, [user]);

  // Admin+ needs a customer picker.
  const loadCustomers = useCallback(async () => {
    if (!isAdminPlus(user)) return;
    try {
      const j: any = await api.get("/customers");
      setCustomers((j || []).map((c: any) => ({ id: c.id, name: c.name || c.email || c.id })).slice(0, 100));
    } catch {
      setCustomers([]);
    }
  }, [user]);
  useFocusEffect(useCallback(() => { loadCustomers(); }, [loadCustomers]));

  const load = useCallback(async () => {
    if (!customerId) { setPms([]); return; }
    setLoading(true);
    try {
      const j: any = await api.get(`/payments/stripe/payment-methods/${encodeURIComponent(customerId)}`);
      setPms(j?.payment_methods || []);
    } catch {
      setPms([]);
    } finally {
      setLoading(false);
    }
  }, [customerId]);

  useEffect(() => { load(); }, [load]);

  const remove = (pm: Pm) => {
    Alert.alert("Remove card?", `Card ending in ${pm.last4 || '----'} will be removed.`, [
      { text: "Cancel", style: "cancel" },
      { text: "Remove", style: "destructive", onPress: async () => {
        try {
          await api.del(`/payments/stripe/payment-methods/${encodeURIComponent(pm.provider_payment_method_id)}`);
          await load();
        } catch (err: any) {
          Alert.alert("Failed", String(err?.message || err));
        }
      } },
    ]);
  };

  const openAddCardWeb = async () => {
    const url = _webPortalUrl();
    if (!url || !url.startsWith("http")) {
      Alert.alert("Not configured",
        "Set EXPO_PUBLIC_WEB_BASE_URL to your web portal to add cards from mobile.");
      return;
    }
    await WebBrowser.openBrowserAsync(url);
  };

  const filteredCustomers = customers.filter(
    (c) => !q || c.name.toLowerCase().includes(q.toLowerCase())
  ).slice(0, 30);

  return (
    <View style={styles.container}>
      <Header title="Payment methods" />
      <ScrollView
        contentContainerStyle={styles.body}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={async () => {
            setRefreshing(true); await load(); setRefreshing(false);
          }} />
        }
      >
        {/* Admin+ picker */}
        {isAdminPlus(user) ? (
          <Card>
            <Text style={styles.sectionLabel}>Customer</Text>
            <TextInput
              testID="pm-customer-search"
              value={q}
              onChangeText={setQ}
              placeholder="Search customers…"
              placeholderTextColor={colors.muted}
              style={styles.input}
            />
            {q ? (
              <View style={{ maxHeight: 220 }}>
                <ScrollView>
                  {filteredCustomers.map((c) => (
                    <Pressable
                      key={c.id}
                      testID={`pm-customer-${c.id}`}
                      onPress={() => { setCustomerId(c.id); setQ(""); }}
                      style={styles.custRow}
                    >
                      <Text style={styles.custName}>{c.name}</Text>
                      <Ionicons name="chevron-forward" size={14} color={colors.muted} />
                    </Pressable>
                  ))}
                </ScrollView>
              </View>
            ) : null}
            {customerId ? (
              <View style={styles.selectedRow}>
                <Text style={styles.selectedLabel}>Viewing:</Text>
                <Text style={styles.selectedId} testID="pm-selected-customer">{customerId}</Text>
              </View>
            ) : null}
          </Card>
        ) : null}

        <Card>
          <View style={styles.rowBetween}>
            <Text style={styles.sectionLabel}>Cards on file</Text>
            <PrimaryButton
              variant="outline"
              title="Add card"
              icon="add-circle-outline"
              onPress={openAddCardWeb}
              testID="pm-add-card-btn"
            />
          </View>
          {loading ? (
            <Text style={styles.hint}>Loading…</Text>
          ) : !customerId ? (
            <EmptyState
              icon="person-outline"
              title="Select a customer"
              subtitle="Search above to pick a customer to view their cards."
              testID="pm-no-customer-empty"
            />
          ) : pms.length === 0 ? (
            <EmptyState
              icon="card-outline"
              title="No cards saved yet"
              subtitle="Tap Add card to capture one via the web portal."
              testID="pm-empty"
            />
          ) : (
            pms.map((pm) => (
              <View key={pm.provider_payment_method_id} style={styles.pmRow}
                    testID={`pm-row-${pm.provider_payment_method_id}`}>
                <Ionicons name="card-outline" size={22} color={colors.brand} />
                <View style={{ flex: 1 }}>
                  <Text style={styles.pmTitle}>
                    <Text style={{ textTransform: "capitalize" }}>{pm.brand || "Card"}</Text>
                    {" "}•••• {pm.last4 || "----"}
                    {pm.is_default ? (
                      <Text style={styles.defaultChip}> DEFAULT</Text>
                    ) : null}
                  </Text>
                  <Text style={styles.pmMeta}>
                    exp {String(pm.exp_month || "").padStart(2, "0")}/{pm.exp_year || "----"}
                  </Text>
                </View>
                <Pressable
                  testID={`pm-remove-${pm.provider_payment_method_id}`}
                  accessibilityLabel="Remove card"
                  onPress={() => remove(pm)}
                >
                  <Ionicons name="trash-outline" size={18} color={colors.error} />
                </Pressable>
              </View>
            ))
          )}
        </Card>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.surface },
  body: { padding: spacing.lg, gap: spacing.md, paddingBottom: spacing["3xl"] },
  sectionLabel: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface, marginBottom: spacing.sm },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    padding: spacing.md, fontFamily: font.regular, fontSize: fontSize.base,
    color: colors.onSurface,
  },
  custRow: {
    flexDirection: "row", justifyContent: "space-between", alignItems: "center",
    paddingVertical: 10, borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.divider,
  },
  custName: { fontFamily: font.medium, fontSize: fontSize.base, color: colors.onSurface },
  selectedRow: { flexDirection: "row", gap: 6, alignItems: "center", marginTop: spacing.sm },
  selectedLabel: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted },
  selectedId: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurface },
  rowBetween: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: spacing.sm },
  hint: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  pmRow: {
    flexDirection: "row", alignItems: "center", gap: spacing.md,
    paddingVertical: 10, borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.divider,
  },
  pmTitle: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  defaultChip: { fontSize: 10, fontFamily: font.bold, color: colors.success, backgroundColor: "#DCFCE7", paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4, marginLeft: 6 },
  pmMeta: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
});
