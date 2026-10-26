/**
 * M3c · Schedule Month view (web Ticket W parity). Self-contained: own month anchor
 * + own ≤42-day fetch. READ-ONLY offline: cachedGet with readCache fallback but NO
 * writeThrough — a month payload must never bulk-replace the tech's offline cache.
 * No drag-drop (web drag-less lock).
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { View, Text, Pressable, ScrollView, Modal, ActivityIndicator, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { cachedGet, readCachedWeekJobs } from "@/src/lib/offline/apiCache";
import { colors, font, spacing, radius } from "@/src/theme";
import MarkOpenButton from "@/src/components/schedule/MarkOpenButton";
import { buildMonthGrid, dayKey, groupJobsByDay, monthBorderColor, monthJobsUrl, MONTH_CARD_PREVIEW_LIMIT } from "@/src/lib/monthGrid";

const DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const jobName = (j: any) => j.service_type || j.title || "Job";

type Props = {
  initialDate: Date;
  scopeQuery: string;
  clientFilter: (jobs: any[]) => any[];
  userId?: string;
  onOpenJob: (id: string) => void;
  onOpenDay?: (d: Date) => void;
};

function MonthCard({ job, onPress }: { job: any; onPress: () => void }) {
  return (
    <Pressable onPress={onPress} style={[st.card, { borderLeftColor: monthBorderColor(job.status) }]} testID={`month-card-${job.id}`}>
      <Text style={st.cardTitle} numberOfLines={1} testID={`month-card-${job.id}-jobname`}>{jobName(job)}</Text>
      <Text style={st.cardSub} numberOfLines={1} testID={`month-card-${job.id}-customername`}>{job.customer_name || "—"}</Text>
    </Pressable>
  );
}

export default function ScheduleMonthView({ initialDate, scopeQuery, clientFilter, userId, onOpenJob, onOpenDay }: Props) {
  const [anchor, setAnchor] = useState(() => new Date(initialDate.getFullYear(), initialDate.getMonth(), 1));
  const [jobs, setJobs] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [reloadKey, setReloadKey] = useState(0);
  const [sheetDay, setSheetDay] = useState<string | null>(null);
  const url = monthJobsUrl(anchor, scopeQuery);

  useEffect(() => {
    const ac = new AbortController();
    setLoading(true); setErr("");
    cachedGet<any>(url, { readCache: async () => (userId ? await readCachedWeekJobs(userId) : []), signal: ac.signal })
      .then((d) => { if (!ac.signal.aborted) setJobs(Array.isArray(d) ? d : d?.items || d?.data || []); })
      .catch((e) => { if (!ac.signal.aborted) setErr(e?.message || "Failed to load month"); })
      .finally(() => { if (!ac.signal.aborted) setLoading(false); });
    return () => ac.abort();
  }, [url, userId, reloadKey]);

  const { weeks } = useMemo(() => buildMonthGrid(anchor), [anchor]);
  const byDay = useMemo(() => groupJobsByDay(clientFilter(jobs)), [jobs, clientFilter]);
  const patchLocal = useCallback((p: any) => setJobs((arr) => arr.map((j) => (j.id === p.id ? { ...j, ...p } : j))), []);
  const todayKey = dayKey(new Date());
  const shift = (n: number) => setAnchor((a) => new Date(a.getFullYear(), a.getMonth() + n, 1));
  const title = anchor.toLocaleDateString(undefined, { month: "long", year: "numeric" });
  const open = (id: string) => { setSheetDay(null); onOpenJob(id); };

  return (
    <ScrollView style={{ flex: 1 }} contentContainerStyle={{ paddingBottom: 96 }} testID="schedule-month-view">
      <View style={st.head}>
        <Pressable onPress={() => shift(-1)} style={st.navBtn} hitSlop={6} testID="month-prev"><Ionicons name="chevron-back" size={18} color={colors.onSurface} /></Pressable>
        <Text style={st.title} testID="month-title">{title}</Text>
        <Pressable onPress={() => shift(1)} style={st.navBtn} hitSlop={6} testID="month-next"><Ionicons name="chevron-forward" size={18} color={colors.onSurface} /></Pressable>
        <Pressable onPress={() => setAnchor(new Date(new Date().getFullYear(), new Date().getMonth(), 1))} style={st.todayBtn} testID="month-today"><Text style={st.todayText}>Today</Text></Pressable>
        {loading ? <ActivityIndicator size="small" color={colors.brand} testID="month-loading" /> : null}
      </View>
      {err ? (
        <Pressable onPress={() => setReloadKey((k) => k + 1)} style={st.err} testID="month-error"><Text style={st.errText}>{err} · Tap to retry</Text></Pressable>
      ) : null}
      <View style={st.dowRow}>
        {DOW.map((d, i) => <Text key={d} style={st.dow} testID={`month-dow-${i}`}>{d}</Text>)}
      </View>
      {weeks.map((week, wi) => (
        <View key={wi} style={st.week} testID={`month-week-${wi}`}>
          {week.map((d) => {
            const k = dayKey(d);
            const list = byDay[k] || [];
            const inMonth = d.getMonth() === anchor.getMonth();
            const isToday = k === todayKey;
            const overflow = list.length - MONTH_CARD_PREVIEW_LIMIT;
            return (
              <View key={k} style={[st.cell, !inMonth && st.cellOut]} testID={`month-cell-${k}`}>
                <Pressable onPress={() => onOpenDay?.(d)} style={[st.dayNum, isToday && st.dayNumToday]} testID={`month-day-num-${k}`}>
                  <Text style={[st.dayNumText, !inMonth && { color: colors.muted }, isToday && { color: "#fff", fontFamily: font.bold }]}>{d.getDate()}</Text>
                </Pressable>
                <ScrollView style={st.cellScroll} nestedScrollEnabled>
                  {list.slice(0, MONTH_CARD_PREVIEW_LIMIT).map((j) => <MonthCard key={j.id} job={j} onPress={() => open(j.id)} />)}
                </ScrollView>
                {overflow > 0 ? (
                  <Pressable onPress={() => setSheetDay(k)} style={st.more} hitSlop={4} testID={`month-more-pill-${k}`}>
                    <Text style={st.moreText}>+{overflow} more</Text>
                  </Pressable>
                ) : null}
              </View>
            );
          })}
        </View>
      ))}
      <Modal visible={!!sheetDay} transparent animationType="slide" onRequestClose={() => setSheetDay(null)}>
        <Pressable style={st.backdrop} onPress={() => setSheetDay(null)} testID="month-day-sheet-backdrop" />
        <View style={st.sheet} testID="month-day-sheet">
          <View style={st.sheetHead}>
            <Text style={st.sheetTitle} testID="month-day-sheet-title">
              {sheetDay ? new Date(`${sheetDay}T00:00:00`).toLocaleDateString(undefined, { weekday: "long", month: "short", day: "numeric" }) : ""} · {(sheetDay && byDay[sheetDay]?.length) || 0} visits
            </Text>
            <Pressable onPress={() => setSheetDay(null)} hitSlop={8} testID="month-day-sheet-close"><Ionicons name="close" size={22} color={colors.onSurface} /></Pressable>
          </View>
          <ScrollView>
            {(sheetDay ? byDay[sheetDay] || [] : []).map((j) => (
              <View key={j.id} style={[st.sheetRow, { borderLeftColor: monthBorderColor(j.status) }]}>
                <Pressable onPress={() => open(j.id)} testID={`month-sheet-row-${j.id}`}>
                  <Text style={st.sheetRowTitle} numberOfLines={1}>{jobName(j)}</Text>
                  <Text style={st.sheetRowSub} numberOfLines={1}>{j.customer_name || "—"}{j.status ? ` · ${j.status}` : ""}</Text>
                </Pressable>
                <MarkOpenButton job={j} onPatch={patchLocal} size="xs" />
              </View>
            ))}
          </ScrollView>
        </View>
      </Modal>
    </ScrollView>
  );
}

const st = StyleSheet.create({
  head: { flexDirection: "row", alignItems: "center", gap: spacing.sm, paddingHorizontal: spacing.md, paddingVertical: spacing.sm },
  navBtn: { width: 36, height: 36, borderRadius: 18, alignItems: "center", justifyContent: "center", borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
  title: { flex: 1, textAlign: "center", fontFamily: font.bold, fontSize: 16, color: colors.onSurface },
  todayBtn: { minHeight: 36, paddingHorizontal: 12, borderRadius: radius.pill, backgroundColor: colors.brand, justifyContent: "center" },
  todayText: { fontFamily: font.semibold, fontSize: 12, color: "#fff" },
  err: { marginHorizontal: spacing.md, marginBottom: spacing.sm, padding: spacing.sm, borderRadius: radius.md, backgroundColor: "#FEE2E2" },
  errText: { fontFamily: font.medium, fontSize: 12, color: "#B91C1C" },
  dowRow: { flexDirection: "row", paddingHorizontal: 4 },
  dow: { flex: 1, textAlign: "center", fontFamily: font.semibold, fontSize: 11, color: colors.muted, paddingVertical: 4 },
  week: { flexDirection: "row", paddingHorizontal: 4 },
  cell: { flex: 1, minHeight: 112, borderWidth: StyleSheet.hairlineWidth, borderColor: colors.border, backgroundColor: colors.surface, padding: 2 },
  cellOut: { backgroundColor: colors.surfaceSecondary },
  dayNum: { alignSelf: "flex-start", minWidth: 22, height: 22, borderRadius: 11, alignItems: "center", justifyContent: "center" },
  dayNumToday: { backgroundColor: colors.brand },
  dayNumText: { fontFamily: font.medium, fontSize: 11, color: colors.onSurface },
  cellScroll: { maxHeight: 78 },
  card: { borderLeftWidth: 3, borderRadius: 3, backgroundColor: colors.surfaceSecondary, paddingHorizontal: 2, paddingVertical: 1, marginTop: 2 },
  cardTitle: { fontFamily: font.semibold, fontSize: 9, color: colors.onSurface },
  cardSub: { fontFamily: font.regular, fontSize: 8, color: colors.onSurfaceSecondary },
  more: { marginTop: 2, alignSelf: "flex-start", paddingHorizontal: 4, paddingVertical: 2, borderRadius: radius.pill, backgroundColor: "#E0F2FE" },
  moreText: { fontFamily: font.bold, fontSize: 9, color: colors.brand },
  backdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.35)" },
  sheet: { maxHeight: "70%", backgroundColor: colors.surface, borderTopLeftRadius: 16, borderTopRightRadius: 16, padding: spacing.md },
  sheetHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: spacing.sm },
  sheetTitle: { flex: 1, fontFamily: font.bold, fontSize: 16, color: colors.onSurface },
  sheetRow: { borderLeftWidth: 4, borderRadius: radius.sm, backgroundColor: colors.surfaceSecondary, padding: spacing.sm, marginBottom: spacing.sm, minHeight: 48 },
  sheetRowTitle: { fontFamily: font.semibold, fontSize: 14, color: colors.onSurface },
  sheetRowSub: { fontFamily: font.regular, fontSize: 12, color: colors.onSurfaceSecondary, marginTop: 2 },
});
