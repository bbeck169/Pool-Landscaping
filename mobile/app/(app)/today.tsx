/**
 * Phase 16C · Tech Today Schedule (mobile).
 * Vertical hourly timeline with route ETA chips between consecutive jobs.
 * Uses Google Directions API via EXPO_PUBLIC_GOOGLE_API_KEY.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, RefreshControl, Linking, Alert } from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";
import * as Location from "expo-location";
import * as Clipboard from "expo-clipboard";
import DateTimePicker from "@react-native-community/datetimepicker";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { colors, spacing, font, fontSize, radius } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import { Loading } from "@/src/components/ui";

const HOUR_ROW = 84;
const GKEY = process.env.EXPO_PUBLIC_GOOGLE_API_KEY;

function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  } catch { return iso.slice(11, 16); }
}
function fmtDur(sec: number | null | undefined): string {
  if (sec == null) return "—";
  const m = Math.round(sec / 60);
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)}h ${m % 60}m`;
}
function fmtMi(m: number | null | undefined): string {
  return m == null ? "—" : `${(m / 1609.344).toFixed(1)} mi`;
}

async function distanceLeg(from: { lat: number; lng: number },
                            to: { lat: number; lng: number }): Promise<any> {
  if (!GKEY) return null;
  try {
    const url = `https://maps.googleapis.com/maps/api/directions/json?origin=${from.lat},${from.lng}&destination=${to.lat},${to.lng}&mode=driving&key=${GKEY}`;
    const r = await fetch(url);
    const d = await r.json();
    const leg = d?.routes?.[0]?.legs?.[0];
    if (!leg) return null;
    return { distance_meters: leg.distance?.value, duration_seconds: leg.duration?.value };
  } catch { return null; }
}

export default function TodayScheduleScreen() {
  const { user } = useAuth();
  const router = useRouter();
  const [selectedDate, setSelectedDate] = useState<string>(() => new Date().toISOString().slice(0, 10));
  const [showPicker, setShowPicker] = useState(false);
  const [data, setData] = useState<any>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [legMap, setLegMap] = useState<Record<string, any>>({});
  const [firstLeg, setFirstLeg] = useState<any>(null);  // You-are-here → first job

  const load = useCallback(async () => {
    try { setData(await api.get(`/schedule/today?date=${selectedDate}`)); } catch {}
    finally { setRefreshing(false); }
  }, [selectedDate]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  // Hydrate route legs
  useEffect(() => {
    if (!data?.route_legs?.length) return;
    (async () => {
      const merged: Record<string, any> = {};
      const cachePayload: any[] = [];
      for (const l of data.route_legs) {
        if (l.cached && l.duration_seconds != null) {
          merged[`${l.from_job_id}|${l.to_job_id}`] = {
            distance_meters: l.distance_meters,
            duration_seconds: l.duration_seconds,
          };
          continue;
        }
        const r = await distanceLeg(
          { lat: l.from_lat, lng: l.from_lng },
          { lat: l.to_lat, lng: l.to_lng }
        );
        if (r) {
          merged[`${l.from_job_id}|${l.to_job_id}`] = r;
          cachePayload.push({
            from_lat: l.from_lat, from_lng: l.from_lng,
            to_lat: l.to_lat, to_lng: l.to_lng,
            distance_meters: r.distance_meters,
            duration_seconds: r.duration_seconds,
          });
        }
      }
      setLegMap(merged);
      if (cachePayload.length) {
        try { await api.post("/schedule/route-leg", { legs: cachePayload }); } catch {}
      }
    })();
  }, [data]);

  // "You are here → next job" leg
  useEffect(() => {
    if (!data?.items) return;
    const nextJob = data.items.find((it: any) => it.type === "job" && it.lat != null && it.lng != null);
    if (!nextJob) { setFirstLeg(null); return; }
    (async () => {
      try {
        const perm = await Location.getForegroundPermissionsAsync();
        if (!perm.granted) {
          const req = await Location.requestForegroundPermissionsAsync();
          if (!req.granted) { setFirstLeg(null); return; }
        }
        const pos = await Location.getLastKnownPositionAsync() || await Location.getCurrentPositionAsync({});
        const leg = await distanceLeg(
          { lat: pos.coords.latitude, lng: pos.coords.longitude },
          { lat: nextJob.lat, lng: nextJob.lng }
        );
        if (leg) setFirstLeg({ ...leg, to: nextJob });
      } catch { setFirstLeg(null); }
    })();
  }, [data]);

  const items = data?.items || [];
  const [minH, maxH] = useMemo(() => {
    let lo = 6, hi = 20;
    items.forEach((it: any) => {
      const s = it.scheduled_start || it.clock_in_at || it.start;
      if (!s) return;
      try {
        const h = new Date(s).getHours();
        lo = Math.min(lo, h - 1);
        hi = Math.max(hi, h + 1);
      } catch {}
    });
    return [Math.max(0, lo), Math.min(23, hi)];
  }, [items]);

  const yFor = (iso: string | undefined) => {
    if (!iso) return 0;
    try {
      const d = new Date(iso);
      return (d.getHours() + d.getMinutes() / 60 - minH) * HOUR_ROW;
    } catch { return 0; }
  };

  const [now, setNow] = useState(new Date());
  useEffect(() => { const t = setInterval(() => setNow(new Date()), 60000); return () => clearInterval(t); }, []);
  const nowY = (now.getHours() + now.getMinutes() / 60 - minH) * HOUR_ROW;

  const s = data?.summary || {};

  // View mode toggle (list default), persisted per device.
  const [viewMode, setViewMode] = useState<"list" | "timeline">("list");
  useEffect(() => {
    (async () => {
      try {
        const v = await AsyncStorage.getItem("schedule_view_mode");
        if (v === "timeline" || v === "list") setViewMode(v);
      } catch {}
    })();
  }, []);
  const setMode = (m: "list" | "timeline") => {
    setViewMode(m);
    AsyncStorage.setItem("schedule_view_mode", m).catch(() => {});
  };
  const jobItems = useMemo(
    () => items.filter((it: any) => it.type === "job"),
    [items]
  );

  if (!data) {
    return (
      <View style={styles.root}>
        <Header title="Today" subtitle="Your schedule" />
        <Loading testID="today-schedule-loading" />
      </View>
    );
  }

  return (
    <View style={styles.root} testID="today-schedule-screen">
      <Header title="Today's Schedule" subtitle={data?.date || ""} />
      <ScrollView
        contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
        testID="today-schedule-scroll"
      >
        {/* Summary */}
        <View style={styles.summary} testID="schedule-summary">
          <SummaryCell label="Jobs" value={String(s.job_count ?? 0)} />
          <SummaryCell label="Sched." value={`${s.scheduled_hours ?? 0}h`} />
          <SummaryCell label="Clocked" value={s.clocked_in ? "Yes" : "No"} tone={s.clocked_in ? colors.success : colors.muted} />
          <SummaryCell label="Miles" value={String(s.miles_logged_today ?? 0)} />
        </View>

        {/* You are here → next job */}
        {firstLeg && (
          <View style={styles.firstLeg} testID="schedule-first-leg">
            <Ionicons name="location" size={14} color={colors.brand}/>
            <Text style={styles.firstLegText}>
              You → {firstLeg.to.title}: <Text style={{ fontFamily: font.bold }}>{fmtDur(firstLeg.duration_seconds)}</Text> · {fmtMi(firstLeg.distance_meters)}
            </Text>
          </View>
        )}

        {/* View mode toggle */}
        <View style={styles.toggle} testID="schedule-view-toggle">
          {(["list", "timeline"] as const).map((m) => (
            <Pressable key={m} onPress={() => setMode(m)}
                       style={[styles.toggleBtn, viewMode === m ? styles.toggleBtnActive : null]}
                       testID={`schedule-view-${m}`}>
              <Text style={[styles.toggleLbl, viewMode === m ? styles.toggleLblActive : null]}>
                {m.toUpperCase()}
              </Text>
            </Pressable>
          ))}
        </View>

        {/* Date picker — prev / date / next / Today */}
        <View style={styles.dateNav} testID="schedule-date-picker">
          <Pressable onPress={() => {
            const d = new Date(selectedDate + "T12:00:00"); d.setDate(d.getDate() - 1);
            setSelectedDate(d.toISOString().slice(0, 10));
          }} hitSlop={8} style={styles.dateArrow} testID="schedule-date-prev">
            <Ionicons name="chevron-back" size={18} color={colors.onSurface}/>
          </Pressable>
          <Pressable onPress={() => setShowPicker(true)}
                     style={styles.dateCenter} testID="schedule-date-center">
            <Ionicons name="calendar-outline" size={14} color={colors.brand}/>
            <Text style={styles.dateText} numberOfLines={1}>
              {selectedDate === new Date().toISOString().slice(0, 10) ? "Today · " : ""}
              {new Date(selectedDate + "T12:00:00").toLocaleDateString([], {
                weekday: "short", month: "short", day: "numeric",
              })}
            </Text>
          </Pressable>
          <Pressable onPress={() => {
            const d = new Date(selectedDate + "T12:00:00"); d.setDate(d.getDate() + 1);
            setSelectedDate(d.toISOString().slice(0, 10));
          }} hitSlop={8} style={styles.dateArrow} testID="schedule-date-next">
            <Ionicons name="chevron-forward" size={18} color={colors.onSurface}/>
          </Pressable>
          {selectedDate !== new Date().toISOString().slice(0, 10) && (
            <Pressable onPress={() => setSelectedDate(new Date().toISOString().slice(0, 10))}
                       style={styles.datePill} testID="schedule-date-today">
              <Text style={styles.datePillText}>TODAY</Text>
            </Pressable>
          )}
        </View>
        {showPicker && (
          <DateTimePicker
            value={new Date(selectedDate + "T12:00:00")}
            mode="date" display="default"
            onChange={(_, d) => {
              setShowPicker(false);
              if (d) setSelectedDate(d.toISOString().slice(0, 10));
            }}
          />
        )}

        {items.length === 0 && (
          <View style={styles.empty} testID="schedule-empty">
            <Ionicons name="checkmark-done-circle-outline" size={32} color={colors.brand}/>
            <Text style={styles.emptyTitle}>Nothing on the books today.</Text>
            <Text style={styles.emptyText}>Enjoy the breather — or head to Jobs to grab something.</Text>
            <Pressable style={styles.emptyBtn} onPress={() => router.push("/(app)/jobs")} testID="schedule-go-jobs">
              <Text style={styles.emptyBtnLbl}>View jobs</Text>
            </Pressable>
          </View>
        )}

        {items.length > 0 && viewMode === "list" && (
          <ScheduleCardList jobs={jobItems} tz={data.tz} onOpen={(id: string) => router.push(`/job/${id}` as any)} />
        )}

        {items.length > 0 && viewMode === "timeline" && (
          <View style={[styles.timeline, { height: (maxH - minH + 1) * HOUR_ROW }]}>
            {Array.from({ length: (maxH - minH + 1) }).map((_, i) => {
              const hr = minH + i;
              return (
                <React.Fragment key={hr}>
                  <View style={{ position: "absolute", left: 52, right: 0, top: i * HOUR_ROW,
                                 height: 1, backgroundColor: colors.border }}/>
                  <Text style={{ position: "absolute", left: 4, top: i * HOUR_ROW - 8,
                                 fontSize: 10, fontFamily: font.semiBold, color: colors.muted }}>
                    {String(((hr + 11) % 12) + 1)}{hr < 12 ? "a" : "p"}
                  </Text>
                </React.Fragment>
              );
            })}

            {nowY >= 0 && nowY <= (maxH - minH + 1) * HOUR_ROW && (
              <View style={[styles.nowLine, { top: nowY }]} testID="schedule-now-line">
                <View style={styles.nowDot}/>
              </View>
            )}

            {items.map((it: any, i: number) => (
              <TimelineItem key={i} item={it} idx={i} yFor={yFor} router={router} />
            ))}

            {data.route_legs.map((l: any, idx: number) => {
              const fromItem = items.find((it: any) => it.type === "job" && it.id === l.from_job_id);
              const toItem = items.find((it: any) => it.type === "job" && it.id === l.to_job_id);
              if (!fromItem || !toItem) return null;
              const yStart = yFor(fromItem.scheduled_end || fromItem.scheduled_start);
              const yEnd = yFor(toItem.scheduled_start);
              const leg = legMap[`${l.from_job_id}|${l.to_job_id}`] || {};
              return (
                <View key={idx}
                      style={{ position: "absolute", left: 60, right: 12,
                               top: yStart + 4, height: Math.max(20, yEnd - yStart - 8),
                               flexDirection: "row", alignItems: "center", gap: 6 }}
                      testID={`schedule-leg-${l.from_job_id}-${l.to_job_id}`}>
                  <View style={{ borderLeftWidth: 2, borderLeftColor: colors.brandSecondary,
                                 borderStyle: "dashed", height: "100%", marginLeft: 8 }}/>
                  <View style={styles.legChip}>
                    <Ionicons name="car" size={11} color={colors.onBrandTertiary}/>
                    <Text style={styles.legChipText}>
                      {leg.duration_seconds != null
                        ? `${fmtDur(leg.duration_seconds)} · ${fmtMi(leg.distance_meters)}`
                        : "…"}
                    </Text>
                  </View>
                </View>
              );
            })}
          </View>
        )}
      </ScrollView>
    </View>
  );
}

