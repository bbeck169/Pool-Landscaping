/**
 * Phase 16C · Tech Today Schedule (mobile).
 * Vertical hourly timeline with route ETA chips between consecutive jobs.
 * Uses Google Directions API via EXPO_PUBLIC_GOOGLE_API_KEY.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
  const isTech = user?.role === "technician";
  const [autoToast, setAutoToast] = useState<any>(null);
  const autoToastRef = useRef<any>(null);
  const [cancelling, setCancelling] = useState(false);
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

  // Phase 19 · Auto-clock-in via GPS (tech only). Foreground watcher.
  useFocusEffect(useCallback(() => {
    if (!isTech) return;
    let sub: any = null;
    let cancelled = false;
    let lastCall = 0;
    (async () => {
      try {
        const Location = await import("expo-location");
        const perm = await Location.requestForegroundPermissionsAsync();
        if (!perm.granted) return;
        sub = await Location.watchPositionAsync(
          { accuracy: Location.Accuracy.High, timeInterval: 15000, distanceInterval: 25 },
          async (pos) => {
            const nowMs = Date.now();
            if (nowMs - lastCall < 15000) return;
            if (autoToastRef.current || cancelled) return;
            lastCall = nowMs;
            try {
              const r = await api.post("/workforce/auto-clock-in", {
                lat: pos.coords.latitude, lng: pos.coords.longitude,
                accuracy: pos.coords.accuracy,
              });
              if (r?.clocked_in) {
                setAutoToast(r);
                autoToastRef.current = r;
                setTimeout(() => {
                  if (autoToastRef.current) {
                    router.push(`/(app)/service-report/${r.job_id}` as any);
                    autoToastRef.current = null;
                    setAutoToast(null);
                  }
                }, 10000);
              }
            } catch (e) { /* stay silent — manual clock-in still works */ }
          },
        );
      } catch (e) { /* Location module unavailable in Expo Go on desktop — ignore */ }
    })();
    return () => { cancelled = true; if (sub?.remove) sub.remove(); };
  }, [isTech, router]));

  const cancelAutoClockIn = async () => {
    if (!autoToast) return;
    setCancelling(true);
    try {
      await api.post(`/workforce/cancel-auto-clock-in/${autoToast.entry_id}`, {});
    } catch (e: any) {
      Alert.alert("Cancel failed", e?.message || "");
    } finally {
      autoToastRef.current = null;
      setAutoToast(null);
      setCancelling(false);
    }
  };
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

  // ── Optimize Route (Phase 20A.1) ────────────────────────────────────
  const [optimizedIds, setOptimizedIds] = useState<string[] | null>(null);
  const [optimizeMeta, setOptimizeMeta] = useState<any>(null);
  const [optimizing, setOptimizing] = useState(false);

  const haversineM = (aLat: any, aLng: any, bLat: any, bLng: any): number => {
    if (aLat == null || aLng == null || bLat == null || bLng == null) return 0;
    const R = 6371000, toRad = (d: number) => (d * Math.PI) / 180;
    const dLat = toRad(bLat - aLat), dLng = toRad(bLng - aLng);
    const s = Math.sin(dLat / 2) ** 2 +
              Math.cos(toRad(aLat)) * Math.cos(toRad(bLat)) * Math.sin(dLng / 2) ** 2;
    return 2 * R * Math.asin(Math.sqrt(s));
  };

  const originalDistanceM = useMemo(() => {
    let sum = 0;
    for (let i = 1; i < jobItems.length; i++) {
      const a: any = jobItems[i - 1], b: any = jobItems[i];
      sum += haversineM(a.site_lat ?? a.lat, a.site_lng ?? a.lng,
                        b.site_lat ?? b.lat, b.site_lng ?? b.lng);
    }
    return sum;
  }, [jobItems]);

  const orderedJobItems = useMemo(() => {
    if (!optimizedIds || optimizedIds.length === 0) return jobItems;
    const byId: Record<string, any> = {};
    jobItems.forEach((j: any) => { byId[j.id] = j; });
    const out = optimizedIds.map((id) => byId[id]).filter(Boolean);
    const seen = new Set(optimizedIds);
    jobItems.forEach((j: any) => { if (!seen.has(j.id)) out.push(j); });
    return out;
  }, [jobItems, optimizedIds]);

  const handleOptimize = async () => {
    if (optimizing) return;
    setOptimizing(true);
    try {
      let coords: any = {};
      try {
        const perm = await Location.requestForegroundPermissionsAsync();
        if (perm.granted) {
          const p = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
          coords = { start_lat: p.coords.latitude, start_lng: p.coords.longitude };
        }
      } catch {}
      const r: any = await api.post("/schedule/optimize-route",
                                     { date: selectedDate, ...coords });
      const ids: string[] = r?.ordered_job_ids || [];
      if (ids.length === 0) {
        Alert.alert("Optimize", "Need at least 2 jobs with GPS coordinates to optimize.");
        return;
      }
      setOptimizedIds(ids);
      const total_m: number = r.total_distance_m || 0;
      const total_s: number = r.total_duration_s || 0;
      const saved_m = Math.max(0, originalDistanceM - total_m);
      const saved_s = Math.round(saved_m / (35 * 1000 / 3600));
      setOptimizeMeta({ total_m, total_s, saved_m, saved_s, cached: !!r.cached });
    } catch (e: any) {
      Alert.alert("Optimize failed", e?.message || "");
    } finally { setOptimizing(false); }
  };

  const resetOrder = () => { setOptimizedIds(null); setOptimizeMeta(null); };

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
      {autoToast && (
        <View style={autoToastStyles.wrap} testID="auto-clockin-toast">
          <Text style={autoToastStyles.head}>▶ Arrived — clocking in now</Text>
          <Text style={autoToastStyles.title}>
            {autoToast.customer_name || autoToast.job_title}
          </Text>
          <Text style={autoToastStyles.sub}>
            {autoToast.distance_m != null ? `${Math.round(autoToast.distance_m)}m from site · ` : ""}
            Opening report in 10s…
          </Text>
          <View style={autoToastStyles.row}>
            <Pressable onPress={cancelAutoClockIn} disabled={cancelling}
                       style={autoToastStyles.cancelBtn}
                       testID="auto-clockin-cancel">
              <Text style={autoToastStyles.cancelText}>
                {cancelling ? "Cancelling…" : "Cancel"}
              </Text>
            </Pressable>
            <Pressable onPress={() => {
                         autoToastRef.current = null;
                         router.push(`/(app)/service-report/${autoToast.job_id}` as any);
                         setAutoToast(null);
                       }}
                       style={autoToastStyles.openBtn}
                       testID="auto-clockin-open-now">
              <Text style={autoToastStyles.openText}>Open now →</Text>
            </Pressable>
          </View>
        </View>
      )}
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

        {/* Optimize Route (Phase 20A.1) */}
        {jobItems.length >= 2 && (
          <View style={styles.optimizeRow}>
            <Pressable onPress={handleOptimize} disabled={optimizing}
                       style={[styles.optimizeBtn, optimizing && { opacity: 0.6 }]}
                       testID="schedule-optimize-route">
              <Ionicons name="git-network-outline" size={14} color="#fff"/>
              <Text style={styles.optimizeText}>
                {optimizing ? "Optimizing…" : "Optimize Route"}
              </Text>
            </Pressable>
            {optimizedIds && (
              <Pressable onPress={resetOrder} style={styles.resetBtn}
                         testID="schedule-reset-order">
                <Ionicons name="refresh" size={14} color={colors.onSurface}/>
                <Text style={styles.resetText}>Reset</Text>
              </Pressable>
            )}
          </View>
        )}
        {optimizeMeta && (
          <View style={styles.savedChip} testID="schedule-optimize-chip">
            <Ionicons name="checkmark-circle" size={14} color="#065F46"/>
            <Text style={styles.savedText}>
              Saved {(optimizeMeta.saved_m / 1609.344).toFixed(1)} mi ·{" "}
              {Math.max(1, Math.round(optimizeMeta.saved_s / 60))} min
              {optimizeMeta.cached ? " · cached" : ""}
            </Text>
          </View>
        )}

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
          <ScheduleCardList jobs={orderedJobItems} tz={data.tz}
                            isTech={isTech}
                            onOpen={(id: string) => router.push(`/job/${id}` as any)}
                            onOpenReport={(id: string) => router.push(`/(app)/service-report/${id}` as any)}
                            onClockIn={async (job: any) => {
                              let geo: any = {};
                              try {
                                const Location = await import("expo-location");
                                const perm = await Location.requestForegroundPermissionsAsync();
                                if (perm.granted) {
                                  const p = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.High });
                                  geo = { lat: p.coords.latitude, lng: p.coords.longitude,
                                          accuracy: p.coords.accuracy };
                                }
                              } catch {}
                              try {
                                await api.post("/workforce/clock-in", { job_id: job.id, ...geo });
                              } catch (e: any) {
                                if (!/open shift/i.test(e?.message || "")) {
                                  Alert.alert("Clock-in failed", e?.message || "");
                                  return;
                                }
                              }
                              router.push(`/(app)/service-report/${job.id}` as any);
                            }}/>
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
                                 fontSize: 10, fontFamily: font.semibold, color: colors.muted }}>
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
  emptyTitle: { fontFamily: font.semibold, fontSize: 16, color: colors.onSurface },
  emptyText: { fontFamily: font.regular, fontSize: 13, color: colors.muted, textAlign: "center" },
  emptyBtn: { backgroundColor: colors.brand, paddingHorizontal: spacing.lg,
              paddingVertical: spacing.md, borderRadius: radius.md, marginTop: spacing.sm },
  emptyBtnLbl: { color: "#fff", fontFamily: font.bold, fontSize: 14 },
  timeline: { position: "relative", backgroundColor: colors.surface, borderRadius: radius.lg,
              borderWidth: 1, borderColor: colors.border, padding: 8 },
  jobCard: { position: "absolute", right: 12, borderRadius: radius.md, padding: spacing.sm,
             backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  jobTime: { fontFamily: font.bold, fontSize: 11, color: colors.brand, marginBottom: 2 },
  jobTitle: { fontFamily: font.semibold, fontSize: 13, color: colors.onSurface },
  jobCustomer: { fontFamily: font.regular, fontSize: 12, color: colors.muted },
  jobAddr: { flex: 1, fontFamily: font.regular, fontSize: 11, color: colors.onSurfaceSecondary },
  jobLink: { fontFamily: font.semibold, fontSize: 11, color: colors.brand },
  shift: { position: "absolute", left: 54, width: 12, borderWidth: 1, borderRadius: 4 },
  break: { position: "absolute", left: 40, width: 10, borderWidth: 1, borderRadius: 3,
           backgroundColor: "#FEF3C7", borderColor: "#92400E" },
  nowLine: { position: "absolute", left: 52, right: 0, height: 2, backgroundColor: colors.error, zIndex: 5 },
  nowDot: { position: "absolute", left: -6, top: -4, width: 10, height: 10, borderRadius: 999,
             backgroundColor: colors.error },
  legChip: { flexDirection: "row", alignItems: "center", gap: 4,
             backgroundColor: colors.brandTertiary, paddingHorizontal: 8, paddingVertical: 2,
             borderRadius: 999 },
  legChipText: { fontFamily: font.semibold, fontSize: 11, color: colors.onBrandTertiary },
  toggle: { flexDirection: "row", borderWidth: 1, borderColor: colors.border,
             borderRadius: radius.md, overflow: "hidden", alignSelf: "flex-start",
             marginBottom: spacing.md },
  toggleBtn: { paddingHorizontal: spacing.md, paddingVertical: spacing.sm },
  toggleBtnActive: { backgroundColor: colors.brand },
  toggleLbl: { fontFamily: font.bold, fontSize: 11, color: colors.onSurfaceSecondary,
                letterSpacing: 0.5 },
  toggleLblActive: { color: "#fff" },
  optimizeRow: { flexDirection: "row", alignItems: "center", gap: 8, marginBottom: spacing.md, flexWrap: "wrap" },
  optimizeBtn: { flexDirection: "row", alignItems: "center", gap: 6,
                 backgroundColor: colors.brand, paddingHorizontal: spacing.md,
                 paddingVertical: spacing.sm, borderRadius: radius.md },
  optimizeText: { fontFamily: font.bold, fontSize: fontSize.sm, color: "#fff" },
  resetBtn: { flexDirection: "row", alignItems: "center", gap: 6,
              backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
              paddingHorizontal: spacing.md, paddingVertical: spacing.sm, borderRadius: radius.md },
  resetText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface },
  savedChip: { flexDirection: "row", alignItems: "center", gap: 6,
               backgroundColor: "#ECFDF5", borderWidth: 1, borderColor: "#6EE7B7",
               paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
               borderRadius: radius.md, marginBottom: spacing.md, alignSelf: "flex-start" },
  savedText: { fontFamily: font.bold, fontSize: fontSize.sm, color: "#065F46" },
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
  dateText: { fontFamily: font.semibold, fontSize: 13, color: colors.onSurface },
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

