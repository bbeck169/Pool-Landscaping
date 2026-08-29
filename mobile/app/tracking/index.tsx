/**
 * Equipment Service Trackers — admin/manager/tech.
 * GET /api/equipment/trackers → { trackers, count, counts_by_status, coming_due_days }
 */
import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, FlatList, TouchableOpacity,
  ActivityIndicator, RefreshControl, TextInput, ScrollView,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useFocusEffect, useRouter } from "expo-router";

import { useAuth } from "@/src/auth";
import { api } from "@/src/api";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";
import { formatCustomerName } from "@/src/utils/formatCustomerName";

type Tracker = {
  id: string;
  tracker_type?: string;
  customer_id?: string;
  customer_name?: string;
  property_address?: string;
  status?: string;
  interval_days?: number;
  last_cleaned_at?: string;
  due_date?: string;
  is_active?: boolean;
  history?: any[];
};

const STATUS_COLORS: Record<string, { bg: string; fg: string; icon: string }> = {
  current: { bg: "#DCFCE7", fg: "#166534", icon: "checkmark-circle" },
  coming_due: { bg: "#FEF3C7", fg: "#A16207", icon: "alert-circle" },
  past_due: { bg: "#FEE2E2", fg: "#991B1B", icon: "close-circle" },
};

const TABS = [
  { key: "all", label: "All" },
  { key: "past_due", label: "Past Due" },
  { key: "coming_due", label: "Coming Due" },
  { key: "current", label: "Current" },
];

const TYPE_TABS = [
  { key: "", label: "All" },
  { key: "filter", label: "Filter" },
  { key: "salt_cell", label: "Salt Cell" },
];

