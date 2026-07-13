import React, { useCallback, useState } from "react";
import { View, StyleSheet, FlatList, RefreshControl } from "react-native";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing } from "@/src/theme";
import { Loading, EmptyState } from "@/src/components/ui";
import { Header, JobCard, FilterRow } from "@/src/components/widgets";

const FILTERS = [
  { key: "all", label: "All" },
  { key: "requested", label: "Requested" },
  { key: "pending", label: "Pending" },
  { key: "active", label: "Active" },
  { key: "completed", label: "Completed" },
];

export default function PortalServices() {
  const [jobs, setJobs] = useState<any[]>([]);
  const [filter, setFilter] = useState("all");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async (f: string) => {
    try {
      const q = f === "all" ? "" : `?status=${f}`;
      setJobs(await api.get(`/jobs${q}`));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(filter); }, [filter, load]));

  return (
    <View style={styles.root}>
      <Header title="Service Records" subtitle="Your upcoming & past services" back />
      <FilterRow options={FILTERS} value={filter} onChange={setFilter} testID="portal-services-filter" />
      {loading ? (
        <Loading testID="portal-services-loading" />
      ) : jobs.length === 0 ? (
        <EmptyState icon="clipboard-outline" title="No services yet" subtitle="Your service history will appear here." testID="portal-services-empty" />
      ) : (
        <FlatList
          testID="portal-services-list"
          data={jobs}
          keyExtractor={(i) => i.id}
          contentContainerStyle={{ padding: spacing.lg, paddingTop: spacing.sm, paddingBottom: spacing["3xl"] }}
          renderItem={({ item }) => <JobCard job={item} testID={`portal-service-${item.id}`} />}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(filter); }} />}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({ root: { flex: 1, backgroundColor: colors.surfaceSecondary } });
