import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, FlatList, RefreshControl, Pressable, Platform, Alert } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { Image } from "expo-image";
import * as ImagePicker from "expo-image-picker";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { colors, spacing, radius, font, fontSize, money, statusMeta } from "@/src/theme";
import { Loading, EmptyState, StatusChip, PrimaryButton, Sheet } from "@/src/components/ui";
import { Header, FilterRow, IconButton } from "@/src/components/widgets";
import { formatCustomerName } from "@/src/utils/formatCustomerName";
import AppTextInput from "@/src/components/ui/AppTextInput";

// Repair status meta
Object.assign(statusMeta, {
  open: { label: "Open", bg: "#FEE2E2", fg: "#DC2626" },
  diagnosing: { label: "Diagnosing", bg: "#FEF9C3", fg: "#A16207" },
  awaiting_parts: { label: "Awaiting Parts", bg: "#FFEDD5", fg: "#C2410C" },
  repaired: { label: "Repaired", bg: "#DCFCE7", fg: "#16A34A" },
});

const FILTERS = [
  { key: "all", label: "All" },
  { key: "open", label: "Open" },
  { key: "diagnosing", label: "Diagnosing" },
  { key: "awaiting_parts", label: "Awaiting Parts" },
  { key: "repaired", label: "Repaired" },
];
const STATUSES = ["open", "diagnosing", "awaiting_parts", "repaired"];
const EQUIPMENT = ["Pool Pump", "DE Filter", "Heater", "Salt Cell", "Automation", "Cleaner"];

