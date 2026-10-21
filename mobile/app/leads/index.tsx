import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, FlatList, RefreshControl, Pressable, Platform, Alert } from "react-native";
import { useFocusEffect, useRouter } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize, money, statusMeta } from "@/src/theme";
import { Loading, EmptyState, StatusChip, PrimaryButton, Sheet } from "@/src/components/ui";
import { Header, FilterRow, IconButton } from "@/src/components/widgets";
import { useBulkSelect, BulkCheckbox, BulkActionBar } from "@/src/components/bulk-select/BulkSelectToolkit";
import AppTextInput from "@/src/components/ui/AppTextInput";
import AddressAutocomplete, { type AddressSelection } from "@/src/components/common/AddressAutocomplete";
import { PhoneLink } from "@/src/components/customer";
import { useToast } from "@/src/components/ToastProvider";

const FILTERS = [
  { key: "all", label: "All" },
  { key: "new", label: "New" },
  { key: "contacted", label: "Contacted" },
  { key: "quoted", label: "Quoted" },
  { key: "closed_won", label: "Closed – Won" },
  { key: "closed_lost", label: "Closed – Lost" },
];
const STATUSES = ["new", "contacted", "quoted", "closed_won", "closed_lost"];

// Phase 34 · Task CC: 5 canonical snake_case lead statuses
Object.assign(statusMeta, {
  "new": { label: "New", bg: "#DBEAFE", fg: "#1E3A8A" },
  "contacted": { label: "Contacted", bg: "#FEF3C7", fg: "#854D0E" },
  "quoted": { label: "Quoted", bg: "#E0E7FF", fg: "#3730A3" },
  "closed_won": { label: "Closed – Won", bg: "#DCFCE7", fg: "#166534" },
  "closed_lost": { label: "Closed – Lost", bg: "#FEE2E2", fg: "#991B1B" },
  // Legacy backwards-compat
  "New": { label: "New", bg: "#DBEAFE", fg: "#1E3A8A" },
  "Contacted": { label: "Contacted", bg: "#FEF3C7", fg: "#854D0E" },
  "Quoted": { label: "Quoted", bg: "#E0E7FF", fg: "#3730A3" },
  "Closed Won": { label: "Closed – Won", bg: "#DCFCE7", fg: "#166534" },
  "Closed Lost": { label: "Closed – Lost", bg: "#FEE2E2", fg: "#991B1B" },
  "qualified": { label: "Quoted", bg: "#E0E7FF", fg: "#3730A3" },
  "won": { label: "Closed – Won", bg: "#DCFCE7", fg: "#166534" },
  "lost": { label: "Closed – Lost", bg: "#FEE2E2", fg: "#991B1B" },
  "On Hold": { label: "On Hold", bg: "#F1F5F9", fg: "#475569" },
  "Archived": { label: "Archived", bg: "#E5E7EB", fg: "#374151" },
});

