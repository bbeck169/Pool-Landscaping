import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, FlatList, RefreshControl, Pressable, Switch, Platform, Alert } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize, money } from "@/src/theme";
import { Loading, EmptyState, PrimaryButton, Sheet } from "@/src/components/ui";
import { Header, IconButton } from "@/src/components/widgets";
import { formatCustomerName } from "@/src/utils/formatCustomerName";
import AppTextInput from "@/src/components/ui/AppTextInput";

const FREQS = ["weekly", "monthly", "quarterly"];

function fmtDate(iso?: string) {
  if (!iso) return "—";
  try {
    return new Date(iso + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  } catch {
    return iso;
  }
}

export default function AutoBilling() {
  const [items, setItems] = useState<any[]>([]);
  const [customers, setCustomers] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [form, setForm] = useState({ customer_id: "", service: "", frequency: "monthly", amount: "" });

  const load = useCallback(async () => {
    try {
      const [plans, custs] = await Promise.all([api.get("/billing-plans"), api.get("/customers")]);
      setItems(plans);
      setCustomers(custs || []);
    } catch {
      setItems([]);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const toggleActive = async (plan: any) => {
    await api.put(`/billing-plans/${plan.id}`, { active: !plan.active });
    load();
  };

  const runNow = async (plan: any) => {
    await api.post(`/billing-plans/${plan.id}/run`);
    Alert.alert("Invoice generated", `A new invoice for ${formatCustomerName(plan)} was created.`);
    load();
  };

  const create = async () => {
    if (!form.customer_id || !form.service.trim()) {
      Alert.alert("Missing info", "Pick a customer and enter a service.");
      return;
    }
    await api.post("/billing-plans", { ...form, amount: parseFloat(form.amount) || 0 });
    setAddOpen(false);
    setForm({ customer_id: "", service: "", frequency: "monthly", amount: "" });
    load();
  };

  const activeCount = items.filter((p) => p.active).length;
  const mrr = items.filter((p) => p.active).reduce((s, p) => {
    const mult = p.frequency === "weekly" ? 4.33 : p.frequency === "quarterly" ? 1 / 3 : 1;
    return s + (p.amount || 0) * mult;
  }, 0);

  return (
    <View style={styles.root}>
      <Header title="Auto Billing" back subtitle="Recurring revenue" right={<IconButton icon="add" onPress={() => setAddOpen(true)} testID="add-plan-button" />} />
      {loading ? (
        <Loading testID="billing-loading" />
      ) : (
        <FlatList
          testID="billing-list"
          data={items}
          keyExtractor={(i) => i.id}
          ListHeaderComponent={
            items.length ? (
              <View style={styles.summaryCard}>
                <View style={styles.summaryItem}>
                  <Text style={styles.summaryValue}>{money(mrr)}</Text>
                  <Text style={styles.summaryLabel}>Est. Monthly Recurring</Text>
                </View>
                <View style={styles.summaryDivider} />
                <View style={styles.summaryItem}>
                  <Text style={styles.summaryValue}>{activeCount}</Text>
                  <Text style={styles.summaryLabel}>Active Plans</Text>
                </View>
              </View>
            ) : null
          }
          contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
          ListEmptyComponent={<EmptyState icon="repeat-outline" title="No billing plans" subtitle="Set up recurring invoices for your customers." testID="billing-empty" />}
          renderItem={({ item }) => (
            <View style={[styles.card, !item.active && styles.cardInactive]} testID={`plan-${item.id}`}>
              <View style={styles.cardTop}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.service}>{item.service}</Text>
                  <Text style={styles.customer}>{formatCustomerName(item)}</Text>
                </View>
                <Switch
                  value={!!item.active}
                  onValueChange={() => toggleActive(item)}
                  trackColor={{ true: colors.brand, false: colors.surfaceTertiary }}
                  thumbColor="#fff"
                  testID={`plan-toggle-${item.id}`}
                />
              </View>
              <View style={styles.cardMeta}>
                <View style={styles.freqPill}>
                  <Ionicons name="repeat" size={12} color={colors.brand} />
                  <Text style={styles.freqText}>{item.frequency}</Text>
                </View>
                <Text style={styles.amount}>{money(item.amount)}</Text>
              </View>
              <View style={styles.cardFooter}>
                <View style={{ flexDirection: "row", alignItems: "center", gap: 5 }}>
                  <Ionicons name="calendar-outline" size={14} color={colors.muted} />
                  <Text style={styles.nextRun}>Next: {fmtDate(item.next_run)}</Text>
                </View>
                <Pressable style={styles.runBtn} onPress={() => runNow(item)} testID={`plan-run-${item.id}`} hitSlop={6}>
                  <Ionicons name="flash" size={14} color="#fff" />
                  <Text style={styles.runBtnText}>Run now</Text>
                </Pressable>
              </View>
            </View>
          )}
        />
      )}

      <Sheet visible={addOpen} onClose={() => setAddOpen(false)} title="New Billing Plan" testID="add-plan-sheet">
        <Text style={styles.inputLabel}>CUSTOMER</Text>
        <View style={styles.pickerWrap}>
          {customers.map((c) => (
            <Pressable
              key={c.id}
              style={[styles.pickChip, form.customer_id === c.id && styles.pickChipActive]}
              onPress={() => setForm((f) => ({ ...f, customer_id: c.id }))}
              testID={`plan-customer-${c.id}`}
            >
              <Text style={[styles.pickChipText, form.customer_id === c.id && { color: "#fff" }]}>{c.name}</Text>
            </Pressable>
          ))}
        </View>

        <Text style={[styles.inputLabel, { marginTop: spacing.md }]}>SERVICE</Text>
        <AppTextInput style={styles.input} value={form.service} onChangeText={(v) => setForm((f) => ({ ...f, service: v }))} placeholder="e.g. Weekly Pool Cleaning" placeholderTextColor={colors.muted} testID="plan-service-input" />

        <Text style={[styles.inputLabel, { marginTop: spacing.md }]}>FREQUENCY</Text>
        <View style={styles.pickerWrap}>
          {FREQS.map((fq) => (
            <Pressable key={fq} style={[styles.pickChip, form.frequency === fq && styles.pickChipActive]} onPress={() => setForm((f) => ({ ...f, frequency: fq }))} testID={`plan-freq-${fq}`}>
              <Text style={[styles.pickChipText, form.frequency === fq && { color: "#fff" }]}>{fq}</Text>
            </Pressable>
          ))}
        </View>

        <Text style={[styles.inputLabel, { marginTop: spacing.md }]}>AMOUNT ($)</Text>
        <AppTextInput style={styles.input} value={form.amount} onChangeText={(v) => setForm((f) => ({ ...f, amount: v }))} keyboardType="decimal-pad" placeholder="0.00" placeholderTextColor={colors.muted} testID="plan-amount-input" />

        <View style={{ height: spacing.md }} />
        <PrimaryButton title="Create Plan" onPress={create} testID="save-plan-button" />
      </Sheet>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  summaryCard: { flexDirection: "row", backgroundColor: colors.brand, borderRadius: radius.lg, padding: spacing.lg, marginBottom: spacing.md },
  summaryItem: { flex: 1, alignItems: "center" },
  summaryDivider: { width: 1, backgroundColor: "rgba(255,255,255,0.25)" },
  summaryValue: { fontFamily: font.bold, fontSize: fontSize["2xl"], color: "#fff" },
  summaryLabel: { fontFamily: font.medium, fontSize: fontSize.sm, color: "rgba(255,255,255,0.85)", marginTop: 2, textAlign: "center" },
  card: { backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.lg, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.md },
  cardInactive: { opacity: 0.6 },
  cardTop: { flexDirection: "row", alignItems: "center" },
  service: { fontFamily: font.semibold, fontSize: fontSize.lg, color: colors.onSurface },
  customer: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
  cardMeta: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: spacing.sm },
  freqPill: { flexDirection: "row", alignItems: "center", gap: 4, backgroundColor: colors.brandTertiary, paddingHorizontal: 10, paddingVertical: 4, borderRadius: radius.pill },
  freqText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.brand, textTransform: "capitalize" },
  amount: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.brand },
  cardFooter: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", borderTopWidth: 1, borderTopColor: colors.divider, paddingTop: spacing.sm, marginTop: spacing.sm },
  nextRun: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
  runBtn: { flexDirection: "row", alignItems: "center", gap: 4, backgroundColor: colors.brandSecondary, paddingHorizontal: 12, height: 32, borderRadius: radius.pill },
  runBtnText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: "#fff" },
  inputLabel: { fontFamily: font.semibold, fontSize: 11, letterSpacing: 0.8, color: colors.onSurfaceSecondary, marginBottom: spacing.xs },
  input: { backgroundColor: colors.surfaceSecondary, borderWidth: 1.5, borderColor: colors.border, borderRadius: radius.md, paddingHorizontal: spacing.md, height: 48, fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}) },
  pickerWrap: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  pickChip: { paddingHorizontal: spacing.md, height: 36, borderRadius: radius.pill, alignItems: "center", justifyContent: "center", backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border },
  pickChipActive: { backgroundColor: colors.brand, borderColor: colors.brand },
  pickChipText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurfaceSecondary, textTransform: "capitalize" },
});
