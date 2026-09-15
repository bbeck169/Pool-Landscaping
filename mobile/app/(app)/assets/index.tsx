/**
 * Phase 20B mobile A.5 · Assets list.
 *
 * - Technicians see only assets assigned to them ("My Equipment").
 * - Admins see the full tenant asset list with a category filter.
 *   FAB (admin only) opens a new-asset sheet.
 */
import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, FlatList, Pressable, Modal, Alert,
  RefreshControl } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Loading } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";
import AppTextInput from "@/src/components/ui/AppTextInput";

const CATS = [
  { key: "",          label: "All" },
  { key: "vehicle",   label: "Vehicles" },
  { key: "equipment", label: "Equipment" },
  { key: "tool",      label: "Tools" },
];

const STATUS_COLORS: Record<string, { bg: string; fg: string }> = {
  active:      { bg: "#DCFCE7", fg: "#166534" },
  maintenance: { bg: "#FEF3C7", fg: "#92400E" },
  retired:     { bg: "#F3F4F6", fg: "#4B5563" },
};

export default function AssetsIndex() {
  const { user } = useAuth();
  const router = useRouter();
  const isAdmin = user?.role === "admin" || (user?.role as string) === "super_admin";
  const isCustomer = user?.role === "customer";

  const [rows, setRows] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [cat, setCat] = useState("");
  const [showNew, setShowNew] = useState(false);
  const [form, setForm] = useState({
    name: "", category: "vehicle", asset_tag: "",
  });

  const load = useCallback(async () => {
    try {
      const q = cat ? `?category=${cat}` : "";
      setRows(await api.get(`/assets${q}`));
    } catch (e: any) {
      if (String(e?.message || "").includes("403")) setRows([]);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [cat]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const create = async () => {
    if (!form.name.trim()) return;
    try {
      await api.post("/assets", form);
      setShowNew(false);
      setForm({ name: "", category: "vehicle", asset_tag: "" });
      load();
    } catch (e: any) { Alert.alert("Create failed", e?.message || ""); }
  };

  if (isCustomer) return (
    <View style={styles.root}>
      <Header title="Equipment" />
      <View style={styles.empty}>
        <Text style={styles.emptyText}>Not available on your plan.</Text>
      </View>
    </View>
  );

  return (
    <View style={styles.root}>
      <Header title={isAdmin ? "Company Assets" : "My Equipment"}
              subtitle={isAdmin
                ? "Vehicles, equipment, and tools"
                : "Assets assigned to you"} />

      {isAdmin && (
        <View style={styles.filterRow}>
          {CATS.map((c) => (
            <Pressable key={c.key} onPress={() => setCat(c.key)}
                       style={[styles.chip,
                               cat === c.key ? styles.chipActive : null]}
                       testID={`assets-cat-${c.key || "all"}`}>
              <Text style={[styles.chipText,
                            cat === c.key ? { color: "#fff" } : null]}>
                {c.label}
              </Text>
            </Pressable>
          ))}
        </View>
      )}

      {loading ? <Loading /> : (
        <FlatList
          testID="assets-list"
          data={rows}
          keyExtractor={(a) => a.id}
          contentContainerStyle={{ padding: spacing.lg, paddingBottom: 120 }}
          refreshControl={
            <RefreshControl refreshing={refreshing}
                            onRefresh={() => { setRefreshing(true); load(); }} />}
          renderItem={({ item }) => {
            const sc = STATUS_COLORS[item.status || "active"];
            const dueSoon = item.next_maintenance_due_at
              && (new Date(item.next_maintenance_due_at).getTime()
                  - Date.now()) < 7 * 86400_000;
            return (
              <Pressable style={styles.row}
                         onPress={() => router.push({
                           pathname: "/(app)/assets/[id]",
                           params: { id: item.id },
                         } as any)}
                         testID={`asset-row-${item.id}`}>
                <View style={styles.rowIcon}>
                  <Ionicons
                    name={item.category === "vehicle" ? "car-outline"
                       : item.category === "tool"    ? "hammer-outline"
                       : "cube-outline"}
                    size={22} color={colors.brand} />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.rowTitle} numberOfLines={1}>
                    {item.name}
                  </Text>
                  <Text style={styles.rowMeta}>
                    {item.category}
                    {item.asset_tag ? ` · ${item.asset_tag}` : ""}
                  </Text>
                  {dueSoon && (
                    <View style={styles.dueChip}>
                      <Ionicons name="alert-circle" size={12} color="#92400E" />
                      <Text style={styles.dueChipText}>
                        Maintenance due{" "}
                        {(item.next_maintenance_due_at || "").slice(0, 10)}
                      </Text>
                    </View>
                  )}
                </View>
                <View style={[styles.statusPill, { backgroundColor: sc.bg }]}>
                  <Text style={[styles.statusPillText, { color: sc.fg }]}>
                    {(item.status || "active").toUpperCase()}
                  </Text>
                </View>
              </Pressable>
            );
          }}
          ListEmptyComponent={() => (
            <View style={styles.empty}>
              <Ionicons name="construct-outline" size={40} color={colors.muted}/>
              <Text style={styles.emptyText}>
                {isAdmin ? "No assets yet — add one with the + button."
                         : "No assets assigned to you yet."}
              </Text>
            </View>
          )}
        />
      )}

      {isAdmin && (
        <Pressable style={styles.fab} onPress={() => setShowNew(true)}
                   testID="assets-new-fab">
          <Ionicons name="add" size={26} color="#fff" />
        </Pressable>
      )}

      <Modal visible={showNew} transparent animationType="slide"
             onRequestClose={() => setShowNew(false)}>
        <View style={styles.modalBg}>
          <View style={styles.modalBody}>
            <View style={styles.modalHead}>
              <Text style={styles.modalTitle}>Add Asset</Text>
              <Pressable onPress={() => setShowNew(false)}>
                <Ionicons name="close" size={22} color={colors.muted}/>
              </Pressable>
            </View>
            <AppTextInput value={form.name}
                       onChangeText={(v) => setForm({ ...form, name: v })}
                       placeholder="Name (e.g., Truck #3)"
                       placeholderTextColor={colors.muted}
                       style={styles.input}
                       testID="asset-new-name" />
            <Text style={styles.label}>Category</Text>
            <View style={styles.chipsRow}>
              {CATS.filter((c) => c.key).map((c) => (
                <Pressable key={c.key}
                           onPress={() => setForm({ ...form, category: c.key })}
                           style={[styles.chip,
                                   form.category === c.key ? styles.chipActive : null]}
                           testID={`asset-new-cat-${c.key}`}>
                  <Text style={[styles.chipText,
                                form.category === c.key
                                  ? { color: "#fff" } : null]}>
                    {c.label}
                  </Text>
                </Pressable>
              ))}
            </View>
            <AppTextInput value={form.asset_tag}
                       onChangeText={(v) => setForm({ ...form, asset_tag: v })}
                       placeholder="Asset tag (optional)"
                       placeholderTextColor={colors.muted}
                       style={[styles.input, { marginTop: spacing.md }]}
                       testID="asset-new-tag" />
            <Pressable style={styles.submitBtn} onPress={create}
                       testID="asset-new-submit">
              <Text style={styles.submitText}>Create</Text>
            </Pressable>
          </View>
        </View>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  filterRow: { flexDirection: "row", gap: spacing.sm,
               paddingHorizontal: spacing.lg, paddingVertical: spacing.md,
               flexWrap: "wrap" },
  chip: { paddingHorizontal: 14, paddingVertical: 6, borderRadius: 20,
          borderWidth: 1, borderColor: colors.border,
          backgroundColor: colors.surface },
  chipActive: { backgroundColor: colors.brand, borderColor: colors.brand },
  chipText: { fontFamily: font.semibold, fontSize: fontSize.sm,
              color: colors.onSurface },
  chipsRow: { flexDirection: "row", gap: spacing.sm, flexWrap: "wrap" },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.md,
         backgroundColor: colors.surface, padding: spacing.md,
         borderRadius: radius.lg, marginBottom: spacing.sm,
         borderWidth: 1, borderColor: colors.border },
  rowIcon: { width: 44, height: 44, borderRadius: 22,
             backgroundColor: colors.brandTertiary,
             alignItems: "center", justifyContent: "center" },
  rowTitle: { fontFamily: font.semibold, fontSize: fontSize.base,
              color: colors.onSurface },
  rowMeta: { fontFamily: font.regular, fontSize: fontSize.sm,
             color: colors.muted, marginTop: 2 },
  dueChip: { flexDirection: "row", alignItems: "center", gap: 4,
             backgroundColor: "#FEF3C7", paddingHorizontal: 6,
             paddingVertical: 2, borderRadius: 6, alignSelf: "flex-start",
             marginTop: 4 },
  dueChipText: { fontFamily: font.semibold, fontSize: 10, color: "#92400E" },
  statusPill: { paddingHorizontal: 8, paddingVertical: 4, borderRadius: 999 },
  statusPillText: { fontFamily: font.bold, fontSize: 10, letterSpacing: 0.5 },
  fab: { position: "absolute", right: 24, bottom: 24, width: 56, height: 56,
         borderRadius: 28, backgroundColor: colors.brand,
         alignItems: "center", justifyContent: "center", elevation: 4 },
  empty: { paddingVertical: 60, alignItems: "center" },
  emptyText: { color: colors.muted, marginTop: spacing.md,
               textAlign: "center", fontFamily: font.regular,
               fontSize: fontSize.base, paddingHorizontal: spacing.xl },
  modalBg: { flex: 1, backgroundColor: "rgba(0,0,0,0.5)",
             justifyContent: "flex-end" },
  modalBody: { backgroundColor: colors.surface, padding: spacing.lg,
               borderTopLeftRadius: 20, borderTopRightRadius: 20 },
  modalHead: { flexDirection: "row", justifyContent: "space-between",
               alignItems: "center", marginBottom: spacing.md },
  modalTitle: { fontFamily: font.bold, fontSize: fontSize.xl,
                color: colors.onSurface },
  input: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.md,
           padding: spacing.md, fontFamily: font.regular, fontSize: fontSize.base,
           color: colors.onSurface, borderWidth: 1, borderColor: colors.border },
  label: { fontFamily: font.bold, fontSize: fontSize.sm, color: colors.muted,
           textTransform: "uppercase", marginTop: spacing.md,
           marginBottom: spacing.sm, letterSpacing: 0.6 },
  submitBtn: { backgroundColor: colors.brand, borderRadius: radius.md,
               padding: spacing.md, alignItems: "center",
               marginTop: spacing.lg },
  submitText: { color: "#fff", fontFamily: font.bold, fontSize: fontSize.base },
});
