/**
 * Phase 20B mobile A.5 · Asset detail + maintenance timeline.
 * Admins can log a new maintenance entry from an inline modal.
 */
import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, Modal, Alert } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import AppTextInput from "@/src/components/ui/AppTextInput";

export default function AssetDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin" || (user?.role as string) === "super_admin";

  const [asset, setAsset] = useState<any>(null);
  const [maint, setMaint] = useState<any[]>([]);
  const [showLog, setShowLog] = useState(false);
  const [form, setForm] = useState<any>({
    kind: "service", cost: "0", notes: "", next_due_at: "",
  });

  const load = useCallback(async () => {
    try {
      setAsset(await api.get(`/assets/${id}`));
      setMaint(await api.get(`/assets/${id}/maintenance`));
    } catch {}
  }, [id]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const submit = async () => {
    try {
      await api.post(`/assets/${id}/maintenance`, {
        kind: form.kind,
        cost: Number(form.cost) || 0,
        notes: form.notes,
        next_due_at: form.next_due_at || undefined,
      });
      setShowLog(false);
      setForm({ kind: "service", cost: "0", notes: "", next_due_at: "" });
      load();
    } catch (e: any) { Alert.alert("Log failed", e?.message || ""); }
  };

  if (!asset) return (
    <View style={styles.root}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()}>
          <Ionicons name="chevron-back" size={22} color={colors.brand} />
        </Pressable>
        <Text style={styles.title}>Loading…</Text>
      </View>
    </View>
  );

  return (
    <View style={styles.root}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} testID="asset-back">
          <Ionicons name="chevron-back" size={22} color={colors.brand} />
        </Pressable>
        <Text style={styles.title} numberOfLines={1}>{asset.name}</Text>
        <View style={{ width: 22 }} />
      </View>

      <ScrollView contentContainerStyle={{ padding: spacing.lg,
                                            paddingBottom: 120 }}>
        <View style={styles.hero}>
          <View style={styles.heroIcon}>
            <Ionicons
              name={asset.category === "vehicle" ? "car-outline"
                 : asset.category === "tool"    ? "hammer-outline"
                 : "cube-outline"}
              size={36} color={colors.brand} />
          </View>
          <Text style={styles.heroTitle}>{asset.name}</Text>
          <Text style={styles.heroMeta}>
            {asset.category}
            {asset.asset_tag ? ` · ${asset.asset_tag}` : ""}
          </Text>
        </View>

        <View style={styles.meta}>
          <Row label="Status" value={asset.status || "active"} />
          {asset.serial_number
            ? <Row label="Serial" value={asset.serial_number} /> : null}
          {asset.assigned_to_user_id
            ? <Row label="Assigned" value={asset.assigned_to_user_id.slice(0, 8)} />
            : null}
          {asset.next_maintenance_due_at
            ? <Row label="Next due"
                    value={(asset.next_maintenance_due_at || "").slice(0, 10)} />
            : null}
          {asset.notes ? <Row label="Notes" value={asset.notes} /> : null}
        </View>

        <View style={styles.sectionHead}>
          <Text style={styles.sectionTitle}>Maintenance history</Text>
          {isAdmin && (
            <Pressable style={styles.logBtn} onPress={() => setShowLog(true)}
                       testID="asset-log-maint">
              <Ionicons name="add" size={14} color="#fff" />
              <Text style={styles.logBtnText}>Log</Text>
            </Pressable>
          )}
        </View>

        {maint.length === 0 ? (
          <Text style={styles.empty}>No maintenance logged yet.</Text>
        ) : maint.map((m) => (
          <View key={m.id} style={styles.mrow} testID={`maint-row-${m.id}`}>
            <View>
              <Text style={styles.mtitle}>
                {m.kind[0].toUpperCase() + m.kind.slice(1)}
              </Text>
              <Text style={styles.mmeta}>
                {(m.performed_at || "").slice(0, 10)}
                {" · $"}{(m.cost || 0).toFixed(2)}
              </Text>
              {m.notes ? <Text style={styles.mnotes}>{m.notes}</Text> : null}
              {m.next_due_at ? (
                <Text style={styles.mnext}>
                  Next: {(m.next_due_at || "").slice(0, 10)}
                </Text>
              ) : null}
            </View>
          </View>
        ))}
      </ScrollView>

      <Modal visible={showLog} transparent animationType="slide"
             onRequestClose={() => setShowLog(false)}>
        <View style={styles.sheetBg}>
          <View style={styles.sheet}>
            <View style={styles.sheetHead}>
              <Text style={styles.sheetTitle}>Log Maintenance</Text>
              <Pressable onPress={() => setShowLog(false)}>
                <Ionicons name="close" size={22} color={colors.muted}/>
              </Pressable>
            </View>
            <Text style={styles.label}>Kind</Text>
            <View style={styles.chipsRow}>
              {["service", "repair", "inspection"].map((k) => (
                <Pressable key={k}
                           onPress={() => setForm({ ...form, kind: k })}
                           style={[styles.chip,
                                   form.kind === k ? styles.chipActive : null]}
                           testID={`maint-kind-${k}`}>
                  <Text style={[styles.chipText,
                                form.kind === k ? { color: "#fff" } : null]}>
                    {k}
                  </Text>
                </Pressable>
              ))}
            </View>
            <AppTextInput value={form.cost}
                       onChangeText={(v) => setForm({ ...form, cost: v })}
                       placeholder="Cost ($)"
                       placeholderTextColor={colors.muted}
                       keyboardType="numeric"
                       style={styles.input}
                       testID="maint-cost" />
            <AppTextInput value={form.notes}
                       onChangeText={(v) => setForm({ ...form, notes: v })}
                       placeholder="Notes"
                       placeholderTextColor={colors.muted}
                       multiline
                       style={[styles.input, { minHeight: 80 }]}
                       testID="maint-notes" />
            <AppTextInput value={form.next_due_at}
                       onChangeText={(v) => setForm({ ...form, next_due_at: v })}
                       placeholder="Next due (YYYY-MM-DD, optional)"
                       placeholderTextColor={colors.muted}
                       style={styles.input}
                       testID="maint-next-due" />
            <Pressable style={styles.submit} onPress={submit}
                       testID="maint-submit">
              <Text style={styles.submitText}>Save entry</Text>
            </Pressable>
          </View>
        </View>
      </Modal>
    </View>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.metaRow}>
      <Text style={styles.metaLabel}>{label}</Text>
      <Text style={styles.metaValue} numberOfLines={2}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  header: { flexDirection: "row", alignItems: "center", gap: spacing.md,
            padding: spacing.md, backgroundColor: colors.surface,
            borderBottomWidth: 1, borderColor: colors.border },
  title: { flex: 1, fontFamily: font.bold, fontSize: fontSize.xl,
           color: colors.onSurface },
  hero: { alignItems: "center", padding: spacing.xl,
          backgroundColor: colors.surface, borderRadius: radius.lg,
          borderWidth: 1, borderColor: colors.border,
          marginBottom: spacing.lg },
  heroIcon: { width: 72, height: 72, borderRadius: 36,
              backgroundColor: colors.brandTertiary,
              alignItems: "center", justifyContent: "center",
              marginBottom: spacing.md },
  heroTitle: { fontFamily: font.bold, fontSize: fontSize.xl,
               color: colors.onSurface, textAlign: "center" },
  heroMeta: { fontFamily: font.regular, fontSize: fontSize.sm,
              color: colors.muted, marginTop: 4 },
  meta: { backgroundColor: colors.surface, borderRadius: radius.lg,
          padding: spacing.md, borderWidth: 1, borderColor: colors.border,
          marginBottom: spacing.lg },
  metaRow: { flexDirection: "row", justifyContent: "space-between",
             paddingVertical: 6 },
  metaLabel: { fontFamily: font.regular, fontSize: fontSize.sm,
               color: colors.muted },
  metaValue: { fontFamily: font.semibold, fontSize: fontSize.sm,
               color: colors.onSurface, maxWidth: "60%",
               textAlign: "right" },
  sectionHead: { flexDirection: "row", justifyContent: "space-between",
                 alignItems: "center", marginBottom: spacing.sm },
  sectionTitle: { fontFamily: font.bold, fontSize: fontSize.lg,
                  color: colors.onSurface },
  logBtn: { flexDirection: "row", alignItems: "center", gap: 4,
            backgroundColor: colors.brand,
            paddingHorizontal: 10, paddingVertical: 6, borderRadius: 999 },
  logBtnText: { color: "#fff", fontFamily: font.bold, fontSize: fontSize.sm },
  empty: { color: colors.muted, fontFamily: font.regular,
           fontSize: fontSize.sm },
  mrow: { backgroundColor: colors.surface, padding: spacing.md,
          borderRadius: radius.md, borderWidth: 1, borderColor: colors.border,
          marginBottom: spacing.sm },
  mtitle: { fontFamily: font.semibold, fontSize: fontSize.base,
            color: colors.onSurface },
  mmeta: { fontFamily: font.regular, fontSize: fontSize.sm,
           color: colors.muted, marginTop: 2 },
  mnotes: { fontFamily: font.regular, fontSize: 12,
            color: colors.onSurface, marginTop: 4 },
  mnext: { fontFamily: font.semibold, fontSize: 12,
           color: "#92400E", marginTop: 4 },
  sheetBg: { flex: 1, backgroundColor: "rgba(0,0,0,0.5)",
             justifyContent: "flex-end" },
  sheet: { backgroundColor: colors.surface, padding: spacing.lg,
           borderTopLeftRadius: 20, borderTopRightRadius: 20 },
  sheetHead: { flexDirection: "row", justifyContent: "space-between",
               alignItems: "center", marginBottom: spacing.md },
  sheetTitle: { fontFamily: font.bold, fontSize: fontSize.xl,
                color: colors.onSurface },
  label: { fontFamily: font.bold, fontSize: fontSize.sm, color: colors.muted,
           textTransform: "uppercase", marginBottom: spacing.sm },
  chipsRow: { flexDirection: "row", gap: spacing.sm, flexWrap: "wrap",
              marginBottom: spacing.md },
  chip: { paddingHorizontal: 14, paddingVertical: 6, borderRadius: 20,
          borderWidth: 1, borderColor: colors.border,
          backgroundColor: colors.surfaceSecondary },
  chipActive: { backgroundColor: colors.brand, borderColor: colors.brand },
  chipText: { fontFamily: font.semibold, fontSize: fontSize.sm,
              color: colors.onSurface },
  input: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.md,
           padding: spacing.md, fontFamily: font.regular, fontSize: fontSize.base,
           color: colors.onSurface, marginBottom: spacing.sm,
           borderWidth: 1, borderColor: colors.border, textAlignVertical: "top" },
  submit: { backgroundColor: colors.brand, borderRadius: radius.md,
            padding: spacing.md, alignItems: "center",
            marginTop: spacing.md },
  submitText: { color: "#fff", fontFamily: font.bold, fontSize: fontSize.base },
});
