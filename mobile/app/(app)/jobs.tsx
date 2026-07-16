import React, { useCallback, useEffect, useMemo, useState } from "react";
import { View, Text, StyleSheet, FlatList, RefreshControl, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter, Redirect } from "expo-router";
import AsyncStorage from "@react-native-async-storage/async-storage";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { useOnline, cacheJobs, getCachedJobs, flushPendingPhotos, flushPendingMutations } from "@/src/offline";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Loading, EmptyState } from "@/src/components/ui";
import { Header, JobCard, FilterRow, IconButton, NotificationBell, OfflineBanner } from "@/src/components/widgets";

const FILTERS = [
  { key: "all", label: "All" },
  { key: "requested", label: "Requested" },
  { key: "pending", label: "Pending" },
  { key: "active", label: "Active" },
  { key: "completed", label: "Completed" },
];

// Phase 50.F — AsyncStorage key builder for "last viewed" timestamps.
const jobViewedKey = (userId: string, jobId: string) => `jv_${userId}_${jobId}`;

export default function Jobs() {
  const { user } = useAuth();
  const router = useRouter();
  const online = useOnline();
  const [jobs, setJobs] = useState<any[]>([]);
  const [filter, setFilter] = useState("all");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [usingCache, setUsingCache] = useState(false);
  const [viewedMap, setViewedMap] = useState<Record<string, string>>({});

  const isCustomer = user?.role === "customer";
  const isAdmin = user?.role === "admin" || user?.role === "super_admin";
  const isTech = user?.role === "technician";
  if (isAdmin) {
    return <Redirect href="/(app)/schedule/calendar" />;
  }

  const load = useCallback(async (f: string) => {
    const cacheKey = `${user?.role}_${user?.id}`;
    try {
      await flushPendingMutations().catch(() => {});
      await flushPendingPhotos().catch(() => {});
      const q = f === "all" ? "" : `?status=${f}`;
      const data = await api.get(`/jobs${q}`);
      setJobs(data);
      setUsingCache(false);
      if (f === "all") cacheJobs(cacheKey, data);
    } catch (e) {
      const cached = await getCachedJobs(cacheKey);
      if (cached) {
        const filtered = f === "all" ? cached : cached.filter((j: any) => j.status === f);
        setJobs(filtered);
        setUsingCache(true);
      }
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [user?.role, user?.id]);

  useFocusEffect(
    useCallback(() => {
      load(filter);
    }, [filter, load, online])
  );

  // Phase 50.F — bulk-load "last viewed" timestamps from AsyncStorage
  // for the current job list so the JobCard can display red-dot badges.
  useEffect(() => {
    if (!isTech || !user?.id || jobs.length === 0) return;
    let alive = true;
    (async () => {
      try {
        const keys = jobs.map((j) => jobViewedKey(user.id, j.id));
        const entries = await AsyncStorage.multiGet(keys);
        const next: Record<string, string> = {};
        for (const [k, v] of entries) {
          if (v) next[k] = v;
        }
        if (alive) setViewedMap(next);
      } catch { /* silent */ }
    })();
    return () => { alive = false; };
  }, [jobs, user?.id, isTech]);

  // Phase 50.E — earliest scheduled-today incomplete job for the tech.
  const nextJob = useMemo(() => {
    if (!isTech) return null;
    const today = new Date().toISOString().slice(0, 10);
    const candidates = jobs.filter((j) =>
      String(j.scheduled_date || "").startsWith(today) &&
      !["completed", "cancelled", "canceled", "no_show", "skipped"].includes(String(j.status || "").toLowerCase()),
    );
    candidates.sort((a, b) => String(a.scheduled_start || a.scheduled_date || "z").localeCompare(String(b.scheduled_start || b.scheduled_date || "z")));
    return candidates[0] || null;
  }, [jobs, isTech]);

  const markViewed = useCallback(async (jobId: string) => {
    if (!user?.id) return;
    const ts = new Date().toISOString();
    setViewedMap((m) => ({ ...m, [jobViewedKey(user.id, jobId)]: ts }));
    try { await AsyncStorage.setItem(jobViewedKey(user.id, jobId), ts); } catch { /* silent */ }
  }, [user?.id]);

  const hasUnread = useCallback((job: any) => {
    if (!isTech || !user?.id) return false;
    const last = job.last_activity_at || job.updated_at;
    if (!last) return false;
    const viewed = viewedMap[jobViewedKey(user.id, job.id)];
    if (!viewed) return true;
    return String(last) > String(viewed);
  }, [isTech, user?.id, viewedMap]);

  return (
    <View style={styles.root}>
      <Header
        title={isCustomer ? "My Services" : "Jobs"}
        subtitle={isCustomer ? "Your upcoming & past services" : "Your assigned jobs"}
        right={
          isCustomer ? <NotificationBell /> : undefined
        }
      />
      {usingCache ? <OfflineBanner /> : null}
      {nextJob ? (
        <Pressable
          testID="next-job-chip"
          style={styles.nextChip}
          onPress={() => { markViewed(nextJob.id); router.push(`/job/${nextJob.id}` as any); }}
        >
          <Ionicons name="flash" size={14} color="#fff" />
          <Text style={styles.nextChipText} numberOfLines={1}>
            Next: {nextJob.customer_name || nextJob.title}
            {nextJob.scheduled_start ? ` @ ${String(nextJob.scheduled_start).slice(11, 16)}` : ""}
          </Text>
          <Ionicons name="chevron-forward" size={14} color="#fff" />
        </Pressable>
      ) : null}
      <FilterRow options={FILTERS} value={filter} onChange={setFilter} testID="jobs-filter" />
      {loading ? (
        <Loading testID="jobs-loading" />
      ) : jobs.length === 0 ? (
        <EmptyState icon="calendar-outline" title={isCustomer ? "No services yet" : "No jobs scheduled"} subtitle={isCustomer ? "Request a service to get started." : "Jobs will appear here once created."} testID="jobs-empty" />
      ) : (
        <FlatList
          testID="jobs-list"
          data={jobs}
          keyExtractor={(i) => i.id}
          contentContainerStyle={{ padding: spacing.lg, paddingTop: spacing.sm, paddingBottom: isCustomer ? 96 : spacing["3xl"] }}
          renderItem={({ item }) => (
            <JobCard
              job={item}
              testID={`job-card-${item.id}`}
              unread={hasUnread(item)}
              onView={() => markViewed(item.id)}
            />
          )}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(filter); }} />}
        />
      )}
      {isCustomer ? (
        <Pressable style={styles.fab} onPress={() => router.push("/request-service")} testID="request-service-fab">
          <Ionicons name="add" size={22} color="#fff" />
          <Text style={styles.fabText}>Request Service</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  nextChip: {
    marginHorizontal: spacing.lg,
    marginTop: spacing.sm,
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: colors.brand,
    paddingHorizontal: spacing.md,
    paddingVertical: 10,
    borderRadius: radius.pill,
  },
  nextChipText: { flex: 1, color: "#fff", fontFamily: font.bold, fontSize: fontSize.sm },
  fab: {
    position: "absolute",
    right: spacing.lg,
    bottom: spacing.lg,
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: colors.brand,
    paddingHorizontal: spacing.lg,
    height: 52,
    borderRadius: radius.pill,
    shadowColor: colors.brand,
    shadowOpacity: 0.35,
    shadowRadius: 10,
    shadowOffset: { width: 0, height: 4 },
    elevation: 4,
  },
  fabText: { fontFamily: font.semibold, fontSize: fontSize.base, color: "#fff" },
});
