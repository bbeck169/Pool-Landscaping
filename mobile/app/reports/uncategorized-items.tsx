/**
 * TD-84 b2 · Uncategorized line items report (web
 * pages/reports/UncategorizedItemsReport.jsx, E3(b) scope).
 * GET /reports/uncategorized-items?range=&missing= · per-row assign
 * POST …/{invoice_id}/{idx}/assign · bulk POST …/bulk-assign (≤200/call).
 * Pickers: GET /income-categories + /service-categories ({items}).
 * NOT ported (TD-84-mobile-bulk-destructive): bulk hard-delete, CSV export.
 * Also deferred: custom date range, per-row Undo toast, "Mark done" dismiss.
 * Admin / super_admin only (every endpoint is _require_admin).
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { View, Text, StyleSheet, FlatList, Pressable, ScrollView, RefreshControl } from "react-native";
import { Redirect } from "expo-router";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { useToast } from "@/src/components/ToastProvider";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import { Loading } from "@/src/components/ui";
import AppTextInput from "@/src/components/ui/AppTextInput";
import { useBulkSelect, BulkCheckbox, BulkActionBar } from "@/src/components/bulk-select/BulkSelectToolkit";
import BusinessUnitPickerSheet from "@/src/components/dashboard/BusinessUnitPickerSheet";
import UncategorizedRow from "@/src/components/reports/UncategorizedRow";
import {
  RANGE_OPTIONS, MISSING_OPTIONS, rowKey, keyToItem, applyAssign, assignToast, chunk, bulkToast, assignPath, bodyField,
  type RangeKey, type MissingKey, type Taxonomy, type CategoryRef, type UncatRow,
} from "@/src/lib/uncategorized";

type Picker = { field: Taxonomy; row?: UncatRow } | null;
const activeCats = (r: any): CategoryRef[] => (r?.items || []).filter((c: any) => c?.id && c?.name && !c.is_archived);

export default function UncategorizedItemsScreen() {
  const { user } = useAuth();
  const { showToast } = useToast();
  const role = user?.role as string | undefined;
  const isAdmin = role === "admin" || role === "super_admin";
  const [range, setRange] = useState<RangeKey>("all");
  const [missing, setMissing] = useState<MissingKey>("either");
  const [customerQ, setCustomerQ] = useState("");
  const [rows, setRows] = useState<UncatRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [cats, setCats] = useState<Record<Taxonomy, CategoryRef[]>>({ income: [], service: [] });
  const [picker, setPicker] = useState<Picker>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [selectMode, setSelectMode] = useState(false);

  const visible = useMemo(() => {
    const q = customerQ.trim().toLowerCase();
    return q ? rows.filter((r) => (r.customer_name || "").toLowerCase().includes(q)) : rows;
  }, [rows, customerQ]);
  const visibleKeys = useMemo(() => visible.map(rowKey), [visible]);
  const bulk = useBulkSelect(visibleKeys);
  const { clear } = bulk;

  const load = useCallback(async () => {
    setError("");
    try {
      const r: any = await api.get(`/reports/uncategorized-items?range=${range}&missing=${missing}`);
      const items: UncatRow[] = Array.isArray(r?.items) ? r.items : [];
      setRows(items);
      setTotal(typeof r?.total === "number" ? r.total : items.length);
    } catch (e: any) {
      setError(e?.message || "Failed to load uncategorized items.");
      setRows([]); setTotal(0);
    } finally { setLoading(false); setRefreshing(false); clear(); }
  }, [range, missing, clear]);

  useEffect(() => { if (!isAdmin) return; setLoading(true); load(); }, [load, isAdmin]);
  useEffect(() => {
    if (!isAdmin) return;
    Promise.all([api.get("/income-categories").catch(() => null), api.get("/service-categories").catch(() => null)])
      .then(([i, s]) => setCats({ income: activeCats(i), service: activeCats(s) }));
  }, [isAdmin]);

  const assignOne = async (row: UncatRow, field: Taxonomy, cat: CategoryRef) => {
    const opKey = `${rowKey(row)}::${field}`;
    if (busy) return;
    setBusy(opKey);
    try {
      const res: any = await api.post(assignPath(row), { [bodyField(field)]: cat.id });
      const resolved = res?.[field === "income" ? "income_category" : "service_category"];
      const ref = { id: resolved?.id || cat.id, name: resolved?.name || cat.name };
      setRows((prev) => prev.map((r) => (rowKey(r) === rowKey(row) ? applyAssign(r, field, ref) : r)));
      showToast(assignToast(row, field, ref.name), "success");
    } catch (e: any) { showToast(e?.message || "Failed to assign category", "error"); }
    finally { setBusy(null); }
  };

  const assignBulk = async (field: Taxonomy, cat: CategoryRef) => {
    const keys = [...bulk.selected];
    if (!keys.length || busy) return;
    setBusy("bulk");
    let assigned = 0, failed = 0, name = cat.name;
    try {
      for (const part of chunk(keys)) {
        const res: any = await api.post("/reports/uncategorized-items/bulk-assign", { items: part.map(keyToItem), [bodyField(field)]: cat.id });
        assigned += Number(res?.assigned || 0); failed += Number(res?.failed || 0);
        name = res?.[field === "income" ? "income_category" : "service_category"]?.name || name;
      }
      const set = new Set(keys);
      setRows((prev) => prev.map((r) => (set.has(rowKey(r)) ? applyAssign(r, field, { id: cat.id, name }) : r)));
      bulk.clear(); setSelectMode(false);
      showToast(bulkToast(assigned, failed, field, name), failed ? "info" : "success");
    } catch (e: any) { showToast(e?.message || "Bulk assign failed", "error"); }
    finally { setBusy(null); }
  };

  const onPick = (cat: CategoryRef) => {
    const p = picker; setPicker(null);
    if (!p) return;
    if (p.row) assignOne(p.row, p.field, cat); else assignBulk(p.field, cat);
  };

  if (!isAdmin) return <Redirect href="/(app)" />;
  const exitSelect = () => { setSelectMode(false); bulk.clear(); };
  const pickerRowId = picker?.row ? (picker.field === "income" ? picker.row.income_category_id : picker.row.service_category_id) : undefined;

  return (
    <View style={s.root} testID="uncategorized-items-report">
      <Header
        title={selectMode ? `${bulk.count} selected` : "Uncategorized items"} back
        subtitle={loading ? undefined : `${visible.length} of ${total} line items`}
        right={
          <Pressable onPress={selectMode ? exitSelect : () => setSelectMode(true)} hitSlop={10} style={s.headerBtn} testID="uncat-select-toggle">
            <Text style={s.headerBtnText}>{selectMode ? "Cancel" : "Select"}</Text>
          </Pressable>
        }
      />
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.chips} style={{ flexGrow: 0 }} testID="uncategorized-filter-bar">
        {RANGE_OPTIONS.map((o) => (
          <Pressable key={o.key} onPress={() => setRange(o.key)} style={[s.chip, range === o.key && s.chipOn]} testID={`uncategorized-range-${o.key}`} accessibilityState={{ selected: range === o.key }}>
            <Text style={[s.chipText, range === o.key && s.chipTextOn]}>{o.label}</Text>
          </Pressable>
        ))}
      </ScrollView>
      <View style={s.segment} testID="uncategorized-missing-toggle">
        <Text style={s.segmentLabel}>Missing</Text>
        {MISSING_OPTIONS.map((o) => (
          <Pressable key={o.key} onPress={() => setMissing(o.key)} style={[s.seg, missing === o.key && s.segOn]} testID={`uncategorized-missing-${o.key}`} accessibilityState={{ selected: missing === o.key }}>
            <Text style={[s.segText, missing === o.key && s.chipTextOn]}>{o.label}</Text>
          </Pressable>
        ))}
      </View>
      <View style={s.searchRow}>
        {selectMode ? <BulkCheckbox checked={bulk.allSelected} indeterminate={bulk.indeterminate} onPress={bulk.toggleAll} testID="uncategorized-select-all" /> : null}
        <AppTextInput style={s.search} value={customerQ} onChangeText={setCustomerQ} placeholder="Filter by customer" placeholderTextColor={colors.muted} testID="uncategorized-customer-filter" />
      </View>
      {error ? <Text style={s.error} testID="uncategorized-error">{error}</Text> : null}
      {loading ? <Loading testID="uncategorized-loading" /> : (
        <FlatList
          data={visible} keyExtractor={rowKey} testID="uncategorized-list"
          contentContainerStyle={{ padding: spacing.lg, paddingTop: spacing.sm, paddingBottom: selectMode ? 120 : spacing["3xl"] }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
          ListEmptyComponent={error ? null : <Text style={s.empty} testID="uncategorized-empty-state">Nothing uncategorized for this filter.</Text>}
          renderItem={({ item }) => {
            const k = rowKey(item);
            return (
              <UncategorizedRow
                row={item} selectMode={selectMode} selected={bulk.selected.has(k)}
                busyField={busy?.startsWith(`${k}::`) ? (busy.slice(k.length + 2) as Taxonomy) : null}
                onToggle={() => bulk.toggleOne(k)}
                onLongPress={() => { if (!selectMode) setSelectMode(true); bulk.toggleOne(k); }}
                onAssign={(field) => setPicker({ field, row: item })}
              />
            );
          }}
        />
      )}
      {selectMode && bulk.count > 0 ? (
        <BulkActionBar count={bulk.count} onClear={bulk.clear} actions={[
          { key: "uncategorized-bulk-assign-income", label: "Set Income", tone: "primary", onPress: () => setPicker({ field: "income" }) },
          { key: "uncategorized-bulk-assign-service", label: "Set Service", tone: "primary", onPress: () => setPicker({ field: "service" }) },
        ]} />
      ) : null}
      <BusinessUnitPickerSheet
        visible={!!picker} categories={picker ? cats[picker.field] : []} selectedId={pickerRowId || undefined}
        title={picker?.field === "service" ? "Assign Service category" : "Assign Income category"}
        onSelect={onPick} onClose={() => setPicker(null)}
      />
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  headerBtn: { minHeight: 44, justifyContent: "center", paddingHorizontal: spacing.sm },
  headerBtnText: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.brand },
  chips: { gap: spacing.sm, paddingHorizontal: spacing.lg, paddingTop: spacing.md },
  chip: { minHeight: 36, justifyContent: "center", paddingHorizontal: spacing.md, borderRadius: radius.pill, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
  chipOn: { backgroundColor: colors.brand, borderColor: colors.brand },
  chipText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface },
  chipTextOn: { color: "#fff" },
  segment: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: spacing.lg, paddingTop: spacing.sm },
  segmentLabel: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.muted, marginRight: 2 },
  seg: { flex: 1, minHeight: 36, alignItems: "center", justifyContent: "center", borderRadius: radius.sm, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
  segOn: { backgroundColor: colors.brand, borderColor: colors.brand },
  segText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface },
  searchRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm, paddingHorizontal: spacing.lg, paddingTop: spacing.sm },
  search: { flex: 1, height: 44, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, paddingHorizontal: spacing.md, fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface },
  error: { marginHorizontal: spacing.lg, marginTop: spacing.sm, fontFamily: font.medium, fontSize: fontSize.sm, color: colors.error },
  empty: { textAlign: "center", padding: spacing.xl, fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
});