function ScheduleCardList({ jobs, tz, isTech, onOpen, onClockIn, onOpenReport }: any) {
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
                          <Text style={{ fontFamily: font.semibold }}>Notes: </Text>
                          {isExpanded ? notesFull : notesPreview}
                          {notesFull.length > 100 ? (
                            <Text style={{ fontFamily: font.semibold, color: colors.brand }}>
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

              {isTech && (j.status || "").toLowerCase() !== "completed" && (
                <View style={{ flexDirection: "row", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
                  <Pressable
                    onPress={(e: any) => { e.stopPropagation && e.stopPropagation();

const autoToastStyles = StyleSheet.create({
  wrap: {
    marginHorizontal: spacing.md,
    marginTop: spacing.md,
    padding: spacing.md,
    borderRadius: radius.lg,
    backgroundColor: "#0F172A",
  },
  head: {
    color: "#fff",
    fontFamily: font.bold,
    fontSize: 11,
    letterSpacing: 1,
    textTransform: "uppercase",
    opacity: 0.85,
  },
  title: {
    color: "#fff",
    fontFamily: font.bold,
    fontSize: 18,
    marginTop: 4,
  },
  sub: {
    color: "#fff",
    opacity: 0.8,
    fontFamily: font.regular,
    fontSize: 12,
    marginTop: 4,
  },
  row: { flexDirection: "row", gap: 8, marginTop: 10 },
  cancelBtn: {
    backgroundColor: "#fff",
    paddingHorizontal: 14,
    paddingVertical: 7,
    borderRadius: 8,
  },
  cancelText: { color: "#0F172A", fontFamily: font.bold, fontSize: 12 },
  openBtn: {
    backgroundColor: colors.brand,
    paddingHorizontal: 14,
    paddingVertical: 7,
    borderRadius: 8,
  },
  openText: { color: "#fff", fontFamily: font.bold, fontSize: 12 },
});

                                            onClockIn && onClockIn(j); }}
                    style={{ backgroundColor: "#DC2626", paddingHorizontal: 12,
                             paddingVertical: 7, borderRadius: 8 }}
                    testID={`schedule-card-clockin-${j.id}`}>
                    <Text style={{ color: "#fff", fontFamily: font.bold, fontSize: 12 }}>
                      ▶ Clock In & Start
                    </Text>
                  </Pressable>
                  <Pressable
                    onPress={(e: any) => { e.stopPropagation && e.stopPropagation();
                                            onOpenReport && onOpenReport(j.id); }}
                    style={{ backgroundColor: colors.surfaceSecondary,
                             borderWidth: 1, borderColor: colors.border,
                             paddingHorizontal: 12, paddingVertical: 7, borderRadius: 8 }}
                    testID={`schedule-card-open-report-${j.id}`}>
                    <Text style={{ color: colors.onSurface, fontFamily: font.bold, fontSize: 12 }}>
                      Open Report
                    </Text>
                  </Pressable>
                </View>
              )}
            </View>
            <Ionicons name="chevron-forward" size={20} color="#DC2626" style={styles.cardChevron}/>
          </Pressable>
        );
      })}
    </View>
  );
}
