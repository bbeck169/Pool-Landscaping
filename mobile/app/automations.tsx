import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, FlatList, RefreshControl, Pressable, Switch, Platform, Alert } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Loading, EmptyState, PrimaryButton, Sheet } from "@/src/components/ui";
import { Header, IconButton } from "@/src/components/widgets";
import AppTextInput from "@/src/components/ui/AppTextInput";

const TRIGGERS = [
  { key: "lead_created", label: "Lead created" },
  { key: "job_completed", label: "Job completed" },
  { key: "invoice_unpaid", label: "Invoice unpaid" },
  { key: "service_requested", label: "Service requested" },
];
const ACTIONS = [
  { key: "send_welcome_sms", label: "Send welcome SMS" },
  { key: "request_review", label: "Request review" },
  { key: "send_reminder", label: "Send reminder" },
  { key: "notify_admin", label: "Notify admin" },
];

function labelOf(list: { key: string; label: string }[], k: string) {
  return list.find((x) => x.key === k)?.label || k;
}

export default function Automations() {
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [form, setForm] = useState({ name: "", trigger: "lead_created", action: "send_welcome_sms" });

  const load = useCallback(async () => {
    try {
      setItems(await api.get("/automations"));
    } catch {
      setItems([]);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const toggle = async (a: any) => {
    try { await api.put(`/automations/${a.id}`, { active: !a.active }); load(); } catch {}
  };

  const create = async () => {
    if (!form.name.trim()) { Alert.alert("Missing", "Enter a name."); return; }
    try {
      await api.post("/automations", { ...form, active: true });
      setAddOpen(false);
      setForm({ name: "", trigger: "lead_created", action: "send_welcome_sms" });
      load();
    } catch (e: any) {
      Alert.alert("Error", e?.message || "Could not create.");
    }
  };

  return (
    <View style={styles.root}>
      <Header title="Automation" back subtitle="Workflow rules" right={<IconButton icon="add" onPress={() => setAddOpen(true)} testID="add-automation-button" />} />
      {loading ? (
        <Loading testID="automations-loading" />
      ) : items.length === 0 ? (
        <EmptyState icon="git-branch-outline" title="No automations" subtitle="Automate follow-ups and reminders." testID="automations-empty" />
      ) : (
        <FlatList
          testID="automations-list"
          data={items}
          keyExtractor={(i) => i.id}
          contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
          renderItem={({ item }) => (
            <View style={[styles.card, !item.active && styles.cardInactive]} testID={`automation-${item.id}`}>
              <View style={{ flexDirection: "row", alignItems: "center" }}>
                <Text style={styles.name}>{item.name}</Text>
                <View style={{ flex: 1 }} />
                <Switch value={!!item.active} onValueChange={() => toggle(item)} trackColor={{ true: colors.brand, false: colors.surfaceTertiary }} thumbColor="#fff" testID={`automation-toggle-${item.id}`} />
              </View>
              <View style={styles.flowRow}>
                <View style={styles.triggerPill}>
                  <Ionicons name="flash-outline" size={12} color="#C2410C" />
                  <Text style={styles.triggerText}>{labelOf(TRIGGERS, item.trigger)}</Text>
                </View>
                <Ionicons name="arrow-forward" size={14} color={colors.muted} />
                <View style={styles.actionPill}>
                  <Ionicons name="play-outline" size={12} color={colors.brand} />
                  <Text style={styles.actionText}>{labelOf(ACTIONS, item.action)}</Text>
                </View>
              </View>
              <Text style={styles.runs}>{item.runs || 0} runs</Text>
            </View>
          )}
        />
      )}

      <Sheet visible={addOpen} onClose={() => setAddOpen(false)} title="New Automation" testID="add-automation-sheet">
        <Text style={styles.inputLabel}>NAME</Text>
        <AppTextInput style={styles.input} value={form.name} onChangeText={(v) => setForm((f) => ({ ...f, name: v }))} placeholder="e.g. Welcome new leads" placeholderTextColor={colors.muted} testID="automation-name-input" />
        <Text style={[styles.inputLabel, { marginTop: spacing.md }]}>WHEN (TRIGGER)</Text>
        <View style={styles.pickerWrap}>
          {TRIGGERS.map((t) => (
            <Pressable key={t.key} style={[styles.pickChip, form.trigger === t.key && styles.pickChipActive]} onPress={() => setForm((f) => ({ ...f, trigger: t.key }))} testID={`automation-trigger-${t.key}`}>
              <Text style={[styles.pickChipText, form.trigger === t.key && { color: "#fff" }]}>{t.label}</Text>
            </Pressable>
          ))}
        </View>
        <Text style={[styles.inputLabel, { marginTop: spacing.md }]}>THEN (ACTION)</Text>
        <View style={styles.pickerWrap}>
          {ACTIONS.map((a) => (
            <Pressable key={a.key} style={[styles.pickChip, form.action === a.key && styles.pickChipActive]} onPress={() => setForm((f) => ({ ...f, action: a.key }))} testID={`automation-action-${a.key}`}>
              <Text style={[styles.pickChipText, form.action === a.key && { color: "#fff" }]}>{a.label}</Text>
            </Pressable>
          ))}
        </View>
        <View style={{ height: spacing.md }} />
        <PrimaryButton title="Create Automation" onPress={create} testID="save-automation-button" />
      </Sheet>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  card: { backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.lg, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.md },
  cardInactive: { opacity: 0.6 },
  name: { fontFamily: font.semibold, fontSize: fontSize.lg, color: colors.onSurface },
  flowRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm, marginTop: spacing.sm, flexWrap: "wrap" },
  triggerPill: { flexDirection: "row", alignItems: "center", gap: 4, backgroundColor: "#FFEDD5", paddingHorizontal: 10, paddingVertical: 5, borderRadius: radius.pill },
  triggerText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: "#C2410C" },
  actionPill: { flexDirection: "row", alignItems: "center", gap: 4, backgroundColor: colors.brandTertiary, paddingHorizontal: 10, paddingVertical: 5, borderRadius: radius.pill },
  actionText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.brand },
  runs: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: spacing.sm },
  inputLabel: { fontFamily: font.semibold, fontSize: 11, letterSpacing: 0.8, color: colors.onSurfaceSecondary, marginBottom: spacing.xs },
  input: { backgroundColor: colors.surfaceSecondary, borderWidth: 1.5, borderColor: colors.border, borderRadius: radius.md, paddingHorizontal: spacing.md, height: 48, fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}) },
  pickerWrap: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  pickChip: { paddingHorizontal: spacing.md, height: 36, borderRadius: radius.pill, alignItems: "center", justifyContent: "center", backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border },
  pickChipActive: { backgroundColor: colors.brand, borderColor: colors.brand },
  pickChipText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
});
