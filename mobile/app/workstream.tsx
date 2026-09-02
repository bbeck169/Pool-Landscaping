/**
 * Workstream — admin-only completed-jobs feed.
 *
 * GET /api/workstream/jobs (default status=completed; the API returns 400
 * for any other status). Only admin + super_admin may access.
 *
 * Tapping a card navigates to /workstream/[id] (Service Log detail).
 */
import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, FlatList, RefreshControl,
  TouchableOpacity, ScrollView, ActivityIndicator,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { useAuth } from "@/src/auth";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";
import { api } from "@/src/api";
import { formatCustomerName } from "@/src/utils/formatCustomerName";
import { formatCompletedAt } from "@/src/lib/dateTimeFormat";

type WsJob = {
  id: string;
  title?: string;
  status?: string;
  service_type?: string;
  scheduled_date?: string;
  customer_name?: string;
  technician_name?: string;
  property_label?: string;
  property_address?: string;
  media?: { photos_count?: number; videos_count?: number };
  created_at?: string;
  updated_at?: string;
};

const SORT_OPTIONS = [
  { key: "newest", label: "Newest" },
  { key: "oldest", label: "Oldest" },
  { key: "tech_asc", label: "Tech A-Z" },
  { key: "customer_asc", label: "Customer A-Z" },
];