function SummaryCell({ label, value, tone }: any) {
  return (
    <View style={styles.summaryCell}>
      <Text style={[styles.summaryValue, tone ? { color: tone } : null]}>{value}</Text>
      <Text style={styles.summaryLabel}>{label}</Text>
    </View>
  );
}

function TimelineItem({ item, idx, yFor, router }: any) {
  const startIso = item.scheduled_start || item.clock_in_at || item.start;
  const endIso   = item.scheduled_end   || item.clock_out_at || item.end;
  const y = yFor(startIso);
  const yEnd = endIso ? yFor(endIso) : y + 60;
  const height = Math.max(48, yEnd - y);

  if (item.type === "job") {
    return (
      <Pressable style={[styles.jobCard, { top: y, height, left: 72 }]}
                 onPress={() => item.id && router.push(`/job/${item.id}`)}
                 testID={`schedule-job-${item.id}`}>
        <Text style={styles.jobTime}>
          {fmtTime(startIso)}{endIso ? ` – ${fmtTime(endIso)}` : ""}
        </Text>
        <Text style={styles.jobTitle} numberOfLines={1}>{item.title}</Text>
        <Text style={styles.jobCustomer} numberOfLines={1}>{item.customer_name || "—"}</Text>
        {item.address && (
          <View style={{ flexDirection: "row", alignItems: "center", gap: 4, marginTop: 2 }}>
            <Ionicons name="location-outline" size={11} color={colors.muted}/>
            <Text style={styles.jobAddr} numberOfLines={1}>{item.address}</Text>
          </View>
        )}
        {item.lat != null && item.lng != null && (
          <Pressable onPress={() =>
                       Linking.openURL(`https://www.google.com/maps/dir/?api=1&destination=${item.lat},${item.lng}`)}
                     hitSlop={8}
                     testID={`schedule-job-directions-${item.id}`}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 4, marginTop: 4 }}>
              <Ionicons name="navigate" size={11} color={colors.brand}/>
              <Text style={styles.jobLink}>Directions</Text>
            </View>
          </Pressable>
        )}
      </Pressable>
    );
  }

  if (item.type === "shift") {
    return (
      <View style={[styles.shift, { top: y, height: Math.max(24, height),
                                     backgroundColor: item.out_of_geofence ? "#FEE2E2" : "#DCFCE7",
                                     borderColor: item.out_of_geofence ? colors.error : colors.success }]}
            testID={`schedule-shift-${item.entry_id}`}/>
    );
  }
  return (
    <View style={[styles.break, { top: y, height: Math.max(18, height) }]}
          testID={`schedule-break-${item.entry_id}-${idx}`}/>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  summary: { flexDirection: "row", justifyContent: "space-between", marginBottom: spacing.md,
             backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.md,
             borderWidth: 1, borderColor: colors.border },
  summaryCell: { flex: 1, alignItems: "center" },
  summaryValue: { fontFamily: font.bold, fontSize: 20, color: colors.onSurface },
  summaryLabel: { fontFamily: font.regular, fontSize: 10, color: colors.muted,
                   textTransform: "uppercase", letterSpacing: 0.5 },
  firstLeg: { flexDirection: "row", alignItems: "center", gap: 6,
              backgroundColor: colors.brandTertiary,
              padding: spacing.md, borderRadius: radius.md, marginBottom: spacing.md },
  firstLegText: { flex: 1, fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onBrandTertiary },
  empty: { alignItems: "center", padding: spacing["2xl"],
           backgroundColor: colors.surface, borderRadius: radius.lg,
           borderWidth: 1, borderColor: colors.border, gap: spacing.sm },
  emptyTitle: { fontFamily: font.semiBold, fontSize: 16, color: colors.onSurface },
  emptyText: { fontFamily: font.regular, fontSize: 13, color: colors.muted, textAlign: "center" },
  emptyBtn: { backgroundColor: colors.brand, paddingHorizontal: spacing.lg,
              paddingVertical: spacing.md, borderRadius: radius.md, marginTop: spacing.sm },
  emptyBtnLbl: { color: "#fff", fontFamily: font.bold, fontSize: 14 },
  timeline: { position: "relative", backgroundColor: colors.surface, borderRadius: radius.lg,
              borderWidth: 1, borderColor: colors.border, padding: 8 },
  jobCard: { position: "absolute", right: 12, borderRadius: radius.md, padding: spacing.sm,
             backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  jobTime: { fontFamily: font.bold, fontSize: 11, color: colors.brand, marginBottom: 2 },
  jobTitle: { fontFamily: font.semiBold, fontSize: 13, color: colors.onSurface },
  jobCustomer: { fontFamily: font.regular, fontSize: 12, color: colors.muted },
  jobAddr: { flex: 1, fontFamily: font.regular, fontSize: 11, color: colors.onSurfaceSecondary },
  jobLink: { fontFamily: font.semiBold, fontSize: 11, color: colors.brand },
  shift: { position: "absolute", left: 54, width: 12, borderWidth: 1, borderRadius: 4 },
  break: { position: "absolute", left: 40, width: 10, borderWidth: 1, borderRadius: 3,
           backgroundColor: "#FEF3C7", borderColor: "#92400E" },
  nowLine: { position: "absolute", left: 52, right: 0, height: 2, backgroundColor: colors.error, zIndex: 5 },
  nowDot: { position: "absolute", left: -6, top: -4, width: 10, height: 10, borderRadius: 999,
             backgroundColor: colors.error },
  legChip: { flexDirection: "row", alignItems: "center", gap: 4,
             backgroundColor: colors.brandTertiary, paddingHorizontal: 8, paddingVertical: 2,
             borderRadius: 999 },
  legChipText: { fontFamily: font.semiBold, fontSize: 11, color: colors.onBrandTertiary },
  toggle: { flexDirection: "row", borderWidth: 1, borderColor: colors.border,
             borderRadius: radius.md, overflow: "hidden", alignSelf: "flex-start",
             marginBottom: spacing.md },
  toggleBtn: { paddingHorizontal: spacing.md, paddingVertical: spacing.sm },
  toggleBtnActive: { backgroundColor: colors.brand },
  toggleLbl: { fontFamily: font.bold, fontSize: 11, color: colors.onSurfaceSecondary,
                letterSpacing: 0.5 },
  toggleLblActive: { color: "#fff" },
  cardList: { borderRadius: radius.lg, backgroundColor: colors.surface,
               borderWidth: 1, borderColor: colors.border, overflow: "hidden" },
  cardRow: { flexDirection: "row", padding: spacing.md, gap: spacing.sm },
  cardChevron: { color: "#DC2626", marginTop: 4 },
  cardService: { fontFamily: font.bold, fontSize: 12, color: "#DC2626",
                  textTransform: "uppercase", letterSpacing: 0.4 },
  cardCustomer: { fontFamily: font.bold, fontSize: 15, color: colors.onSurface, marginTop: 2 },
  cardAddr: { fontFamily: font.regular, fontSize: 13, color: colors.onSurfaceSecondary },
  cardBH: { fontFamily: font.bold, fontSize: 13, color: colors.onSurface },
  cardStatusPill: { paddingHorizontal: 8, paddingVertical: 2, borderRadius: 999 },
  cardStatusText: { fontFamily: font.bold, fontSize: 10, textTransform: "uppercase",
                     letterSpacing: 0.4 },
  gatePill: { flexDirection: "row", alignItems: "center", gap: 4,
               backgroundColor: "#FEF3C7", borderWidth: 1, borderColor: "#FDE68A",
               paddingHorizontal: 8, paddingVertical: 3, borderRadius: 6 },
  gateText: { fontFamily: font.bold, fontSize: 12, color: "#92400E",
               fontVariant: ["tabular-nums"] },
  notesText: { flex: 1, fontFamily: font.regular, fontSize: 12,
                color: colors.onSurfaceSecondary },
  dateNav: { flexDirection: "row", alignItems: "center", gap: spacing.sm,
              marginBottom: spacing.md },
  dateArrow: { padding: spacing.sm, borderWidth: 1, borderColor: colors.border,
                borderRadius: radius.md, backgroundColor: colors.surface },
  dateCenter: { flex: 1, flexDirection: "row", alignItems: "center",
                 justifyContent: "center", gap: 6, paddingVertical: spacing.md,
                 borderWidth: 1, borderColor: colors.border,
                 borderRadius: radius.md, backgroundColor: colors.surface },
  dateText: { fontFamily: font.semiBold, fontSize: 13, color: colors.onSurface },
  datePill: { backgroundColor: colors.brand, paddingHorizontal: spacing.md,
               paddingVertical: spacing.sm, borderRadius: radius.md },
  datePillText: { color: "#fff", fontFamily: font.bold, fontSize: 10,
                    textTransform: "uppercase", letterSpacing: 0.5 },
});

