/**
 * Phase 41.5c · Feb-2026 — Mobile Chemical Products admin screen.
 *
 * Native parity for the Products tab of the web
 * ``/admin/chemicals`` page (``frontend/src/pages/settings/
 * ChemicalsPage.jsx``). Endpoints reused verbatim:
 *   • GET    /api/chemical-products?q=&active=true
 *   • POST   /api/chemical-products
 *   • PATCH  /api/chemical-products/{slug}
 *   • DELETE /api/chemical-products/{slug}
 *
 * Role gate: admin / super_admin (mirrors the web ``<AdminOnly>``).
 *
 * The web page also has a Profitability tab (chart + KPIs). That
 * surface is deferred — its recharts BarChart doesn't have a mobile-
 * appropriate rendering path in scope for this ticket and is
 * explicitly labelled a non-goal.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, RefreshControl,
  TouchableOpacity, ActivityIndicator, Alert, Modal, Switch } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import AppTextInput from "@/src/components/ui/AppTextInput";
import { useToast } from "@/src/components/ToastProvider";

type ChemicalProduct = {
  id?: string;
  slug?: string;
  name: string;
  sku?: string | null;
  unit: string;
  unit_cost_cents: number;
  active: boolean;
};

const EMPTY: ChemicalProduct = {
  name: "", sku: "", unit: "lb", unit_cost_cents: 0, active: true,
};

const centsToDollars = (c: number) => `$${((c || 0) / 100).toFixed(2)}`;

export default function ChemicalProductsScreen() {
  const { showToast } = useToast(); // TD-96-mobile-toast-sweep (undefined since 4a8d04429)
  const { user } = useAuth();
  // Mirror the web ``<AdminOnly>`` route guard.
  const isAdmin = user?.role === "admin" || (user?.role as any) === "super_admin";

  const [rows, setRows] = useState<ChemicalProduct[]>([]);
  const [q, setQ] = useState("");
  const [showInactive, setShowInactive] = useState(false);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [editing, setEditing] = useState<ChemicalProduct | null>(null);
  const [costCentsDraft, setCostCentsDraft] = useState("0");
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    if (!isAdmin) return;
    try {
      const qs = new URLSearchParams();
      if (q) qs.set("q", q);
      if (!showInactive) qs.set("active", "true");
      const body = await api.get(`/chemical-products?${qs.toString()}`);
      setRows(body?.products || []);
    } catch {
      setRows([]);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [isAdmin, q, showInactive]);

  // Initial + on-filter-change fetch. Search on Enter/Search button.
  useEffect(() => { load(); }, [showInactive]); // eslint-disable-line react-hooks/exhaustive-deps

  const openNew = () => {
    setEditing({ ...EMPTY });
    setCostCentsDraft("0");
  };
  const openEdit = (p: ChemicalProduct) => {
    setEditing({ ...p });
    setCostCentsDraft(String(p.unit_cost_cents ?? 0));
  };
  const closeEdit = () => { setEditing(null); setCostCentsDraft("0"); };

  const save = async () => {
    if (!editing) return;
    if (!editing.name || !editing.unit) {
      Alert.alert("Missing field", "Name and unit are required.");
      return;
    }
    setSaving(true);
    const payload = {
      name: editing.name,
      sku: editing.sku || "",
      unit: editing.unit,
      unit_cost_cents: parseInt(costCentsDraft, 10) || 0,
      active: !!editing.active,
    };
    try {
      if (editing.slug) {
        await api.patch(`/chemical-products/${editing.slug}`, payload);
        showToast("Product updated.");
      } else {
        await api.post("/chemical-products", payload);
        showToast("Product created.");
      }
      closeEdit();
      await load();
    } catch (e: any) {
      Alert.alert("Error", e?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const deactivate = (p: ChemicalProduct) => {
    if (!p.slug) return;
    Alert.alert(
      "Deactivate?",
      `Deactivate "${p.name}"? Historical costs are preserved.`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Deactivate", style: "destructive",
          onPress: async () => {
            try {
              await api.del(`/chemical-products/${p.slug}`);
              await load();
            } catch (e: any) {
              Alert.alert("Error", e?.message || "Deactivate failed");
            }
          },
        },
      ],
    );
  };

  if (!isAdmin) {
    return (
      <View style={s.root} testID="chemicals-admin-role-gate">
        <Header title="Chemical Products" back />
        <View style={s.center}>
          <Ionicons name="lock-closed" size={32} color={colors.muted} />
          <Text style={s.centerText}>Admin only</Text>
        </View>
      </View>
    );
  }

  return (
    <View style={s.root} testID="chemicals-admin-screen">
      <Header title="Chemical Products" subtitle="Catalog + unit costs" back />

      <View style={s.toolbar}>
        <AppTextInput
          testID="chem-product-search"
          style={s.search}
          value={q}
          onChangeText={setQ}
          onSubmitEditing={load}
          placeholder="Search name / SKU / slug"
          placeholderTextColor={colors.muted}
          autoCapitalize="none"
          autoCorrect={false}
          returnKeyType="search"
        />
        <TouchableOpacity onPress={load} style={s.searchBtn}
                          testID="chem-product-search-btn">
          <Ionicons name="search" size={16} color={colors.onSurface} />
        </TouchableOpacity>
        <TouchableOpacity onPress={openNew} style={s.newBtn}
                          testID="chem-product-new">
          <Ionicons name="add" size={18} color="#fff" />
          <Text style={s.newBtnText}>New</Text>
        </TouchableOpacity>
      </View>

      <View style={s.filterRow}>
        <Text style={s.filterLabel}>Show inactive</Text>
        <Switch
          value={showInactive}
          onValueChange={setShowInactive}
          testID="chem-product-show-inactive"
        />
      </View>

      {loading ? (
        <View style={s.center}>
          <ActivityIndicator size="large" color={colors.brand}
                             testID="chemicals-admin-loading" />
        </View>
      ) : (
        <ScrollView
          testID="chemicals-admin-list"
          contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}
          refreshControl={<RefreshControl refreshing={refreshing}
                              onRefresh={() => { setRefreshing(true); load(); }} />}
        >
          {rows.length === 0 ? (
            <View style={s.emptyCard} testID="chemicals-admin-empty">
              <Text style={s.emptyText}>No products yet.</Text>
            </View>
          ) : null}

          {rows.map((p) => (
            <TouchableOpacity
              key={p.slug || p.id}
              activeOpacity={0.7}
              style={s.card}
              onPress={() => openEdit(p)}
              testID={`chem-product-row-${p.slug}`}
            >
              <View style={s.cardTop}>
                <Text style={s.cardTitle}>{p.name}</Text>
                <View style={[s.pill,
                              { backgroundColor: p.active ? "#DCFCE7" : colors.surfaceTertiary }]}>
                  <Text style={[s.pillText,
                                { color: p.active ? "#166534" : colors.onSurfaceSecondary }]}
                        testID={`chem-product-status-${p.slug}`}>
                    {p.active ? "active" : "inactive"}
                  </Text>
                </View>
              </View>
              <View style={s.cardMeta}>
                <Text style={s.cardMetaLabel}>SKU</Text>
                <Text style={s.cardMetaValue}>{p.sku || "—"}</Text>
              </View>
              <View style={s.cardMeta}>
                <Text style={s.cardMetaLabel}>Unit cost</Text>
                <Text style={s.cardMetaValue}
                      testID={`chem-product-cost-${p.slug}`}>
                  {centsToDollars(p.unit_cost_cents)} / {p.unit}
                </Text>
              </View>
              {p.active ? (
                <TouchableOpacity onPress={() => deactivate(p)}
                                  style={s.deactivateBtn}
                                  testID={`chem-product-deactivate-${p.slug}`}>
                  <Text style={s.deactivateText}>Deactivate</Text>
                </TouchableOpacity>
              ) : null}
            </TouchableOpacity>
          ))}
        </ScrollView>
      )}

      <Modal
        visible={editing !== null}
        transparent
        animationType="fade"
        onRequestClose={closeEdit}
      >
        <View style={s.modalBackdrop}>
          <View style={s.modalCard} testID="chem-product-modal">
            <Text style={s.modalTitle}>
              {editing?.slug ? "Edit product" : "New product"}
            </Text>

            <Text style={s.label}>Name *</Text>
            <AppTextInput
              testID="chem-product-name"
              style={s.input}
              value={editing?.name || ""}
              onChangeText={(v) => setEditing((e) => (e ? { ...e, name: v } : e))}
              placeholder="Chlorine tablet 3-inch"
              placeholderTextColor={colors.muted}
            />

            <Text style={s.label}>SKU</Text>
            <AppTextInput
              testID="chem-product-sku"
              style={s.input}
              value={editing?.sku || ""}
              onChangeText={(v) => setEditing((e) => (e ? { ...e, sku: v } : e))}
              placeholder="optional"
              placeholderTextColor={colors.muted}
              autoCapitalize="none"
            />

            <Text style={s.label}>Unit *</Text>
            <AppTextInput
              testID="chem-product-unit"
              style={s.input}
              value={editing?.unit || ""}
              onChangeText={(v) => setEditing((e) => (e ? { ...e, unit: v } : e))}
              placeholder="lb, gal, oz"
              placeholderTextColor={colors.muted}
              autoCapitalize="none"
              autoCorrect={false}
            />

            <Text style={s.label}>Unit cost (cents)</Text>
            <AppTextInput
              testID="chem-product-cost"
              style={s.input}
              value={costCentsDraft}
              onChangeText={setCostCentsDraft}
              keyboardType="number-pad"
              placeholder="0"
              placeholderTextColor={colors.muted}
            />
            <Text style={s.hint}>
              Storage in cents. {centsToDollars(parseInt(costCentsDraft, 10) || 0)}
              {" "}per {editing?.unit || "unit"}.
            </Text>

            <View style={s.switchRow}>
              <Text style={s.label}>Active</Text>
              <Switch
                testID="chem-product-active"
                value={!!editing?.active}
                onValueChange={(v) => setEditing((e) => (e ? { ...e, active: v } : e))}
              />
            </View>

            <View style={s.modalFooter}>
              <TouchableOpacity onPress={closeEdit}
                                style={[s.modalBtn, s.modalBtnGhost]}
                                testID="chem-product-cancel">
                <Text style={s.modalBtnGhostText}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity
                onPress={save}
                disabled={saving}
                style={[s.modalBtn, s.modalBtnPrimary, saving && { opacity: 0.6 }]}
                testID="chem-product-save"
              >
                <Text style={s.modalBtnPrimaryText}>
                  {saving ? "Saving\u2026" : "Save"}
                </Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: spacing.md },
  centerText: { fontFamily: font.medium, fontSize: fontSize.lg, color: colors.muted },

  toolbar: { flexDirection: "row", gap: spacing.sm,
             paddingHorizontal: spacing.lg, paddingTop: spacing.md,
             alignItems: "center" },
  search: { flex: 1, backgroundColor: colors.surface,
            borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
            paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
            fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface },
  searchBtn: { padding: 10, backgroundColor: colors.surface,
               borderWidth: 1, borderColor: colors.border, borderRadius: radius.md },
  newBtn: { flexDirection: "row", alignItems: "center", gap: 4,
            backgroundColor: colors.brand, paddingHorizontal: spacing.md,
            paddingVertical: 10, borderRadius: radius.md },
  newBtnText: { fontFamily: font.bold, color: "#fff", fontSize: fontSize.base },

  filterRow: { flexDirection: "row", alignItems: "center",
               justifyContent: "space-between",
               paddingHorizontal: spacing.lg, paddingVertical: spacing.sm },
  filterLabel: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },

  emptyCard: {
    backgroundColor: colors.surface, borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border,
    padding: spacing.lg, alignItems: "center",
  },
  emptyText: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted },

  card: { backgroundColor: colors.surface, borderRadius: radius.md,
          borderWidth: 1, borderColor: colors.border,
          padding: spacing.md, marginBottom: spacing.md },
  cardTop: { flexDirection: "row", justifyContent: "space-between",
             alignItems: "center" },
  cardTitle: { fontFamily: font.bold, fontSize: fontSize.base,
               color: colors.onSurface, flex: 1, paddingRight: 8 },
  pill: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 999 },
  pillText: { fontFamily: font.bold, fontSize: 10, textTransform: "uppercase",
              letterSpacing: 0.5 },
  cardMeta: { flexDirection: "row", justifyContent: "space-between", marginTop: 6 },
  cardMetaLabel: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  cardMetaValue: { fontFamily: font.bold, fontSize: fontSize.sm, color: colors.onSurface },
  deactivateBtn: { marginTop: spacing.sm, alignSelf: "flex-start",
                   borderWidth: 1, borderColor: colors.border,
                   borderRadius: radius.sm, paddingHorizontal: 10, paddingVertical: 5 },
  deactivateText: { fontFamily: font.bold, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },

  modalBackdrop: { flex: 1, backgroundColor: "rgba(15,23,42,0.55)",
                   alignItems: "center", justifyContent: "center", padding: spacing.lg },
  modalCard: { width: "100%", maxWidth: 480,
               backgroundColor: colors.surface, borderRadius: radius.lg,
               padding: spacing.lg },
  modalTitle: { fontFamily: font.bold, fontSize: fontSize.lg,
                color: colors.onSurface, marginBottom: spacing.md },
  label: { fontFamily: font.bold, fontSize: 11, textTransform: "uppercase",
           letterSpacing: 0.8, color: colors.muted,
           marginTop: spacing.sm, marginBottom: spacing.xs },
  input: { backgroundColor: colors.surfaceSecondary,
           borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
           paddingHorizontal: spacing.md, paddingVertical: spacing.md,
           fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface },
  hint: { fontFamily: font.regular, fontSize: fontSize.sm,
          color: colors.muted, marginTop: spacing.xs },
  switchRow: { flexDirection: "row", justifyContent: "space-between",
               alignItems: "center", marginTop: spacing.md },
  modalFooter: { flexDirection: "row", justifyContent: "flex-end",
                 gap: spacing.sm, marginTop: spacing.lg },
  modalBtn: { paddingHorizontal: spacing.md, paddingVertical: 10,
              borderRadius: radius.md },
  modalBtnGhost: { borderWidth: 1, borderColor: colors.border,
                   backgroundColor: colors.surface },
  modalBtnGhostText: { fontFamily: font.bold, fontSize: fontSize.base,
                       color: colors.onSurface },
  modalBtnPrimary: { backgroundColor: colors.brand },
  modalBtnPrimaryText: { fontFamily: font.bold, fontSize: fontSize.base, color: "#fff" },
});
