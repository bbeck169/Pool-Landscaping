import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, Pressable, Platform, Alert, ScrollView } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import { Loading } from "@/src/components/ui";
import { showConfirm } from "@/src/components/ConfirmModal";
import AppTextInput from "@/src/components/ui/AppTextInput";

// TD-81-adj D2 — GET returns {items:[{id,name,...}], total}; POST returns the
// created doc (not a list), so we reload after Add. Remove → Archive: the
// legacy DELETE is shadowed by finances.py (TD-81-adj-be), web uses /archive.
type Cat = { id: string; name: string };

export default function IncomeCategories() {
  const [cats, setCats] = useState<Cat[]>([]);
  const [loading, setLoading] = useState(true);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try { const r = await api.get("/income-categories"); setCats((r?.items || []).filter((c: any) => c?.id && c?.name)); }
    catch { setCats([]); }
    finally { setLoading(false); }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const add = async () => {
    if (!name.trim()) return;
    setBusy(true);
    try { await api.post("/income-categories", { name: name.trim() }); setName(""); await load(); }
    catch (e: any) {
      Alert.alert("Error", e?.detail?.error === "duplicate_name" ? "A category with that name already exists." : (e.message || "Could not add."));
    }
    finally { setBusy(false); }
  };

  const archive = (c: Cat) => {
    showConfirm({
      title: "Archive category",
      message: `Archive "${c.name}"? It is hidden from pickers; line items using it are flagged for re-categorizing.`,
      confirmLabel: "Archive",
      confirmStyle: "destructive",
      onConfirm: async () => {
        try { await api.post(`/income-categories/${encodeURIComponent(c.id)}/archive`, {}); await load(); }
        catch (e: any) { Alert.alert("Error", e.message || "Could not archive."); }
      },
    });
  };

  if (loading) return <Loading testID="income-cats-loading" />;

  return (
    <View style={styles.root}>
      <Header title="Income Categories" back subtitle="Used to tag every invoice line item" />
      <View style={styles.addRow}>
        <AppTextInput style={styles.input} value={name} onChangeText={setName} placeholder="New category (e.g. Repairs)" placeholderTextColor={colors.muted} testID="cat-input" onSubmitEditing={add} />
        <Pressable style={[styles.addBtn, busy && { opacity: 0.6 }]} onPress={add} disabled={busy} testID="cat-add">
          <Ionicons name="add" size={22} color="#fff" />
        </Pressable>
      </View>
      <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingTop: 0 }}>
        {cats.map((c) => (
          <View key={c.id} style={styles.row} testID={`cat-${c.name}`}>
            <Ionicons name="pricetag-outline" size={18} color={colors.brand} />
            <Text style={styles.rowText}>{c.name}</Text>
            <Pressable hitSlop={10} onPress={() => archive(c)} accessibilityLabel="Archive" style={styles.archiveBtn} testID={`cat-archive-${c.name}`}>
              <Ionicons name="archive-outline" size={17} color={colors.error} />
              <Text style={styles.archiveText}>Archive</Text>
            </Pressable>
          </View>
        ))}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  addRow: { flexDirection: "row", gap: spacing.sm, padding: spacing.lg, paddingBottom: spacing.md },
  input: { flex: 1, backgroundColor: colors.surface, borderWidth: 1.5, borderColor: colors.border, borderRadius: radius.md, paddingHorizontal: spacing.md, height: 48, fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}) },
  addBtn: { width: 48, height: 48, borderRadius: radius.md, backgroundColor: colors.brand, alignItems: "center", justifyContent: "center" },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.md, backgroundColor: colors.surface, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, padding: spacing.md, marginBottom: spacing.sm },
  rowText: { flex: 1, fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  archiveBtn: { flexDirection: "row", alignItems: "center", gap: 4, minHeight: 36, paddingHorizontal: spacing.sm },
  archiveText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.error },
});
