import React, { useCallback, useMemo, useState } from "react";
import { View, Text, StyleSheet, ScrollView, RefreshControl, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";

import { api } from "@/src/api";
import { offlineWrite } from "@/src/services/offlineWrite";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Loading, StatusChip, Sheet } from "@/src/components/ui";
import { Header, IconButton } from "@/src/components/widgets";
import { formatCustomerName } from "@/src/utils/formatCustomerName";

function ymd(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
function prettyDate(iso: string) {
  try {
    const d = new Date(iso + "T00:00:00");
    return d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
  } catch {
    return iso;
  }
}
function timeOf(iso?: string) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    if (iso.length <= 10 || isNaN(d.getTime())) return "";
    return d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
  } catch {
    return "";
  }
}

export default function Dispatch() {
  const router = useRouter();
  const [date, setDate] = useState(ymd(new Date()));
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [assign, setAssign] = useState<any>(null); // job being assigned

  const load = useCallback(async (d: string) => {
    try {
      setData(await api.get(`/dispatch?date=${d}`));
    } catch {
      setData(null);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(date); }, [date, load]));

  const shift = (days: number) => {
    const d = new Date(date + "T00:00:00");
    d.setDate(d.getDate() + days);
    setDate(ymd(d));
    setLoading(true);
  };

  const doAssign = async (technician_id: string) => {
    if (!assign) return;
    const body = { technician_id };
    await offlineWrite({
      op_type: "job.assign",
      entity_id: assign.id,
      endpoint: `/jobs/${assign.id}`,
      method: "PUT",
      payload: body,
      onlineFn: () => api.put(`/jobs/${assign.id}`, body),
    });
    setAssign(null);
    load(date);
  };

  const totalJobs = useMemo(() => {
    if (!data) return 0;
    return (data.unassigned?.length || 0) + (data.columns || []).reduce((s: number, c: any) => s + c.jobs.length, 0);
  }, [data]);

  return (
    <View style={styles.root}>
      <Header title="Dispatch" back subtitle={`${totalJobs} job${totalJobs === 1 ? "" : "s"} scheduled`} right={<IconButton icon="swap-horizontal" onPress={() => router.push("/coverage")} testID="dispatch-coverage" />} />

      <View style={styles.dateBar}>
        <Pressable onPress={() => shift(-1)} style={styles.dateNav} testID="dispatch-prev-day" hitSlop={8}>
          <Ionicons name="chevron-back" size={20} color={colors.brand} />
        </Pressable>
        <View style={styles.dateCenter}>
          <Text style={styles.dateText}>{prettyDate(date)}</Text>
          {date === ymd(new Date()) ? <Text style={styles.todayTag}>Today</Text> : (
            <Pressable onPress={() => { setDate(ymd(new Date())); setLoading(true); }} hitSlop={6}>
              <Text style={styles.jumpToday}>Jump to today</Text>
            </Pressable>
          )}
        </View>
        <Pressable onPress={() => shift(1)} style={styles.dateNav} testID="dispatch-next-day" hitSlop={8}>
          <Ionicons name="chevron-forward" size={20} color={colors.brand} />
        </Pressable>
      </View>

      {loading ? (
        <Loading testID="dispatch-loading" />
      ) : (
        <ScrollView
          testID="dispatch-scroll"
          contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(date); }} />}
        >
          {/* Unassigned bucket */}
          <View style={[styles.column, styles.unassignedCol]}>
            <View style={styles.colHeader}>
              <Ionicons name="alert-circle" size={16} color={colors.warning} />
              <Text style={styles.colTitle}>Unassigned</Text>
              <Text style={styles.colCount}>{data?.unassigned?.length || 0}</Text>
            </View>
            {(data?.unassigned || []).length === 0 ? (
              <Text style={styles.emptyCol}>All jobs assigned 🎉</Text>
            ) : (
              (data.unassigned || []).map((j: any) => (
                <DispatchJob key={j.id} job={j} onPress={() => router.push(`/job/${j.id}`)} onAssign={() => setAssign(j)} />
              ))
            )}
          </View>

          {/* Technician columns */}
          {(data?.columns || []).map((c: any) => (
            <View key={c.technician_id} style={styles.column}>
              <View style={styles.colHeader}>
                <View style={styles.techAvatar}>
                  <Text style={styles.techInitial}>{c.technician_name?.charAt(0)?.toUpperCase()}</Text>
                </View>
                <Text style={styles.colTitle} numberOfLines={1}>{c.technician_name}</Text>
                <Text style={styles.colCount}>{c.jobs.length}</Text>
              </View>
              {c.jobs.length === 0 ? (
                <Text style={styles.emptyCol}>No jobs today</Text>
              ) : (
                c.jobs.map((j: any) => (
                  <DispatchJob key={j.id} job={j} onPress={() => router.push(`/job/${j.id}`)} onAssign={() => setAssign(j)} />
                ))
              )}
            </View>
          ))}
        </ScrollView>
      )}

      <Sheet visible={!!assign} onClose={() => setAssign(null)} title="Assign technician" testID="assign-sheet">
        {assign ? (
          <>
            <Text style={styles.assignJob}>{assign.title}</Text>
            <Text style={styles.assignSub}>{formatCustomerName(assign)}</Text>
            <View style={{ height: spacing.md }} />
            {(data?.columns || []).map((c: any) => (
              <Pressable key={c.technician_id} style={styles.assignRow} onPress={() => doAssign(c.technician_id)} testID={`assign-${c.technician_id}`}>
                <View style={styles.techAvatar}>
                  <Text style={styles.techInitial}>{c.technician_name?.charAt(0)?.toUpperCase()}</Text>
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.assignName}>{c.technician_name}</Text>
                  <Text style={styles.assignMeta}>{c.jobs.length} job{c.jobs.length === 1 ? "" : "s"} today · {c.specialty || "Field crew"}</Text>
                </View>
                <Ionicons name="chevron-forward" size={18} color={colors.muted} />
              </Pressable>
            ))}
          </>
        ) : null}
      </Sheet>
    </View>
  );
}

