import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, FlatList, RefreshControl, Pressable, TextInput, Platform, Alert } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { writeCache, readCache } from "@/src/services/readCache";
import { colors, spacing, radius, font, fontSize, money } from "@/src/theme";
import { Loading, EmptyState, PrimaryButton, Sheet } from "@/src/components/ui";
import { Header, IconButton } from "@/src/components/widgets";
import { ImportExport } from "@/src/components/ImportExport";

// Phase 54f · Feb-2026 — supplier badge on pricebook rows (mobile parity).
const SUPPLIER_LABELS: Record<string, string> = {
  poolcorp:    "Pool360",
  siteone:     "SiteOne",
  ewing:       "Ewing",
  heritage:    "Heritage",
  epoolsupply: "ePoolSupply",
};

const SUPPLIER_BADGE_PALETTE: Record<string, { backgroundColor: string; borderColor: string }> = {
  poolcorp:    { backgroundColor: "#DBEAFE", borderColor: "#1E3A8A" },
  siteone:     { backgroundColor: "#DCFCE7", borderColor: "#166534" },
  ewing:       { backgroundColor: "#FEF3C7", borderColor: "#92400E" },
  heritage:    { backgroundColor: "#EDE9FE", borderColor: "#5B21B6" },
  epoolsupply: { backgroundColor: "#FCE7F3", borderColor: "#9D174D" },
};

function supplierBadgeColor(slug: string) {
  return SUPPLIER_BADGE_PALETTE[slug] || { backgroundColor: "#E5E7EB", borderColor: "#374151" };
}

// Phase 54f · Feb-2026 — mobile supplier filter (horizontal chip strip).
function SupplierFilterChips({
  value, onChange,
}: { value: string; onChange: (v: string) => void }) {
  const options = [
    { key: "all",    label: "All" },
    { key: "manual", label: "Manual" },
    ...Object.keys(SUPPLIER_LABELS).map((slug) =>
      ({ key: slug, label: SUPPLIER_LABELS[slug] })),
  ];
  return (
    <View style={styles.chipStrip} testID="pb-mobile-supplier-filter">
      {options.map((o) => (
        <Pressable
          key={o.key}
          onPress={() => onChange(o.key)}
          style={[styles.chip, value === o.key && styles.chipActive]}
          testID={`pb-mobile-supplier-chip-${o.key}`}
        >
          <Text style={[styles.chipText, value === o.key && styles.chipTextActive]}>
            {o.label}
          </Text>
        </Pressable>
      ))}
    </View>
  );
}

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
  // Phase 54f · Feb-2026 — supplier filter (mobile parity).
  const [supplierFilter, setSupplierFilter] = useState<string>("all");
  const filteredItems = items.filter((i) => {
    if (supplierFilter === "all") return true;
    if (supplierFilter === "manual") return !i.supplier_slug;
    return i.supplier_slug === supplierFilter;
  });

  const load = useCallback(async () => {
    try {
      const data = await api.get("/items");
      setItems(data);
      writeCache("pricebook:items", data).catch(() => {});
    } catch {
      const cached = await readCache<any[]>("pricebook:items");
      setItems(cached ?? []);
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
      {/* Phase 54f · Feb-2026 — supplier filter chip strip (mobile). */}
      <SupplierFilterChips value={supplierFilter} onChange={setSupplierFilter} />
      {loading ? (
        <Loading testID="items-loading" />
      ) : filteredItems.length === 0 ? (
        <EmptyState icon="pricetags-outline"
                    title={items.length === 0 ? "No items" : "No items match this supplier"}
                    subtitle={items.length === 0
                      ? "Add services and parts to your catalog."
                      : "Try a different supplier or 'All'."}
                    testID="items-empty" />
      ) : (
        <FlatList
          testID="items-list"
          data={filteredItems}
          keyExtractor={(i) => i.id}
          contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
          renderItem={({ item }) => (
            <Pressable style={styles.row} testID={`item-${item.id}`} onPress={() => openEdit(item)}>
              <View style={{ flex: 1 }}>
                <Text style={styles.name}>{item.name}</Text>
                <View style={styles.subRow}>
                  <Text style={styles.sub}>{item.category} · per {item.unit}</Text>
                  {item.supplier_slug ? (
                    <View style={[styles.supplierBadge, supplierBadgeColor(item.supplier_slug)]}
                          testID={`item-supplier-badge-${item.id}`}>
                      <Text style={styles.supplierBadgeText}>
                        {SUPPLIER_LABELS[item.supplier_slug] || item.supplier_slug}
                      </Text>
                    </View>
                  ) : (
                    <View style={[styles.supplierBadge, styles.supplierBadgeManual]}
                          testID={`item-supplier-badge-${item.id}`}>
                      <Text style={styles.supplierBadgeText}>Manual</Text>
                    </View>
                  )}
                </View>
                {isAdmin && (
                  <View style={styles.adminCosts} testID={`item-wholesale-${item.id}`}>
                    <Text style={styles.costLabel}>
                      Cost: {money(item.effective_cost ?? item.wholesale_price ?? 0)}
                      {Array.isArray(item.suppliers) && item.suppliers.length > 0
                        ? ` from ${item.suppliers.length} supplier${item.suppliers.length > 1 ? "s" : ""}`
                        : ""}
                    </Text>
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
  subRow: { flexDirection: "row", alignItems: "center", marginTop: 2, gap: 8, flexWrap: "wrap" },
  supplierBadge: { paddingHorizontal: 6, paddingVertical: 2, borderRadius: 6, borderWidth: 1 },
  supplierBadgeManual: { backgroundColor: "#E5E7EB", borderColor: "#374151" },
  supplierBadgeText: { fontFamily: font.regular, fontSize: 10, color: colors.onSurface },
  chipStrip: { flexDirection: "row", flexWrap: "wrap", gap: 6, paddingHorizontal: spacing.lg, paddingTop: spacing.sm, paddingBottom: spacing.xs },
  chip: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: 999, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
  chipActive: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  chipText: { fontFamily: font.regular, fontSize: 12, color: colors.onSurface },
  chipTextActive: { color: colors.onBrandPrimary, fontFamily: font.bold },
  price: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.brand },
  adminCosts: { flexDirection: "row", gap: spacing.md, marginTop: 4 },
  costLabel: { fontFamily: font.regular, fontSize: 11, color: colors.muted },
  inputLabel: { fontFamily: font.semibold, fontSize: 11, letterSpacing: 0.8, color: colors.onSurfaceSecondary, marginBottom: spacing.xs },
  input: { backgroundColor: colors.surfaceSecondary, borderWidth: 1.5, borderColor: colors.border, borderRadius: radius.md, paddingHorizontal: spacing.md, height: 48, fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}) },
});