export default function TrackingScreen() {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { user } = useAuth();
  const role = String((user as any)?.role || "");
  const allowed = ["admin", "super_admin", "manager", "technician"].includes(role);

  const [items, setItems] = useState<Tracker[]>([]);
  const [counts, setCounts] = useState<any>({});
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [statusTab, setStatusTab] = useState("all");
  const [typeTab, setTypeTab] = useState("");
  const [search, setSearch] = useState("");

  const load = useCallback(async () => {
    if (!allowed) { setLoading(false); return; }
    try {
      const params = new URLSearchParams();
      if (typeTab) params.append("tracker_type", typeTab);
      const url = `/equipment/trackers${params.toString() ? `?${params}` : ""}`;
      const res = await api.get(url);
      setItems(res?.trackers || []);
      setCounts(res?.counts_by_status || {});
    } catch {} finally { setLoading(false); setRefreshing(false); }
  }, [allowed, typeTab]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  if (!allowed) {
    return (
      <View style={[s.center, { paddingTop: insets.top + 60 }]} testID="tracking-role-gate">
        <Ionicons name="lock-closed" size={36} color={colors.muted} />
        <Text style={s.gateText}>Not authorized</Text>
        <TouchableOpacity onPress={() => router.replace("/(app)")} style={s.gateBtn}>
          <Text style={s.gateBtnText}>Go Home</Text>
        </TouchableOpacity>
      </View>
    );
  }

  const q = search.toLowerCase().trim();
  const filtered = items.filter((t) => {
    if (statusTab !== "all" && t.status !== statusTab) return false;
    if (q && !`${t.customer_name || ""} ${t.property_address || ""}`.toLowerCase().includes(q)) return false;
    return true;
  });

  return (
    <View style={[s.root, { paddingTop: insets.top }]}>
      <View style={s.navBar}>
        <TouchableOpacity onPress={() => router.back()} hitSlop={12}>
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </TouchableOpacity>
        <Text style={s.navTitle}>Service Tracking</Text>
        <View style={{ width: 22 }} />
      </View>

      {/* Type tabs */}
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.filterRow}>
        {TYPE_TABS.map((t) => (
          <TouchableOpacity key={t.key} style={[s.chip, typeTab === t.key && s.chipActive]} onPress={() => setTypeTab(t.key)} testID={`tracker-type-${t.key || "all"}`}>
            <Ionicons name={t.key === "filter" ? "funnel-outline" : t.key === "salt_cell" ? "water-outline" : "layers-outline"} size={14} color={typeTab === t.key ? "#fff" : colors.muted} />
            <Text style={[s.chipText, typeTab === t.key && s.chipTextActive]}>{t.label}</Text>
          </TouchableOpacity>
        ))}
      </ScrollView>

      {/* Status tabs */}
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.filterRow}>
        {TABS.map((t) => (
          <TouchableOpacity key={t.key} style={[s.pill, statusTab === t.key && s.pillActive]} onPress={() => setStatusTab(t.key)} testID={`tracker-status-${t.key}`}>
            <Text style={[s.pillText, statusTab === t.key && s.pillTextActive]}>
              {t.label}{t.key !== "all" && counts[t.key] != null ? ` (${counts[t.key]})` : ""}
            </Text>
          </TouchableOpacity>
        ))}
      </ScrollView>

      {/* Search */}
      <View style={s.searchWrap}>
        <Ionicons name="search" size={16} color={colors.muted} />
        <TextInput style={s.searchInput} value={search} onChangeText={setSearch} placeholder="Search customer or address…" placeholderTextColor={colors.muted} testID="tracker-search" />
      </View>

      {loading ? (
        <View style={s.center}><ActivityIndicator size="large" color={colors.brand} /></View>
      ) : (
        <FlatList
          data={filtered}
          keyExtractor={(t) => t.id}
          contentContainerStyle={s.list}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.brand} />}
          ListEmptyComponent={
            <View style={s.emptyWrap}>
              <Ionicons name="filter-outline" size={32} color={colors.muted} />
              <Text style={s.emptyText}>No trackers found</Text>
            </View>
          }
          renderItem={({ item }) => {
            const sc = STATUS_COLORS[item.status || ""] || STATUS_COLORS.current;
            const isFilter = item.tracker_type === "filter";
            const dueDate = item.due_date ? new Date(item.due_date) : null;
            const lastCleaned = item.last_cleaned_at ? new Date(item.last_cleaned_at) : null;
            return (
              <View style={s.card} testID={`tracker-${item.id}`}>
                <View style={s.cardTop}>
                  <View style={[s.typeIcon, { backgroundColor: isFilter ? "#DCFCE7" : "#E0F2FE" }]}>
                    <Ionicons name={isFilter ? "funnel" : "water"} size={18} color={isFilter ? "#166534" : "#0369A1"} />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={s.cardName} numberOfLines={1}>{formatCustomerName(item)}</Text>
                    {item.property_address ? <Text style={s.cardAddr} numberOfLines={1}>{item.property_address}</Text> : null}
                  </View>
                  <View style={[s.statusPill, { backgroundColor: sc.bg }]}>
                    <Ionicons name={sc.icon as any} size={12} color={sc.fg} />
                    <Text style={[s.statusText, { color: sc.fg }]}>{(item.status || "").replace(/_/g, " ")}</Text>
                  </View>
                </View>
                <View style={s.cardMeta}>
                  {item.interval_days && (
                    <View style={s.metaChip}>
                      <Text style={s.metaText}>Every {item.interval_days}d</Text>
                    </View>
                  )}
                  {lastCleaned && (
                    <Text style={s.metaDate}>Cleaned: {lastCleaned.toLocaleDateString()}</Text>
                  )}
                  {dueDate && (
                    <Text style={[s.metaDate, item.status === "past_due" && { color: "#DC2626" }]}>
                      Due: {dueDate.toLocaleDateString()}
                    </Text>
                  )}
                </View>
              </View>
            );
          }}
        />
      )}
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: "#F8FAFC" },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 24 },
  gateText: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface, marginTop: 12 },
  gateBtn: { marginTop: 20, paddingHorizontal: 24, paddingVertical: 12, borderRadius: radius.md, backgroundColor: colors.brand },
  gateBtnText: { fontFamily: font.semibold, fontSize: fontSize.base, color: "#fff" },
  navBar: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.lg, paddingVertical: spacing.md, borderBottomWidth: 1, borderBottomColor: colors.border, backgroundColor: colors.surface },
  navTitle: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  filterRow: { paddingHorizontal: spacing.lg, paddingVertical: spacing.xs, gap: spacing.sm },
  chip: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 12, paddingVertical: 7, borderRadius: 999, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  chipActive: { backgroundColor: colors.brand, borderColor: colors.brand },
  chipText: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted },
  chipTextActive: { color: "#fff" },
  pill: { paddingHorizontal: 14, paddingVertical: 7, borderRadius: 999, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  pillActive: { backgroundColor: colors.brandTertiary, borderColor: colors.brandTertiary },
  pillText: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted },
  pillTextActive: { color: colors.onBrandTertiary, fontFamily: font.semibold },
  searchWrap: { flexDirection: "row", alignItems: "center", gap: 8, marginHorizontal: spacing.lg, marginVertical: spacing.sm, backgroundColor: colors.surface, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, paddingHorizontal: 12, height: 40 },
  searchInput: { flex: 1, fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurface },
  list: { padding: spacing.lg, paddingBottom: 40 },
  card: { backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.lg, marginBottom: spacing.sm, borderWidth: 1, borderColor: colors.border },
  cardTop: { flexDirection: "row", alignItems: "center", gap: 10 },
  typeIcon: { width: 36, height: 36, borderRadius: 18, alignItems: "center", justifyContent: "center" },
  cardName: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  cardAddr: { fontFamily: font.regular, fontSize: 11, color: colors.muted, marginTop: 1 },
  statusPill: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 8, paddingVertical: 3, borderRadius: 999 },
  statusText: { fontFamily: font.bold, fontSize: 9, letterSpacing: 0.3, textTransform: "uppercase" },
  cardMeta: { flexDirection: "row", gap: 12, marginTop: spacing.sm, alignItems: "center", flexWrap: "wrap" },
  metaChip: { backgroundColor: "#F1F5F9", paddingHorizontal: 8, paddingVertical: 2, borderRadius: 4 },
  metaText: { fontFamily: font.medium, fontSize: 10, color: colors.muted },
  metaDate: { fontFamily: font.regular, fontSize: 11, color: colors.muted },
  emptyWrap: { alignItems: "center", paddingTop: 80 },
  emptyText: { fontFamily: font.medium, fontSize: fontSize.base, color: colors.muted, marginTop: 8 },
});