/* ────────────────────────────────────────────────────────────────────
   Card List — new default per user reference screenshot.
   ──────────────────────────────────────────────────────────────────── */
function billableHours(startIso?: string, endIso?: string): number {
  if (!startIso || !endIso) return 0;
  try {
    return Math.max(0, (new Date(endIso).getTime() - new Date(startIso).getTime()) / 3600_000);
  } catch { return 0; }
}
function cardStatusTone(status?: string) {
  const s = (status || "").toLowerCase();
  if (["completed", "closed", "done"].includes(s))
    return { bg: "#DCFCE7", fg: "#166534", label: s === "closed" ? "Closed" : "Completed" };
  if (["active", "in_progress"].includes(s))
    return { bg: "#FEF3C7", fg: "#92400E", label: "In Progress" };
  if (s === "cancelled")
    return { bg: "#FEE2E2", fg: "#991B1B", label: "Cancelled" };
  return { bg: "#DBEAFE", fg: "#1E40AF", label: "Scheduled" };
}

function ScheduleCardList({ jobs, tz, onOpen }: any) {
  const [checked, setChecked] = useState<Record<string, boolean>>({});
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const toggle = (id: string) => setChecked((s) => ({ ...s, [id]: !s[id] }));
  const toggleExpand = (id: string) => setExpanded((s) => ({ ...s, [id]: !s[id] }));
  const combinedNotes = (j: any) =>
    [j.job_notes, j.access_notes, j.customer_notes].filter(Boolean).join("\n\n");
  const copyCode = async (code: string) => {
    try {
      await Clipboard.setStringAsync(code);
      Alert.alert("Gate code copied", code);
    } catch { /* ignore */ }
  };
  return (
    <View style={styles.cardList} testID="schedule-card-list">
      {jobs.map((j: any, i: number) => {
        const bh = billableHours(j.scheduled_start, j.scheduled_end);
        const tone = cardStatusTone(j.status);
        const isChecked = !!checked[j.id];
        const isExpanded = !!expanded[j.id];
        const notesFull = combinedNotes(j);
        const notesPreview = notesFull.length > 100 ? notesFull.slice(0, 100) + "…" : notesFull;
        const cityLine = [j.city, j.state, j.zip].filter(Boolean).join(", ");
        return (
          <Pressable key={j.id || i} onPress={() => onOpen(j.id)}
                     style={[styles.cardRow, {
                       borderBottomWidth: i < jobs.length - 1 ? 1 : 0,
                       borderBottomColor: colors.border,
                     }]}
                     testID={`schedule-card-${j.id}`}>
            <Pressable onPress={(e) => { e.stopPropagation && e.stopPropagation(); toggle(j.id); }}
                       hitSlop={8}
                       style={{ marginTop: 3 }}
                       testID={`schedule-card-check-${j.id}`}>
              <Ionicons name={isChecked ? "checkbox" : "square-outline"}
                        size={20} color={isChecked ? colors.brand : colors.muted}/>
            </Pressable>
            <View style={{ flex: 1, minWidth: 0 }}>
              <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start", gap: 8 }}>
                <Text style={styles.cardService} numberOfLines={1}
                      testID={`schedule-card-service-${j.id}`}>
                  {j.service_type || j.title || "Service"}
                </Text>
                <View style={[styles.cardStatusPill, { backgroundColor: tone.bg }]}
                      testID={`schedule-card-status-${j.id}`}>
                  <Text style={[styles.cardStatusText, { color: tone.fg }]}>{tone.label}</Text>
                </View>
              </View>
              <Text style={styles.cardCustomer} numberOfLines={1}
                    testID={`schedule-card-customer-${j.id}`}>
                {j.customer_name || "—"}
              </Text>
              <Text style={styles.cardAddr} numberOfLines={1}
                    testID={`schedule-card-address-${j.id}`}>
                {j.address || "—"}
              </Text>
              {cityLine ? (
                <Text style={styles.cardAddr} numberOfLines={1}>{cityLine}</Text>
              ) : null}

              {/* Gate code + notes preview (Phase 16C follow-up) */}
              {(j.gate_code || notesFull) ? (
                <View style={{ marginTop: 6, flexDirection: "row", alignItems: "flex-start",
                                gap: 8, flexWrap: "wrap" }}>
                  {j.gate_code ? (
                    <Pressable onPress={(e) => { e.stopPropagation && e.stopPropagation(); copyCode(j.gate_code); }}
                                hitSlop={4} style={styles.gatePill}
                                testID={`schedule-card-gate-${j.id}`}>
                      <Ionicons name="key" size={11} color="#92400E"/>
                      <Text style={styles.gateText}>{j.gate_code}</Text>
                    </Pressable>
                  ) : null}
                  {notesFull ? (
                    <Pressable onPress={(e) => { e.stopPropagation && e.stopPropagation(); toggleExpand(j.id); }}
                                hitSlop={4} style={{ flex: 1, minWidth: 0 }}
                                testID={`schedule-card-notes-${j.id}`}>
                      <View style={{ flexDirection: "row", alignItems: "flex-start", gap: 4 }}>
                        <Ionicons name="document-text-outline" size={11} color={colors.muted}
                                  style={{ marginTop: 2 }}/>
                        <Text style={styles.notesText} numberOfLines={isExpanded ? 20 : 2}>
                          <Text style={{ fontFamily: font.semiBold }}>Notes: </Text>
                          {isExpanded ? notesFull : notesPreview}
                          {notesFull.length > 100 ? (
                            <Text style={{ fontFamily: font.semiBold, color: colors.brand }}>
                              {isExpanded ? "  less" : "  more"}
                            </Text>
                          ) : null}
                        </Text>
                      </View>
                    </Pressable>
                  ) : null}
                </View>
              ) : null}

              <View style={{ flexDirection: "row", justifyContent: "space-between",
                              alignItems: "center", marginTop: 6 }}>
                <View style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
                  <Ionicons name="calendar-clear-outline" size={13} color={colors.muted}/>
                  <Text style={{ fontFamily: font.regular, fontSize: 11, color: colors.muted }}>
                    {j.scheduled_start
                      ? new Date(j.scheduled_start).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
                      : "No start time"}
                  </Text>
                </View>
                <Text style={styles.cardBH} testID={`schedule-card-bh-${j.id}`}>
                  {bh.toFixed(2)} BH
                </Text>
              </View>
            </View>
            <Ionicons name="chevron-forward" size={20} color="#DC2626" style={styles.cardChevron}/>
          </Pressable>
        );
      })}
    </View>
  );
}