export default function Leads() {
  const router = useRouter();
  // TD-96-mobile-bulk-toast · bulkChangeStatus called showToast without this
  // (since 4a8d04429) → ReferenceError → false "Error" alert after success.
  const { showToast } = useToast();
  const [items, setItems] = useState<any[]>([]);
  const [filter, setFilter] = useState("all");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [form, setForm] = useState({ name: "", phone: "", email: "", source: "Website", notes: "", est_value: "", address: "" });
  const [addressGeo, setAddressGeo] = useState<{ lat: number; lng: number } | null>(null);

  // Convert-to-job/quote state
  const [selectMode, setSelectMode] = useState(false);
  const [bulkStatusTarget, setBulkStatusTarget] = useState("");

  const visibleIds = items.map((i: any) => i.id);
  const bulk = useBulkSelect(visibleIds);
  const exitSelectMode = () => { setSelectMode(false); bulk.clear(); };

  const bulkChangeStatus = async (status: string) => {
    if (!bulk.count) return;
    try {
      await api.post("/leads/bulk-status", { ids: [...bulk.selected], status });
      showToast(`${bulk.count} lead${bulk.count !== 1 ? "s" : ""} set to ${status.replace("_", " ")}.`);
      exitSelectMode();
      load(filter);
    } catch (e: any) {
      Alert.alert("Error", e?.message || "Update failed");
    }
  };

  const load = useCallback(async (f: string) => {
    try {
      const q = f === "all" ? "?include_archived=1&page_size=200" : `?status=${encodeURIComponent(f)}&page_size=200`;
      const res = await api.get(`/leads${q}`);
      // Phase 8: API returns {rows, total, page, page_size}
      const arr = Array.isArray(res) ? res : (res?.rows || res?.leads || []);
      setItems(arr);
    } catch {
      setItems([]);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(filter); }, [filter, load]));

  const create = async () => {
    if (!form.name.trim()) return;
    await api.post("/leads", {
      ...form,
      est_value: parseFloat(form.est_value) || 0,
      lat: addressGeo?.lat ?? null,
      lng: addressGeo?.lng ?? null,
      latitude: addressGeo?.lat ?? null,
      longitude: addressGeo?.lng ?? null,
    });
    setAddOpen(false);
    setForm({ name: "", phone: "", email: "", source: "Website", notes: "", est_value: "", address: "" });
    setAddressGeo(null);
    load(filter);
  };


  return (
    <View style={styles.root}>
      <Header title="Leads" back right={<IconButton icon="add" onPress={() => setAddOpen(true)} testID="add-lead-button" />} />
      <FilterRow options={FILTERS} value={filter} onChange={setFilter} testID="leads-filter" />
      {loading ? (
        <Loading testID="leads-loading" />
      ) : items.length === 0 ? (
        <EmptyState icon="magnet-outline" title="No leads" subtitle="Add a lead to start your pipeline." testID="leads-empty" />
      ) : (
        <FlatList
          testID="leads-list"
          data={items}
          keyExtractor={(i) => i.id}
          contentContainerStyle={{ padding: spacing.lg, paddingTop: spacing.sm, paddingBottom: spacing["3xl"] }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(filter); }} />}
          renderItem={({ item }) => (
            <Pressable
              style={[styles.card, bulk.selected.has(item.id) && { borderColor: colors.brand, backgroundColor: colors.brandTertiary }]}
              onPress={() => selectMode ? bulk.toggleOne(item.id) : router.push(`/leads/${item.id}`)}
              onLongPress={() => { if (!selectMode) { setSelectMode(true); bulk.toggleOne(item.id); } }}
              testID={`lead-${item.id}`}
            >
              {selectMode ? <BulkCheckbox checked={bulk.selected.has(item.id)} onPress={() => bulk.toggleOne(item.id)} /> : null}
              <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
                <Text style={styles.name}>{item.name}</Text>
                <StatusChip status={item.status} />
              </View>
              <Text style={styles.sub}>
                {item.source} · {item.phone ? (
                  <PhoneLink phone={item.phone} style={styles.sub} showIcon={false} testID={`lead-phone-${item.id}`}>{item.phone}</PhoneLink>
                ) : (
                  <Text>{item.email || "—"}</Text>
                )}
              </Text>
              {item.est_value ? <Text style={styles.value}>Est. {money(item.est_value)}</Text> : null}
            </Pressable>
          )}
        />
      )}

      <Sheet visible={addOpen} onClose={() => setAddOpen(false)} title="New Lead" testID="add-lead-sheet">
        {[["name", "Name *", "default"], ["phone", "Phone", "phone-pad"], ["email", "Email", "email-address"], ["source", "Source", "default"], ["est_value", "Estimated Value ($)", "decimal-pad"], ["notes", "Notes", "default"]].map(([k, lbl, kt]) => (
          <View key={k as string} style={{ marginBottom: spacing.sm }}>
            <Text style={styles.inputLabel}>{lbl}</Text>
            <AppTextInput
              testID={`lead-${k}-input`}
              style={styles.input}
              value={(form as any)[k as string]}
              onChangeText={(v) => setForm((f) => ({ ...f, [k as string]: v }))}
              keyboardType={kt as any}
              placeholderTextColor={colors.muted}
            />
          </View>
        ))}
        <View style={{ marginBottom: spacing.sm }}>
          <Text style={styles.inputLabel}>Address</Text>
          <AddressAutocomplete
            value={form.address}
            onChange={(sel: AddressSelection) => {
              setForm((f) => ({ ...f, address: sel.formatted || "" }));
              setAddressGeo(sel.latitude != null && sel.longitude != null ? { lat: sel.latitude, lng: sel.longitude } : null);
            }}
            testID="newlead-address"
          />
        </View>
        <View style={{ height: spacing.sm }} />
        <PrimaryButton title="Add Lead" onPress={create} testID="save-lead-button" />
      </Sheet>

      <BulkActionBar
        count={bulk.count}
        onClear={exitSelectMode}
        actions={
          STATUSES.map((s) => ({
            key: `bulk-status-${s}`,
            label: s.replace("_", " ").replace(/\b\w/g, (c) => c.toUpperCase()),
            tone: s === "closed_lost" ? "danger" as const : "default" as const,
            onPress: () => bulkChangeStatus(s),
          }))
        }
      />
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  card: { backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.lg, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.md, gap: 4 },
  name: { fontFamily: font.semibold, fontSize: fontSize.lg, color: colors.onSurface },
  sub: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  value: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.brand },
  inputLabel: { fontFamily: font.semibold, fontSize: 11, letterSpacing: 0.8, color: colors.onSurfaceSecondary, marginBottom: spacing.xs },
  input: { backgroundColor: colors.surfaceSecondary, borderWidth: 1.5, borderColor: colors.border, borderRadius: radius.md, paddingHorizontal: spacing.md, height: 48, fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}) },
});
