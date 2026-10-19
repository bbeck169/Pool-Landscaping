/**
 * Dashboard parity · mobile mirror of web `pages/admin/properties/
 * PropertiesListPage.jsx` (`/properties`). Deep-link target of the
 * Active Accounts / Pool / Landscaping / Both Service Customers KPI tiles.
 *
 * Params (same as web): `?is_active=true|false|all` (default true),
 * `?service_category=pool|landscaping|both|unset`, `?customer_id=`, `?q=`.
 * GET /properties (BE `require_admin`), names hydrated via
 * GET /customers?ids_in= like web; ids the list doesn't return are
 * resolved one-by-one (the fallback web's comment describes). Grouped by
 * customer (sticky headers); row tap → `/customer/<cid>?tab=properties`.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { View, Text, StyleSheet, SectionList, Pressable, Platform } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Loading } from "@/src/components/ui";
import { Header, FilterRow } from "@/src/components/widgets";
import AppTextInput from "@/src/components/ui/AppTextInput";
import { mapApiError } from "@/src/utils/mapApiError";
import { PropertyRow, GroupHeader } from "@/src/components/properties/PropertyListParts";

export const PROPERTY_CATEGORY_OPTIONS = [
  { key: "all", label: "All categories" },
  { key: "pool", label: "Pool" },
  { key: "landscaping", label: "Landscaping" },
  { key: "both", label: "Both services" },
  { key: "unset", label: "Not set" },
];
export const PROPERTY_ACTIVE_OPTIONS = [
  { key: "true", label: "Active" },
  { key: "false", label: "Inactive" },
  { key: "all", label: "All" },
];
const pick = (v: any, opts: { key: string }[], dflt: string) => (opts.some((o) => o.key === v) ? String(v) : dflt);

export default function PropertiesList() {
  const router = useRouter();
  const p = useLocalSearchParams<{ is_active?: string; service_category?: string; customer_id?: string; q?: string }>();
  const [activeFilter, setActiveFilter] = useState(pick(p.is_active, PROPERTY_ACTIVE_OPTIONS, "true"));
  const [categoryFilter, setCategoryFilter] = useState(pick(p.service_category, PROPERTY_CATEGORY_OPTIONS, "all"));
  const customerIdFilter = typeof p.customer_id === "string" ? p.customer_id : "";
  const [search, setSearch] = useState(typeof p.q === "string" ? p.q : "");
  const [debounced, setDebounced] = useState(search);
  const [rows, setRows] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [names, setNames] = useState<Record<string, string>>({});

  useEffect(() => { const t = setTimeout(() => setDebounced(search), 300); return () => clearTimeout(t); }, [search]);

  const fetchRows = useCallback(async () => {
    setLoading(true);
    setError("");
    const qp = new URLSearchParams();
    if (activeFilter !== "all") qp.set("is_active", activeFilter);
    if (categoryFilter !== "all") qp.set("service_category", categoryFilter);
    if (customerIdFilter) qp.set("customer_id", customerIdFilter);
    if (debounced) qp.set("search", debounced);
    const qs = qp.toString();
    try {
      const r: any = await api.get(`/properties${qs ? `?${qs}` : ""}`);
      setRows(Array.isArray(r?.items) ? r.items : []);
    } catch (e) {
      setRows([]);
      setError(mapApiError(e).title || "Couldn't load properties.");
    } finally {
      setLoading(false);
    }
  }, [activeFilter, categoryFilter, customerIdFilter, debounced]);

  useEffect(() => { fetchRows(); }, [fetchRows]);

  // Customer-name hydration — web `?ids_in=` call, then per-id fallback.
  useEffect(() => {
    const missing = Array.from(new Set(rows.map((r) => r.customer_id).filter(Boolean))).filter((cid) => !(cid in names));
    if (!missing.length) return;
    let alive = true;
    (async () => {
      const next: Record<string, string> = {};
      try {
        const r: any = await api.get(`/customers?ids_in=${encodeURIComponent(missing.join(","))}`);
        const items = Array.isArray(r?.items) ? r.items : Array.isArray(r) ? r : [];
        for (const c of items) if (missing.includes(c.id)) next[c.id] = c.name || c.company_name || "(unnamed)";
      } catch { /* non-fatal */ }
      const left = missing.filter((cid) => !(cid in next));
      await Promise.all(left.map(async (cid) => {
        try { const c: any = await api.get(`/customers/${cid}?slim=1`); next[cid] = c?.name || c?.company_name || ""; }
        catch { next[cid] = ""; }
      }));
      if (alive) setNames((prev) => ({ ...prev, ...next }));
    })();
    return () => { alive = false; };
  }, [rows]); // eslint-disable-line react-hooks/exhaustive-deps

  // Write filters back to the URL (web parity; default is_active omitted).
  useEffect(() => {
    router.setParams({
      is_active: activeFilter !== "true" ? activeFilter : undefined,
      service_category: categoryFilter !== "all" ? categoryFilter : undefined,
      q: debounced || undefined,
    } as any);
  }, [activeFilter, categoryFilter, debounced]); // eslint-disable-line react-hooks/exhaustive-deps

  const sections = useMemo(() => {
    const buckets = new Map<string, any[]>();
    for (const r of rows) {
      const cid = r.customer_id || "_orphans";
      if (!buckets.has(cid)) buckets.set(cid, []);
      buckets.get(cid)!.push(r);
    }
    return Array.from(buckets.entries())
      .map(([cid, data]) => ({ customerId: cid, customerName: names[cid] || "", data }))
      .sort((a, b) => (a.customerName || "zzz").localeCompare(b.customerName || "zzz"));
  }, [rows, names]);

  const clearFilters = () => { setActiveFilter("all"); setCategoryFilter("all"); setSearch(""); };

  return (
    <View style={styles.root} testID="properties-list-page">
      <Header title="Properties" subtitle="All serviceable properties across your accounts" back />
      <View style={styles.filterbar} testID="properties-list-filterbar">
        <View style={styles.searchBox}>
          <Ionicons name="search" size={16} color={colors.muted} />
          <AppTextInput testID="properties-list-search" style={styles.searchInput} value={search}
            onChangeText={setSearch} placeholder="Search label, address, city…" placeholderTextColor={colors.muted}
            autoCapitalize="none" returnKeyType="search" />
        </View>
      </View>
      <FilterRow options={PROPERTY_ACTIVE_OPTIONS} value={activeFilter} onChange={setActiveFilter} testID="properties-list-active-filter" />
      <FilterRow options={PROPERTY_CATEGORY_OPTIONS} value={categoryFilter} onChange={setCategoryFilter} testID="properties-list-category-filter" />
      {loading ? (
        <Loading testID="properties-list-loading" />
      ) : error ? (
        <Text style={styles.error} testID="properties-list-error">{error}</Text>
      ) : rows.length === 0 ? (
        <View style={styles.empty} testID="properties-list-empty">
          <Text style={styles.emptyTitle}>No properties match</Text>
          <Text style={styles.emptyText}>Try widening the filters or clearing search.</Text>
          <Pressable style={styles.clearBtn} onPress={clearFilters} testID="properties-list-clear-filters">
            <Text style={styles.clearText}>Clear filters</Text>
          </Pressable>
        </View>
      ) : (
        <SectionList
          testID="properties-list-grouped"
          sections={sections}
          keyExtractor={(it) => String(it.id)}
          stickySectionHeadersEnabled
          keyboardShouldPersistTaps="handled"
          contentContainerStyle={{ paddingBottom: spacing["3xl"] }}
          renderSectionHeader={({ section }) => (
            <GroupHeader customerId={section.customerId} customerName={section.customerName} count={section.data.length} />
          )}
          renderItem={({ item }) => (
            <PropertyRow property={item} onOpen={() => {
              if (item.customer_id) router.push({ pathname: "/customer/[id]", params: { id: item.customer_id, tab: "properties" } } as any);
            }} />
          )}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  filterbar: { paddingHorizontal: spacing.lg, paddingTop: spacing.md },
  searchBox: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm, height: 48,
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    borderRadius: radius.md, paddingHorizontal: spacing.md,
  },
  searchInput: { flex: 1, fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}) },
  error: { margin: spacing.lg, fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.error },
  empty: { alignItems: "center", padding: spacing.xl, gap: spacing.sm },
  emptyTitle: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  emptyText: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, textAlign: "center" },
  clearBtn: { marginTop: spacing.sm, minHeight: 44, justifyContent: "center", paddingHorizontal: spacing.lg, borderRadius: radius.pill, backgroundColor: colors.brand },
  clearText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: "#fff" },
});
