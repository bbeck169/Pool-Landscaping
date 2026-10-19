/**
 * Dashboard parity · mobile mirror of web `pages/jobs/JobsList.jsx`
 * (`/admin/jobs`, AdminOnly). Target of the Active Jobs / Pending KPI
 * tiles for admin / super_admin — `/(app)/jobs` redirects admins to the
 * calendar, so the filtered list needs its own route.
 *
 * `?status=` seeds the filter (straight passthrough to `GET /jobs`),
 * row tap → `/job/<id>`. Web's bulk delete / status / reschedule
 * toolkit is NOT ported in this cycle (read-only list).
 */
import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, FlatList, Pressable, RefreshControl } from "react-native";
import { Redirect, useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Loading, StatusChip } from "@/src/components/ui";
import { Header, FilterRow } from "@/src/components/widgets";
import { formatCustomerName } from "@/src/utils/formatCustomerName";

// Web STATUS_OPTIONS + leading "All" ("" on web).
export const ADMIN_JOB_STATUS_OPTIONS = [
  { key: "all", label: "All" },
  { key: "active", label: "Active" },
  { key: "pending", label: "Pending" },
  { key: "scheduled", label: "Scheduled" },
  { key: "in_progress", label: "In progress" },
  { key: "completed", label: "Completed" },
  { key: "canceled", label: "Canceled" },
];

function JobRow({ job, onPress }: { job: any; onPress: () => void }) {
  return (
    <Pressable style={styles.row} onPress={onPress} testID={`job-row-${job.id}`}>
      <View style={{ flex: 1, minWidth: 0 }}>
        <Text style={styles.title} numberOfLines={1}>
          {job.title || job.service_name || `Job ${String(job.id).slice(0, 8)}`}
        </Text>
        <Text style={styles.meta} numberOfLines={1} testID={`job-row-customer-${job.id}`}>
          {[formatCustomerName(job), job.scheduled_date || "—"].filter(Boolean).join(" · ")}
        </Text>
      </View>
      <StatusChip status={job.status || "scheduled"} testID={`job-row-status-${job.id}`} />
    </Pressable>
  );
}

export default function AdminJobsList() {
  const { user } = useAuth();
  const router = useRouter();
  const params = useLocalSearchParams<{ status?: string }>();
  const initial = ADMIN_JOB_STATUS_OPTIONS.some((o) => o.key === params.status) ? String(params.status) : "all";
  const [status, setStatus] = useState(initial);
  const [rows, setRows] = useState<any[] | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    const qs = status !== "all" ? `?status=${encodeURIComponent(status)}` : "";
    try {
      const r = await api.get(`/jobs${qs}`);
      setRows(Array.isArray(r) ? r : []);
    } catch {
      setRows([]);
    } finally {
      setRefreshing(false);
    }
  }, [status]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const onChange = (k: string) => {
    setRows(null);
    setStatus(k);
    router.setParams({ status: k === "all" ? undefined : k } as any);
  };

  if (user && !["admin", "super_admin"].includes(String(user.role))) return <Redirect href="/(app)" />;

  return (
    <View style={styles.root} testID="jobs-page">
      <Header title="Jobs (admin)" subtitle="Work orders by status" back />
      <FilterRow options={ADMIN_JOB_STATUS_OPTIONS} value={status} onChange={onChange} testID="jobs-filter-status" />
      {rows === null ? (
        <Loading testID="jobs-loading" />
      ) : (
        <FlatList
          testID="jobs-table"
          data={rows}
          keyExtractor={(j) => String(j.id)}
          contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}
          renderItem={({ item }) => <JobRow job={item} onPress={() => router.push(`/job/${item.id}` as any)} />}
          ListEmptyComponent={<Text style={styles.empty} testID="jobs-empty">No jobs match this filter.</Text>}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  row: {
    flexDirection: "row", alignItems: "center", gap: spacing.md, minHeight: 56,
    backgroundColor: colors.surface, borderRadius: radius.lg, borderWidth: 1,
    borderColor: colors.border, padding: spacing.md, marginBottom: spacing.sm,
  },
  title: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  meta: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
  empty: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, textAlign: "center", marginTop: spacing.xl },
});