export default function Equipment() {
  const { user } = useAuth();
  const isTech = user?.role === "technician";
  const [items, setItems] = useState<any[]>([]);
  const [customers, setCustomers] = useState<any[]>([]);
  const [techs, setTechs] = useState<any[]>([]);
  const [filter, setFilter] = useState("all");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [sel, setSel] = useState<any>(null);
  const [form, setForm] = useState<{ customer_id: string; equipment: string; issue: string; cost: string; photos: string[] }>({ customer_id: "", equipment: "Pool Pump", issue: "", cost: "", photos: [] });

  const load = useCallback(async (f: string) => {
    try {
      const q = f === "all" ? "" : `?status=${f}`;
      const [reps, custs, tks] = await Promise.all([
        api.get(`/repairs${q}`),
        api.get("/customers"),
        api.get("/technicians"),
      ]);
      setItems(reps);
      setCustomers(custs || []);
      setTechs(tks || []);
    } catch {
      setItems([]);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(filter); }, [filter, load]));

  const addPhoto = async () => {
    const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!perm.granted) {
      Alert.alert("Permission needed", "Allow photo access to attach repair photos.");
      return;
    }
    const res = await ImagePicker.launchImageLibraryAsync({ base64: true, quality: 0.5, allowsMultipleSelection: true, selectionLimit: 5 });
    if (res.canceled) return;
    const uris = res.assets.filter((a) => a.base64).map((a) => `data:image/jpeg;base64,${a.base64}`);
    setForm((f) => ({ ...f, photos: [...f.photos, ...uris].slice(0, 6) }));
  };

  const create = async () => {
    if (!form.customer_id || !form.issue.trim()) {
      Alert.alert("Missing info", "Pick a customer and describe the issue.");
      return;
    }
    await api.post("/repairs", { ...form, cost: parseFloat(form.cost) || 0 });
    setAddOpen(false);
    setForm({ customer_id: "", equipment: "Pool Pump", issue: "", cost: "", photos: [] });
    load(filter);
  };

  const setStatus = async (rid: string, status: string) => {
    await api.put(`/repairs/${rid}`, { status });
    setSel(null);
    load(filter);
  };

  const assignTech = async (rid: string, technician_id: string) => {
    await api.put(`/repairs/${rid}`, { technician_id });
    setSel((s: any) => (s ? { ...s, technician_id } : s));
    load(filter);
  };

  return (
    <View style={styles.root}>
      <Header title="Equipment Repair" back right={<IconButton icon="add" onPress={() => setAddOpen(true)} testID="add-repair-button" />} />
      <FilterRow options={FILTERS} value={filter} onChange={setFilter} testID="repairs-filter" />
      {loading ? (
        <Loading testID="repairs-loading" />
      ) : items.length === 0 ? (
        <EmptyState icon="build-outline" title="No repair tickets" subtitle="Log an equipment issue to track it." testID="repairs-empty" />
      ) : (
        <FlatList
          testID="repairs-list"
          data={items}
          keyExtractor={(i) => i.id}
          contentContainerStyle={{ padding: spacing.lg, paddingTop: spacing.sm, paddingBottom: spacing["3xl"] }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(filter); }} />}
          renderItem={({ item }) => (
            <Pressable style={styles.card} onPress={() => setSel(item)} testID={`repair-${item.id}`}>
              <View style={styles.cardTop}>
                <View style={styles.eqIcon}>
                  <Ionicons name="hardware-chip-outline" size={18} color={colors.brand} />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.equipment}>{item.equipment}</Text>
                  <Text style={styles.customer}>{formatCustomerName(item)}</Text>
                </View>
                <StatusChip status={item.status} />
              </View>
              <Text style={styles.issue} numberOfLines={2}>{item.issue}</Text>
              <View style={styles.cardFooter}>
                <View style={{ flexDirection: "row", alignItems: "center", gap: 5 }}>
                  <Ionicons name="person-outline" size={14} color={colors.muted} />
                  <Text style={styles.tech}>{item.technician_name || "Unassigned"}</Text>
                </View>
                {item.cost ? <Text style={styles.cost}>{money(item.cost)}</Text> : null}
              </View>
            </Pressable>
          )}
        />
      )}

      {/* Add repair */}
      <Sheet visible={addOpen} onClose={() => setAddOpen(false)} title="New Repair Ticket" testID="add-repair-sheet">
        <Text style={styles.inputLabel}>CUSTOMER</Text>
        <View style={styles.pickerWrap}>
          {customers.map((c) => (
            <Pressable key={c.id} style={[styles.pickChip, form.customer_id === c.id && styles.pickChipActive]} onPress={() => setForm((f) => ({ ...f, customer_id: c.id }))} testID={`repair-customer-${c.id}`}>
              <Text style={[styles.pickChipText, form.customer_id === c.id && { color: "#fff" }]}>{c.name}</Text>
            </Pressable>
          ))}
        </View>

        <Text style={[styles.inputLabel, { marginTop: spacing.md }]}>EQUIPMENT</Text>
        <View style={styles.pickerWrap}>
          {EQUIPMENT.map((e) => (
            <Pressable key={e} style={[styles.pickChip, form.equipment === e && styles.pickChipActive]} onPress={() => setForm((f) => ({ ...f, equipment: e }))} testID={`repair-eq-${e}`}>
              <Text style={[styles.pickChipText, form.equipment === e && { color: "#fff" }]}>{e}</Text>
            </Pressable>
          ))}
        </View>

        <Text style={[styles.inputLabel, { marginTop: spacing.md }]}>ISSUE</Text>
        <AppTextInput style={[styles.input, { height: 72, paddingTop: spacing.sm }]} value={form.issue} onChangeText={(v) => setForm((f) => ({ ...f, issue: v }))} placeholder="Describe the problem…" placeholderTextColor={colors.muted} multiline testID="repair-issue-input" />

        {!isTech ? (
          <>
            <Text style={[styles.inputLabel, { marginTop: spacing.md }]}>ESTIMATED COST ($)</Text>
            <AppTextInput style={styles.input} value={form.cost} onChangeText={(v) => setForm((f) => ({ ...f, cost: v }))} keyboardType="decimal-pad" placeholder="0.00" placeholderTextColor={colors.muted} testID="repair-cost-input" />
          </>
        ) : null}

        <Text style={[styles.inputLabel, { marginTop: spacing.md }]}>PHOTOS</Text>
        <View style={styles.photoRow}>
          {form.photos.map((p, i) => (
            <View key={i} style={styles.photoThumb} testID={`repair-form-photo-${i}`}>
              <Image source={{ uri: p }} style={styles.photoImg} contentFit="cover" />
              <Pressable style={styles.photoRemove} onPress={() => setForm((f) => ({ ...f, photos: f.photos.filter((_, idx) => idx !== i) }))} hitSlop={6} testID={`repair-form-photo-remove-${i}`}>
                <Ionicons name="close" size={13} color="#fff" />
              </Pressable>
            </View>
          ))}
          {form.photos.length < 6 ? (
            <Pressable style={styles.photoAdd} onPress={addPhoto} testID="repair-add-photo">
              <Ionicons name="camera-outline" size={22} color={colors.brand} />
              <Text style={styles.photoAddText}>Add</Text>
            </Pressable>
          ) : null}
        </View>

        <View style={{ height: spacing.md }} />
        <PrimaryButton title="Create Ticket" onPress={create} testID="save-repair-button" />
      </Sheet>

      {/* Detail / update */}
      <Sheet visible={!!sel} onClose={() => setSel(null)} title={sel?.equipment} testID="repair-detail-sheet">
        {sel ? (
          <>
            <Text style={styles.customer}>{formatCustomerName(sel)}</Text>
            <Text style={styles.detailIssue}>{sel.issue}</Text>
            {sel.cost ? <Text style={styles.detailCost}>Cost: {money(sel.cost)}</Text> : null}
            {sel.photos?.length ? (
              <View style={styles.photoRow}>
                {sel.photos.map((p: string, i: number) => (
                  <Image key={i} source={{ uri: p }} style={styles.detailPhoto} contentFit="cover" testID={`repair-detail-photo-${i}`} />
                ))}
              </View>
            ) : null}

            <Text style={[styles.inputLabel, { marginTop: spacing.md }]}>STATUS</Text>
            <View style={styles.pickerWrap}>
              {STATUSES.map((s) => (
                <Pressable key={s} style={[styles.pickChip, sel.status === s && styles.pickChipActive]} onPress={() => setStatus(sel.id, s)} testID={`repair-status-${s}`}>
                  <Text style={[styles.pickChipText, sel.status === s && { color: "#fff" }]}>{statusMeta[s]?.label || s}</Text>
                </Pressable>
              ))}
            </View>

            <Text style={[styles.inputLabel, { marginTop: spacing.md }]}>ASSIGN TECHNICIAN</Text>
            <View style={styles.pickerWrap}>
              {techs.map((t) => (
                <Pressable key={t.id} style={[styles.pickChip, sel.technician_id === t.id && styles.pickChipActive]} onPress={() => assignTech(sel.id, t.id)} testID={`repair-tech-${t.id}`} disabled={isTech}>
                  <Text style={[styles.pickChipText, sel.technician_id === t.id && { color: "#fff" }]}>{t.name}</Text>
                </Pressable>
              ))}
            </View>
          </>
        ) : null}
      </Sheet>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  card: { backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.lg, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.md },
  cardTop: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  eqIcon: { width: 40, height: 40, borderRadius: radius.md, backgroundColor: colors.brandTertiary, alignItems: "center", justifyContent: "center" },
  equipment: { fontFamily: font.semibold, fontSize: fontSize.lg, color: colors.onSurface },
  customer: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
  issue: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurfaceSecondary, marginTop: spacing.sm },
  cardFooter: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", borderTopWidth: 1, borderTopColor: colors.divider, paddingTop: spacing.sm, marginTop: spacing.sm },
  tech: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
  cost: { fontFamily: font.bold, fontSize: fontSize.base, color: colors.brand },
  detailIssue: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, marginTop: spacing.sm },
  detailCost: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.brand, marginTop: spacing.sm },
  photoRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm, marginTop: spacing.sm },
  photoThumb: { width: 72, height: 72, borderRadius: radius.md, overflow: "hidden", backgroundColor: colors.surfaceTertiary },
  photoImg: { width: "100%", height: "100%" },
  photoRemove: { position: "absolute", top: 2, right: 2, width: 20, height: 20, borderRadius: 10, backgroundColor: "rgba(0,0,0,0.6)", alignItems: "center", justifyContent: "center" },
  photoAdd: { width: 72, height: 72, borderRadius: radius.md, borderWidth: 1.5, borderStyle: "dashed", borderColor: colors.brand, alignItems: "center", justifyContent: "center", gap: 2 },
  photoAddText: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.brand },
  detailPhoto: { width: 88, height: 88, borderRadius: radius.md, backgroundColor: colors.surfaceTertiary },
  inputLabel: { fontFamily: font.semibold, fontSize: 11, letterSpacing: 0.8, color: colors.onSurfaceSecondary, marginBottom: spacing.xs },
  input: { backgroundColor: colors.surfaceSecondary, borderWidth: 1.5, borderColor: colors.border, borderRadius: radius.md, paddingHorizontal: spacing.md, height: 48, fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}) },
  pickerWrap: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  pickChip: { paddingHorizontal: spacing.md, height: 36, borderRadius: radius.pill, alignItems: "center", justifyContent: "center", backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border },
  pickChipActive: { backgroundColor: colors.brand, borderColor: colors.brand },
  pickChipText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
});
