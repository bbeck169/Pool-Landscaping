import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, FlatList, RefreshControl, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter, Redirect } from "expo-router";

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

export default function Jobs() {
  const { user } = useAuth();
  const router = useRouter();
  const online = useOnline();
  const [jobs, setJobs] = useState<any[]>([]);
  const [filter, setFilter] = useState("all");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [usingCache, setUsingCache] = useState(false);

  // Phase 30 → Phase 47 follow-up: admins still land on the unified calendar
  // (they can reach the workstream list via nav), but TECHNICIANS and
  // customers land on the JobCard workstream list here — that's the layout
  // the workstream card (LEFT pills / RIGHT photo / VIEW DETAILS overlay)
  // was designed for.
  const isCustomer = user?.role === "customer";
  const isAdmin = user?.role === "admin" || user?.role === "super_admin";
  if (isAdmin) {
    return <Redirect href="/(app)/schedule/calendar" />;
  }

  const load = useCallback(async (f: string) => {
    const cacheKey = `${user?.role}_${user?.id}`;
    try {
      // Sync any photos & mutations captured while offline, then fetch fresh data.
      await flushPendingMutations().catch(() => {});
      await flushPendingPhotos().catch(() => {});
      const q = f === "all" ? "" : `?status=${f}`;
      const data = await api.get(`/jobs${q}`);
      setJobs(data);
      setUsingCache(false);
      if (f === "all") cacheJobs(cacheKey, data);
    } catch (e) {
      // Offline / server unreachable — fall back to cached schedule.
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

  const isAdminOrig = false; // dead — customer branch only reaches here after Phase 30 redirect.

  return (
    <View style={styles.root}>
      <Header
        title={isCustomer ? "My Services" : "Jobs"}
        subtitle={isAdmin ? "All service jobs" : isCustomer ? "Your upcoming & past services" : "Your assigned jobs"}
        right={
          isAdmin ? (
            <IconButton icon="add" onPress={() => router.push("/job/new")} testID="add-job-button" />
          ) : isCustomer ? (
            <NotificationBell />
          ) : undefined
        }
      />
      {usingCache ? <OfflineBanner /> : null}
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
          renderItem={({ item }) => <JobCard job={item} testID={`job-card-${item.id}`} />}
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
