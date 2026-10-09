/**
 * Phase 9-M · Customer profile — lazy "Job History" section
 * (web parity b5c09c9dc · Phase 9d).
 *
 * The profile now loads ``GET /customers/{id}?slim=1`` which omits the
 * embedded ``jobs`` array.  This section is the mobile analogue of a
 * web lazy tab: the header shows the count badge from
 * ``/customers/{id}/summary`` immediately, and jobs are fetched on the
 * FIRST expand via ``GET /jobs?customer_id=&limit=50&offset=0&sort=
 * scheduled_date_desc`` — cached 5 min per (customer, "jobs") through
 * ``useCustomerTabCache``.  "Load more" pages by offset (web P37).
 */
import React, { useState } from "react";
import { View, Text, StyleSheet, Pressable, ActivityIndicator } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { JobCard } from "@/src/components/widgets";
import { useCustomerTabCache } from "@/src/hooks/useCustomerTabCache";

export const CUSTOMER_JOBS_PAGE = 50;

const jobsUrl = (cid: string, offset: number) =>
  `/jobs?customer_id=${encodeURIComponent(cid)}&limit=${CUSTOMER_JOBS_PAGE}&offset=${offset}&sort=scheduled_date_desc`;

type Props = {
  customerId: string;
  /** ``summary.jobs_count`` — null until /summary resolves. */
  count: number | null | undefined;
  /** Offline fallback (cached non-slim profile may still carry jobs). */
  fallbackJobs?: any[];
};

export default function CustomerJobsSection({ customerId, count, fallbackJobs }: Props) {
  const { getOrFetch } = useCustomerTabCache(customerId);
  const [open, setOpen] = useState(false);
  const [jobs, setJobs] = useState<any[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);

  const toggle = async () => {
    const next = !open;
    setOpen(next);
    if (!next) return;
    setLoading(true);
    try {
      const rows = await getOrFetch("jobs", () => api.get(jobsUrl(customerId, 0)));
      setJobs(Array.isArray(rows) ? rows : []);
    } catch {
      setJobs(Array.isArray(fallbackJobs) ? fallbackJobs : []);
    } finally {
      setLoading(false);
    }
  };

  const loadMore = async () => {
    if (!jobs || loadingMore) return;
    setLoadingMore(true);
    try {
      const rows = await api.get(jobsUrl(customerId, jobs.length));
      setJobs((prev) => [...(prev || []), ...(Array.isArray(rows) ? rows : [])]);
    } catch { /* keep what we have */ } finally {
      setLoadingMore(false);
    }
  };

  const badge = typeof count === "number" ? count : jobs ? jobs.length : null;
  const hasMore = !!jobs && jobs.length >= CUSTOMER_JOBS_PAGE
    && (typeof count !== "number" || jobs.length < count);

  return (
    <View testID="customer-jobs-section">
      <Pressable
        onPress={toggle}
        style={s.header}
        testID="customer-jobs-tab"
        accessibilityRole="button"
        accessibilityState={{ expanded: open }}
        accessibilityLabel={open ? "Collapse job history" : "Expand job history"}
      >
        <Text style={s.title}>Job History</Text>
        {badge !== null ? (
          <View style={s.badge}><Text style={s.badgeText} testID="customer-jobs-tab-badge">{badge}</Text></View>
        ) : null}
        <View style={{ flex: 1 }} />
        <Ionicons name={open ? "chevron-up" : "chevron-down"} size={20} color={colors.muted} />
      </Pressable>
      {open ? (
        loading ? (
          <ActivityIndicator color={colors.brand} style={{ marginVertical: spacing.md }} testID="customer-jobs-loading" />
        ) : jobs && jobs.length ? (
          <>
            {jobs.map((j: any) => <JobCard key={j.id} job={j} testID={`customer-job-${j.id}`} />)}
            {hasMore ? (
              <Pressable onPress={loadMore} style={s.more} testID="customer-jobs-load-more" disabled={loadingMore}>
                {loadingMore ? <ActivityIndicator color={colors.brand} /> : <Text style={s.moreText}>Load more</Text>}
              </Pressable>
            ) : null}
          </>
        ) : (
          <Text style={s.empty} testID="customer-jobs-empty">No jobs yet for this customer.</Text>
        )
      ) : null}
    </View>
  );
}

const s = StyleSheet.create({
  header: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    marginTop: spacing.xl, marginBottom: spacing.md, minHeight: 44,
  },
  title: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface },
  badge: {
    minWidth: 26, paddingHorizontal: 8, paddingVertical: 2,
    borderRadius: radius.pill, backgroundColor: colors.brandTertiary, alignItems: "center",
  },
  badgeText: { fontFamily: font.bold, fontSize: fontSize.sm, color: colors.brand },
  empty: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted },
  more: {
    alignItems: "center", justifyContent: "center", minHeight: 44,
    borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, marginTop: spacing.sm,
  },
  moreText: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.brand },
});
