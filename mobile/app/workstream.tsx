/**
 * Workstream — filterable job feed.
 * Uses GET /api/workstream/jobs with filters mirrored from web.
 * Replaces old activity-based work-stream.tsx.
 */
import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, FlatList, RefreshControl,
  TouchableOpacity, ScrollView,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { useAuth } from "@/src/auth";
import { getWorkstreamJobs, type WorkstreamJob, type WorkstreamFilters } from "@/src/api/workstream";
import { colors, font, fontSize, spacing, radius, statusMeta } from "@/src/theme";

const STATUS_OPTIONS = [
  { key: "", label: "All" },
  { key: "pending", label: "Pending" },
  { key: "in_progress", label: "In Progress" },
  { key: "completed", label: "Completed" },
  { key: "cancelled", label: "Cancelled" },
];

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
    return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" });
  } catch { return ""; }
}

export default function WorkstreamScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { user: _user } = useAuth();
  // _user available for future role-gated filters

  const [jobs, setJobs] = useState<WorkstreamJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [filters, setFilters] = useState<WorkstreamFilters>({ sort: "newest", limit: 100 });

  const load = useCallback(async () => {
    try {
      const data = await getWorkstreamJobs(filters);
      setJobs(Array.isArray(data) ? data : []);
    } catch {
      setJobs([]);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [filters]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const setStatus = (status: string) => setFilters((f) => ({ ...f, status: status || undefined }));
  const setSort = (sort: string) => setFilters((f) => ({ ...f, sort }));

  const renderCard = ({ item }: { item: WorkstreamJob }) => {
    const meta = statusMeta[item.status || ""] || { label: item.status || "", bg: colors.surfaceTertiary, fg: colors.onSurfaceSecondary };
    const photoCount = item.media?.photos_count || 0;
    const videoCount = item.media?.videos_count || 0;
    return (
      <TouchableOpacity
        style={s.card}
        activeOpacity={0.7}
        onPress={() => router.push(`/job/${item.id}`)}
        testID={`ws-job-card-${item.id}`}
      >
        <View style={s.cardTop}>
          <View style={[s.statusPill, { backgroundColor: meta.bg }]}>
            <Text style={[s.statusText, { color: meta.fg }]}>{meta.label}</Text>
          </View>
          <Text style={s.cardTime}>{relTime(item.latest_activity || item.updated_at)}</Text>
        </View>
        <Text style={s.cardTitle} numberOfLines={2}>{item.title || "Untitled Job"}</Text>
        <View style={s.cardMeta}>
          {item.customer_name ? (
            <View style={s.metaChip}>
              <Ionicons name="person" size={12} color={colors.muted} />
              <Text style={s.metaText} numberOfLines={1}>{item.customer_name}</Text>
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
              <Ionicons name={item.service_type === "pool" ? "water" : "leaf"} size={12} color={colors.muted} />
              <Text style={s.metaText}>{item.service_type}</Text>
            </View>
          ) : null}
        </View>
        {item.scheduled_date ? (
          <View style={s.scheduleRow}>
            <Ionicons name="calendar-outline" size={13} color={colors.brand} />
            <Text style={s.scheduleText}>{item.scheduled_date}</Text>
          </View>
        ) : null}
        <View style={s.cardBottom}>
          {item.property_label ? (
            <View style={s.metaChip}>
              <Ionicons name="location" size={12} color={colors.muted} />
              <Text style={s.metaText} numberOfLines={1}>{item.property_label}</Text>
            </View>
          ) : null}
          <View style={s.countsRow}>
            {(item.notes_count || 0) > 0 && (
              <View style={s.countChip}>
                <Ionicons name="document-text" size={11} color={colors.muted} />
                <Text style={s.countText}>{item.notes_count}</Text>
              </View>
            )}
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
        <Text style={s.headerTitle}>Workstream</Text>
        <View style={{ width: 22 }} />
      </View>

      {/* Status filter pills */}
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.filterRow}>
        {STATUS_OPTIONS.map((opt) => (
          <TouchableOpacity
            key={opt.key}
            style={[s.filterPill, (filters.status || "") === opt.key && s.filterPillActive]}
            onPress={() => setStatus(opt.key)}
            testID={`ws-filter-${opt.key || "all"}`}
          >
            <Text style={[s.filterText, (filters.status || "") === opt.key && s.filterTextActive]}>
              {opt.label}
            </Text>
          </TouchableOpacity>
        ))}
      </ScrollView>

      {/* Sort row */}
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={[s.filterRow, { paddingTop: 0 }]}>
        {SORT_OPTIONS.map((opt) => (
          <TouchableOpacity
            key={opt.key}
            style={[s.sortPill, filters.sort === opt.key && s.sortPillActive]}
            onPress={() => setSort(opt.key)}
          >
            <Text style={[s.sortText, filters.sort === opt.key && s.sortTextActive]}>{opt.label}</Text>
          </TouchableOpacity>
        ))}
      </ScrollView>

      {loading ? (
        <View style={s.emptyWrap}>
          <Text style={s.emptyText}>Loading...</Text>
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
              <Text style={s.emptyText}>No jobs found</Text>
            </View>
          }
        />
      )}
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: "#F8FAFC" },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.lg, paddingVertical: spacing.md, backgroundColor: colors.surface, borderBottomWidth: 1, borderBottomColor: colors.border },
  headerTitle: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface },
  filterRow: { paddingHorizontal: spacing.lg, paddingVertical: spacing.sm, gap: spacing.sm },
  filterPill: { paddingHorizontal: 14, paddingVertical: 7, borderRadius: 999, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  filterPillActive: { backgroundColor: colors.brandTertiary, borderColor: colors.brandTertiary },
  filterText: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted },
  filterTextActive: { color: colors.onBrandTertiary, fontFamily: font.semibold },
  sortPill: { paddingHorizontal: 10, paddingVertical: 5, borderRadius: 999, backgroundColor: "transparent" },
  sortPillActive: { backgroundColor: colors.surfaceSecondary },
  sortText: { fontFamily: font.regular, fontSize: 11, color: colors.muted },
  sortTextActive: { fontFamily: font.semibold, color: colors.onSurface },
  list: { padding: spacing.lg, paddingBottom: 40 },
  card: { backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.lg, marginBottom: spacing.md, borderWidth: 1, borderColor: colors.border },
  cardTop: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: spacing.sm },
  statusPill: { paddingHorizontal: 10, paddingVertical: 3, borderRadius: 999 },
  statusText: { fontFamily: font.bold, fontSize: 10, letterSpacing: 0.5, textTransform: "uppercase" },
  cardTime: { fontFamily: font.regular, fontSize: 11, color: colors.muted },
  cardTitle: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface, marginBottom: spacing.sm },
  cardMeta: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm, marginBottom: spacing.xs },
  metaChip: { flexDirection: "row", alignItems: "center", gap: 4 },
  metaText: { fontFamily: font.regular, fontSize: 11, color: colors.muted, maxWidth: 120 },
  scheduleRow: { flexDirection: "row", alignItems: "center", gap: 4, marginTop: spacing.xs },
  scheduleText: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.brand },
  cardBottom: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginTop: spacing.sm, paddingTop: spacing.sm, borderTopWidth: 1, borderTopColor: colors.border },
  countsRow: { flexDirection: "row", gap: spacing.sm },
  countChip: { flexDirection: "row", alignItems: "center", gap: 3 },
  countText: { fontFamily: font.medium, fontSize: 10, color: colors.muted },
  emptyWrap: { flex: 1, alignItems: "center", justifyContent: "center", paddingTop: 80 },
  emptyText: { fontFamily: font.medium, fontSize: fontSize.base, color: colors.muted, marginTop: 8 },
});