function relTime(iso?: string) {
  if (!iso) return "";
  try {
    const ms = Date.now() - new Date(iso).getTime();
    const m = Math.floor(ms / 60000);
    if (m < 1) return "just now";
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h ago`;
    const d = Math.floor(h / 24);
    if (d < 30) return `${d}d ago`;
    return formatCompletedAt(iso);
  } catch { return ""; }
}

export default function WorkstreamScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { user } = useAuth();

  // Role gate: admin + super_admin only
  const role = (user as any)?.role || "";
  const allowed = role === "admin" || role === "super_admin";

  const [jobs, setJobs] = useState<WsJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [sort, setSort] = useState("newest");

  const load = useCallback(async () => {
    if (!allowed) { setLoading(false); return; }
    try {
      // Always fetch completed jobs only — the API defaults to completed
      // and returns 400 for other statuses.
      const params = new URLSearchParams();
      if (sort) params.set("sort", sort);
      params.set("limit", "100");
      const qs = params.toString();
      const res = await api.get(`/workstream/jobs${qs ? `?${qs}` : ""}`);
      const list = Array.isArray(res) ? res : res?.jobs || [];
      setJobs(list);
    } catch {
      setJobs([]);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [sort, allowed]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  // Role gate UI
  if (!allowed) {
    return (
      <View style={[s.center, { paddingTop: insets.top + 60 }]} testID="workstream-role-gate">
        <Ionicons name="lock-closed" size={36} color={colors.muted} />
        <Text style={s.gateText}>Not authorized</Text>
        <Text style={s.gateSubtext}>Workstream is available to admins only.</Text>
        <TouchableOpacity onPress={() => router.replace("/(app)")} style={s.gateBtn} testID="workstream-go-home">
          <Text style={s.gateBtnText}>Go Home</Text>
        </TouchableOpacity>
      </View>
    );
  }

  const renderCard = ({ item }: { item: WsJob }) => {
    const photoCount = item.media?.photos_count || 0;
    const videoCount = item.media?.videos_count || 0;
    return (
      <TouchableOpacity
        style={s.card}
        activeOpacity={0.7}
        onPress={() => router.push(`/workstream/${item.id}`)}
        testID={`ws-job-card-${item.id}`}
      >
        <View style={s.cardTop}>
          <View style={s.statusPill}>
            <Text style={s.statusText}>COMPLETED</Text>
          </View>
          <Text style={s.cardTime}>{relTime(item.created_at)}</Text>
        </View>
        <Text style={s.cardTitle} numberOfLines={2}>{item.title || "Untitled Job"}</Text>
        <View style={s.cardMeta}>
          {item.customer_name ? (
            <View style={s.metaChip}>
              <Ionicons name="person" size={12} color={colors.muted} />
              <Text style={s.metaText} numberOfLines={1}>{formatCustomerName(item)}</Text>
            </View>
          ) : null}
          {item.technician_name ? (
            <View style={s.metaChip}>
              <Ionicons name="construct" size={12} color={colors.muted} />
              <Text style={s.metaText} numberOfLines={1}>{item.technician_name}</Text>
            </View>
          ) : null}
          {item.service_type ? (
            <View style={s.metaChip}>
              <Ionicons name={item.service_type?.toLowerCase().includes("pool") ? "water" : "leaf"} size={12} color={colors.muted} />
              <Text style={s.metaText}>{item.service_type}</Text>
            </View>
          ) : null}
        </View>
        {item.property_label || item.property_address ? (
          <View style={s.propRow}>
            <Ionicons name="location" size={12} color={colors.muted} />
            <Text style={s.metaText} numberOfLines={1}>{item.property_label || item.property_address}</Text>
          </View>
        ) : null}
        <View style={s.cardBottom}>
          <View style={s.countsRow}>
            {photoCount > 0 && (
              <View style={s.countChip}>
                <Ionicons name="image" size={11} color={colors.muted} />
                <Text style={s.countText}>{photoCount}</Text>
              </View>
            )}
            {videoCount > 0 && (
              <View style={s.countChip}>
                <Ionicons name="videocam" size={11} color={colors.muted} />
                <Text style={s.countText}>{videoCount}</Text>
              </View>
            )}
          </View>
        </View>
      </TouchableOpacity>
    );
  };

  return (
    <View style={[s.root, { paddingTop: insets.top }]}>
      <View style={s.header}>
        <TouchableOpacity onPress={() => router.back()} hitSlop={12}>
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </TouchableOpacity>
        <Text style={s.headerTitle}>Workstream — Completed Jobs</Text>
        <View style={{ width: 22 }} />
      </View>

      {/* Sort row only — no status filter pills */}
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.filterRow}>
        {SORT_OPTIONS.map((opt) => (
          <TouchableOpacity
            key={opt.key}
            style={[s.sortPill, sort === opt.key && s.sortPillActive]}
            onPress={() => setSort(opt.key)}
            testID={`ws-sort-${opt.key}`}
          >
            <Text style={[s.sortText, sort === opt.key && s.sortTextActive]}>{opt.label}</Text>
          </TouchableOpacity>
        ))}
      </ScrollView>

      {loading ? (
        <View style={s.emptyWrap}>
          <ActivityIndicator size="large" color={colors.brand} />
        </View>
      ) : (
        <FlatList
          data={jobs}
          keyExtractor={(j) => j.id}
          renderItem={renderCard}
          contentContainerStyle={s.list}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.brand} />}
          ListEmptyComponent={
            <View style={s.emptyWrap}>
              <Ionicons name="briefcase-outline" size={36} color={colors.muted} />
              <Text style={s.emptyText}>No completed jobs</Text>
            </View>
          }
        />
      )}
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: "#F8FAFC" },
  center: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface, padding: 24 },
  gateText: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface, marginTop: 12 },
  gateSubtext: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted, marginTop: 4, textAlign: "center" },
  gateBtn: { marginTop: 20, paddingHorizontal: 24, paddingVertical: 12, borderRadius: radius.md, backgroundColor: colors.brand },
  gateBtnText: { fontFamily: font.semibold, fontSize: fontSize.base, color: "#fff" },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.lg, paddingVertical: spacing.md, backgroundColor: colors.surface, borderBottomWidth: 1, borderBottomColor: colors.border },
  headerTitle: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface, flex: 1, textAlign: "center" },
  filterRow: { paddingHorizontal: spacing.lg, paddingVertical: spacing.sm, gap: spacing.sm },
  sortPill: { paddingHorizontal: 14, paddingVertical: 7, borderRadius: 999, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  sortPillActive: { backgroundColor: colors.brandTertiary, borderColor: colors.brandTertiary },
  sortText: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted },
  sortTextActive: { color: colors.onBrandTertiary, fontFamily: font.semibold },
  list: { padding: spacing.lg, paddingBottom: 40 },
  card: { backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.lg, marginBottom: spacing.md, borderWidth: 1, borderColor: colors.border },
  cardTop: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: spacing.sm },
  statusPill: { paddingHorizontal: 10, paddingVertical: 3, borderRadius: 999, backgroundColor: "#DCFCE7" },
  statusText: { fontFamily: font.bold, fontSize: 10, letterSpacing: 0.5, color: "#166534" },
  cardTime: { fontFamily: font.regular, fontSize: 11, color: colors.muted },
  cardTitle: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface, marginBottom: spacing.sm },
  cardMeta: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm, marginBottom: spacing.xs },
  metaChip: { flexDirection: "row", alignItems: "center", gap: 4 },
  metaText: { fontFamily: font.regular, fontSize: 11, color: colors.muted, maxWidth: 140 },
  propRow: { flexDirection: "row", alignItems: "center", gap: 4, marginTop: 4 },
  cardBottom: { marginTop: spacing.sm, paddingTop: spacing.sm, borderTopWidth: 1, borderTopColor: colors.border },
  countsRow: { flexDirection: "row", gap: spacing.sm },
  countChip: { flexDirection: "row", alignItems: "center", gap: 3 },
  countText: { fontFamily: font.medium, fontSize: 10, color: colors.muted },
  emptyWrap: { flex: 1, alignItems: "center", justifyContent: "center", paddingTop: 80 },
  emptyText: { fontFamily: font.medium, fontSize: fontSize.base, color: colors.muted, marginTop: 8 },
});
