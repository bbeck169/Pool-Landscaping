import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, FlatList, RefreshControl, Pressable, TextInput, Platform, Alert } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { colors, spacing, radius, font, fontSize, money } from "@/src/theme";
import { Loading, EmptyState, PrimaryButton, Sheet } from "@/src/components/ui";
import { Header, IconButton } from "@/src/components/widgets";
import { ImportExport } from "@/src/components/ImportExport";

const ADMIN_ROLES = ["admin", "super_admin", "manager"];

export default function PriceBook() {
  const { user } = useAuth();
  const isAdmin = ADMIN_ROLES.includes(user?.role || "");
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [form, setForm] = useState({ name: "", category: "Service", unit: "each", unit_price: "" });
  // PB1: edit mode for wholesale/labor
  const [editItem, setEditItem] = useState<any>(null);
  const [editForm, setEditForm] = useState({ unit_price: "", wholesale_price: "", labor_cost_default: "" });
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    try {
      setItems(await api.get("/items"));
    } catch {
      setItems([]);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const create = async () => {
    if (!form.name.trim()) return;
    await api.post("/items", { ...form, unit_price: parseFloat(form.unit_price) || 0 });
    setAddOpen(false);
    setForm({ name: "", category: "Service", unit: "each", unit_price: "" });
    load();
  };

  const remove = async (iid: string) => {
    await api.del(`/items/${iid}`);
    load();
  };

  // PB1: open edit drawer
  const openEdit = (item: any) => {
    setEditItem(item);
    setEditForm({
      unit_price: String(item.unit_price ?? ""),
      wholesale_price: String(item.wholesale_price ?? ""),
      labor_cost_default: String(item.labor_cost_default ?? ""),
    });
  };

  const saveEdit = async () => {
    if (!editItem) return;
    const up: any = {};
    const rp = parseFloat(editForm.unit_price);
    const wp = parseFloat(editForm.wholesale_price);
    const lc = parseFloat(editForm.labor_cost_default);
    if (!isNaN(rp) && rp >= 0) up.unit_price = rp;
    else if (editForm.unit_price !== "") { Alert.alert("Validation", "Retail price must be ≥ 0."); return; }
    if (isAdmin) {
      if (!isNaN(wp) && wp >= 0) up.wholesale_price = wp;
      else if (editForm.wholesale_price !== "") { Alert.alert("Validation", "Wholesale price must be ≥ 0."); return; }
      if (!isNaN(lc) && lc >= 0) up.labor_cost_default = lc;
      else if (editForm.labor_cost_default !== "") { Alert.alert("Validation", "Labor cost must be ≥ 0."); return; }
    }
    setSaving(true);
    try {
      await api.patch(`/items/${editItem.id}`, up);
      setEditItem(null);
      load();
    } catch (e: any) {
      Alert.alert("Error", e?.message || "Failed to save.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <View style={styles.root}>
      <Header title="Price Book" back subtitle="Services, parts & chemicals" right={
        <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.xs }}>
          <ImportExport entity="items" label="items" exportPath="/export/items" importPath="/import/items" onDone={load} />
          <IconButton icon="add" onPress={() => setAddOpen(true)} testID="add-item-button" />
        </View>
      } />
      {loading ? (
        <Loading testID="items-loading" />
      ) : items.length === 0 ? (
        <EmptyState icon="pricetags-outline" title="No items" subtitle="Add services and parts to your catalog." testID="items-empty" />
      ) : (
        <FlatList
          testID="items-list"
          data={items}
          keyExtractor={(i) => i.id}
          contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
          renderItem={({ item }) => (
            <Pressable style={styles.row} testID={`item-${item.id}`} onPress={() => openEdit(item)}>
              <View style={{ flex: 1 }}>
                <Text style={styles.name}>{item.name}</Text>
                <Text style={styles.sub}>{item.category} · per {item.unit}</Text>
                {isAdmin && (
                  <View style={styles.adminCosts} testID={`item-wholesale-${item.id}`}>
                    <Text style={styles.costLabel}>W: {money(item.wholesale_price || 0)}</Text>
                    <Text style={styles.costLabel}>L: {money(item.labor_cost_default || 0)}</Text>
                  </View>
                )}
              </View>
              <Text style={styles.price}>{money(item.unit_price)}</Text>
              <Pressable onPress={() => remove(item.id)} hitSlop={8} testID={`delete-item-${item.id}`} style={{ marginLeft: spacing.md }}>
                <Ionicons name="trash-outline" size={18} color={colors.error} />
              </Pressable>
            </Pressable>
          )}
        />
      )}

      <Sheet visible={addOpen} onClose={() => setAddOpen(false)} title="New Item" testID="add-item-sheet">
        {[["name", "Name *", "default"], ["category", "Category", "default"], ["unit", "Unit (each, hour…)", "default"], ["unit_price", "Unit Price ($)", "decimal-pad"]].map(([k, lbl, kt]) => (
          <View key={k as string} style={{ marginBottom: spacing.sm }}>
            <Text style={styles.inputLabel}>{lbl}</Text>
            <TextInput
              testID={`item-${k}-input`}
              style={styles.input}
              value={(form as any)[k as string]}
              onChangeText={(v) => setForm((f) => ({ ...f, [k as string]: v }))}
              keyboardType={kt as any}
              placeholderTextColor={colors.muted}
            />
          </View>
        ))}
        <View style={{ height: spacing.sm }} />
        <PrimaryButton title="Add Item" onPress={create} testID="save-item-button" />
      </Sheet>

      {/* PB1: Edit item sheet with wholesale + labor */}
      <Sheet visible={!!editItem} onClose={() => setEditItem(null)} title={`Edit: ${editItem?.name || ""}`} testID="edit-item-sheet">
        <View style={{ marginBottom: spacing.sm }}>
          <Text style={styles.inputLabel}>Retail Price ($)</Text>
          <TextInput
            testID="edit-unit-price-input"
            style={styles.input}
            value={editForm.unit_price}
            onChangeText={(v) => setEditForm((f) => ({ ...f, unit_price: v }))}
            keyboardType="decimal-pad"
            placeholderTextColor={colors.muted}
          />
        </View>
        {isAdmin && (
          <>
            <View style={{ marginBottom: spacing.sm }}>
              <Text style={styles.inputLabel}>Wholesale Price ($)</Text>
              <TextInput
                testID="edit-wholesale-price-input"
                style={styles.input}
                value={editForm.wholesale_price}
                onChangeText={(v) => setEditForm((f) => ({ ...f, wholesale_price: v }))}
                keyboardType="decimal-pad"
                placeholderTextColor={colors.muted}
              />
            </View>
            <View style={{ marginBottom: spacing.sm }}>
              <Text style={styles.inputLabel}>Labor Cost ($)</Text>
              <TextInput
                testID="edit-labor-cost-input"
                style={styles.input}
                value={editForm.labor_cost_default}
                onChangeText={(v) => setEditForm((f) => ({ ...f, labor_cost_default: v }))}
                keyboardType="decimal-pad"
                placeholderTextColor={colors.muted}
              />
            </View>
          </>
        )}
        <View style={{ height: spacing.sm }} />
        <PrimaryButton title={saving ? "Saving…" : "Save"} onPress={saveEdit} disabled={saving} testID="save-edit-button" />
      </Sheet>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  row: { flexDirection: "row", alignItems: "center", backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.sm },
  name: { fontFamily: font.semibold, fontSize: fontSize.lg, color: colors.onSurface },
  sub: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
  price: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.brand },
  adminCosts: { flexDirection: "row", gap: spacing.md, marginTop: 4 },
  costLabel: { fontFamily: font.regular, fontSize: 11, color: colors.muted },
  inputLabel: { fontFamily: font.semibold, fontSize: 11, letterSpacing: 0.8, color: colors.onSurfaceSecondary, marginBottom: spacing.xs },
  input: { backgroundColor: colors.surfaceSecondary, borderWidth: 1.5, borderColor: colors.border, borderRadius: radius.md, paddingHorizontal: spacing.md, height: 48, fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}) },
});