function DispatchJob({ job, onPress, onAssign }: { job: any; onPress: () => void; onAssign: () => void }) {
  return (
    <Pressable style={styles.jobRow} onPress={onPress} testID={`dispatch-job-${job.id}`}>
      <View style={styles.timePill}>
        <Text style={styles.timeText}>{timeOf(job.scheduled_date) || "—"}</Text>
      </View>
      <View style={{ flex: 1 }}>
        <Text style={styles.jobTitle} numberOfLines={1}>{job.title}</Text>
        <Text style={styles.jobSub} numberOfLines={1}>{job.address || formatCustomerName(job)}</Text>
      </View>
      {!job.technician_id ? (
        <Pressable style={styles.assignBtn} onPress={onAssign} testID={`dispatch-assign-${job.id}`} hitSlop={6}>
          <Ionicons name="person-add-outline" size={14} color="#fff" />
          <Text style={styles.assignBtnText}>Assign</Text>
        </Pressable>
      ) : (
        <StatusChip status={job.status} />
      )}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  dateBar: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", backgroundColor: colors.surface, paddingHorizontal: spacing.lg, paddingVertical: spacing.md, borderBottomWidth: 1, borderBottomColor: colors.border },
  dateNav: { width: 40, height: 40, borderRadius: radius.md, backgroundColor: colors.brandTertiary, alignItems: "center", justifyContent: "center" },
  dateCenter: { alignItems: "center" },
  dateText: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  todayTag: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.brand, marginTop: 1 },
  jumpToday: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.brand, marginTop: 1 },
  column: { backgroundColor: colors.surface, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.border, padding: spacing.md, marginBottom: spacing.md },
  unassignedCol: { borderColor: "#FDE68A", backgroundColor: "#FFFBEB" },
  colHeader: { flexDirection: "row", alignItems: "center", gap: spacing.sm, marginBottom: spacing.sm },
  colTitle: { flex: 1, fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  colCount: { fontFamily: font.bold, fontSize: fontSize.base, color: colors.muted, backgroundColor: colors.surfaceSecondary, minWidth: 24, textAlign: "center", paddingHorizontal: 6, paddingVertical: 2, borderRadius: radius.pill, overflow: "hidden" },
  emptyCol: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, paddingVertical: spacing.sm },
  jobRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm, paddingVertical: spacing.sm, borderTopWidth: 1, borderTopColor: colors.divider },
  timePill: { minWidth: 54, alignItems: "center", backgroundColor: colors.surfaceSecondary, paddingVertical: 4, paddingHorizontal: 6, borderRadius: radius.sm },
  timeText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
  jobTitle: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  jobSub: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 1 },
  assignBtn: { flexDirection: "row", alignItems: "center", gap: 4, backgroundColor: colors.brand, paddingHorizontal: 10, height: 30, borderRadius: radius.pill },
  assignBtnText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: "#fff" },
  techAvatar: { width: 30, height: 30, borderRadius: 15, backgroundColor: colors.brandTertiary, alignItems: "center", justifyContent: "center" },
  techInitial: { fontFamily: font.bold, fontSize: fontSize.base, color: colors.brand },
  assignJob: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  assignSub: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted, marginTop: 2 },
  assignRow: { flexDirection: "row", alignItems: "center", gap: spacing.md, paddingVertical: spacing.md, borderTopWidth: 1, borderTopColor: colors.divider },
  assignName: { fontFamily: font.semibold, fontSize: fontSize.lg, color: colors.onSurface },
  assignMeta: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 1 },
});
