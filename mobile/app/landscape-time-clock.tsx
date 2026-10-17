/**
 * Phase 46.3 — Landscaping Time Clock (Expo mobile + web).
 *
 * Wraps /api/timeclock/{punch,today,summary}. Landscaping-only per
 * backend RBAC. Uses `expo-location` for GPS (falls back to
 * `navigator.geolocation` on web via a small adapter below).
 */
import React, { useEffect, useMemo, useState } from "react";
import { View, Text, StyleSheet, Pressable, ScrollView } from 'react-native';
import * as Location from "expo-location";
import { Ionicons } from "@expo/vector-icons";
import { Redirect } from "expo-router";
import { useAuth } from "@/src/auth";
import { isPoolTechWithoutTimeClock } from "@/src/lib/timeClockVisibility";
import { api } from "@/src/api";
import { offlineWrite } from "@/src/services/offlineWrite";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";

type Punch = {
  id: string;
  punch_type: "in" | "out";
  timestamp: string;
  lat: number | null;
  lng: number | null;
  accuracy_m: number | null;
  source: string;
  geo_denied: boolean;
};
type Today = { clocked_in: boolean; seconds: number; punches: Punch[] };
type Summary = { total_seconds: number; days: { day: string; seconds: number }[]; punches: Punch[] };

function weekBoundsIso() {
  const d = new Date();
  const day = d.getDay();
  const diff = (day + 6) % 7;
  const start = new Date(d); start.setDate(start.getDate() - diff);
  const end = new Date(start); end.setDate(end.getDate() + 6);
  return { start: start.toISOString().slice(0, 10), end: end.toISOString().slice(0, 10) };
}

function fmtHms(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds || 0));
  const hh = Math.floor(s / 3600);
  const mm = Math.floor((s % 3600) / 60);
  const ss = s % 60;
  return `${String(hh).padStart(2, "0")}:${String(mm).padStart(2, "0")}:${String(ss).padStart(2, "0")}`;
}
function fmtTime(iso: string) {
  try { return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }); }
  catch { return "—"; }
}

async function readGeo(): Promise<{ lat: number | null; lng: number | null; accuracy_m: number | null; geo_denied: boolean }> {
  try {
    const perm = await Location.requestForegroundPermissionsAsync();
    if (perm.status !== "granted") {
      return { lat: null, lng: null, accuracy_m: null, geo_denied: true };
    }
    const pos = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
    return {
      lat: pos.coords.latitude,
      lng: pos.coords.longitude,
      accuracy_m: pos.coords.accuracy ?? null,
      geo_denied: false,
    };
  } catch {
    return { lat: null, lng: null, accuracy_m: null, geo_denied: true };
  }
}

/**
 * TD-64 Phase 2b · pool techs (technician without the Time Clock designation)
 * have NO Time Clock surface — deep links bounce to the schedule (web
 * LandscapingTimeClock `<Navigate to="/schedule" replace>` parity).
 * Admins/managers unaffected. Separate wrapper keeps the screen's hooks stable.
 */
export default function LandscapingTimeClockRoute() {
  const { user } = useAuth();
  if (isPoolTechWithoutTimeClock(user as any)) return <Redirect href="/(app)/schedule/calendar" />;
  return <LandscapingTimeClockScreen />;
}

function LandscapingTimeClockScreen() {
  const { user } = useAuth();
  const [today, setToday] = useState<Today | null>(null);
  const [week, setWeek] = useState<Summary | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  const load = async () => {
    setError(null);
    try {
      const t: Today = await api.get("/timeclock/mine-today");
      setToday(t);
    } catch (e: any) {
      setError(e?.message || "Failed to load today");
      setToday(null);
    }
    try {
      const { start, end } = weekBoundsIso();
      const s: Summary = await api.get(`/timeclock/mine-summary?start=${start}&end=${end}`);
      setWeek(s);
    } catch { setWeek(null); }
  };

  useEffect(() => { load(); }, []);

  useEffect(() => {
    if (!today?.clocked_in) return;
    const int = setInterval(() => setTick((n) => n + 1), 1000);
    return () => clearInterval(int);
  }, [today?.clocked_in]);

  const openIn = useMemo(() => {
    let last: Punch | null = null;
    for (const p of today?.punches || []) {
      if (p.punch_type === "in") last = p;
      else if (p.punch_type === "out" && last) last = null;
    }
    return last;
  }, [today]);

  const runningSeconds = useMemo(() => {
    const base = today?.seconds || 0;
    if (!today?.clocked_in || !openIn) return base;
    const started = new Date(openIn.timestamp).getTime();
    return base + Math.max(0, Math.floor((Date.now() - started) / 1000));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [today, openIn, tick]);

  const doPunch = async (type: "in" | "out") => {
    setBusy(true);
    setError(null);
    try {
      const geo = await readGeo();
      const payload = {
        punch_type: type,
        lat: geo.lat,
        lng: geo.lng,
        accuracy_m: geo.accuracy_m,
        source: "mobile",
        geo_denied: geo.geo_denied,
      };
      const { queued } = await offlineWrite({
        op_type: "clock.landscape",
        entity_id: "self",
        endpoint: "/timeclock/punch",
        method: "POST",
        payload,
        onlineFn: () => api.post("/timeclock/punch", payload),
      });
      if (!queued) await load();
      else setError("Queued offline — will sync later.");
    } catch (e: any) {
      setError(e?.message || "Punch failed");
    } finally { setBusy(false); }
  };

  const blocked = /landscaping/i.test(error || "") && /available/i.test(error || "");

  return (
    <ScrollView
      style={styles.root}
      contentContainerStyle={{ padding: spacing.lg, paddingBottom: 120 }}
      testID="landscape-time-clock-screen"
    >
      <Text style={styles.h1}>Time Clock</Text>
      <Text style={styles.hint}>Landscaping crew · clock in / out with GPS.</Text>

      {blocked ? (
        <View style={styles.blockedCard} testID="landscape-time-clock-blocked">
          <Ionicons name="lock-closed-outline" size={18} color="#854D0E" />
          <Text style={styles.blockedText}>
            This screen is available for the landscaping crew only.
          </Text>
        </View>
      ) : (
        <>
          <View style={styles.card} testID="landscape-time-clock-card">
            <Text style={styles.h2}>Today</Text>
            <View style={styles.timerRow}>
              <Text style={styles.timer} testID="landscape-time-clock-timer">
                {fmtHms(runningSeconds)}
              </Text>
              <View style={[styles.badge,
                today?.clocked_in ? styles.badgeOn : styles.badgeOff]}>
                <Text style={[styles.badgeText,
                  today?.clocked_in ? styles.badgeTextOn : styles.badgeTextOff]}
                  testID="landscape-time-clock-status">
                  {today?.clocked_in ? "Clocked in" : "Off the clock"}
                </Text>
              </View>
            </View>

            <View style={styles.btnRow}>
              <Pressable
                onPress={() => doPunch("in")}
                disabled={busy || !!today?.clocked_in}
                style={[
                  styles.btn,
                  today?.clocked_in ? styles.btnDisabled : styles.btnPrimary,
                  { flex: 1 },
                ]}
                testID="landscape-time-clock-punch-in"
              >
                <Ionicons name="log-in-outline" size={18} color={today?.clocked_in ? colors.muted : "#fff"} />
                <Text style={[styles.btnText,
                  today?.clocked_in ? styles.btnTextDisabled : styles.btnTextPrimary]}>Clock In</Text>
              </Pressable>
              <Pressable
                onPress={() => doPunch("out")}
                disabled={busy || !today?.clocked_in}
                style={[
                  styles.btn,
                  !today?.clocked_in ? styles.btnDisabled : styles.btnDanger,
                  { flex: 1 },
                ]}
                testID="landscape-time-clock-punch-out"
              >
                <Ionicons name="log-out-outline" size={18} color={!today?.clocked_in ? colors.muted : "#fff"} />
                <Text style={[styles.btnText,
                  !today?.clocked_in ? styles.btnTextDisabled : styles.btnTextPrimary]}>Clock Out</Text>
              </Pressable>
            </View>
            {error && !blocked ? (
              <Text style={styles.errText} testID="landscape-time-clock-error">{error}</Text>
            ) : null}
          </View>

          <View style={styles.card} testID="landscape-time-clock-week">
            <View style={styles.weekHeader}>
              <Text style={styles.h2}>This week</Text>
              <Text style={styles.weekTotal}>{fmtHms(week?.total_seconds || 0)}</Text>
            </View>
            <View style={styles.daysWrap}>
              {(week?.days || []).map((d) => (
                <View key={d.day} style={styles.dayCell}
                      testID={`landscape-time-clock-day-${d.day}`}>
                  <Text style={styles.dayLabel}>{d.day}</Text>
                  <Text style={styles.dayHours}>{fmtHms(d.seconds)}</Text>
                </View>
              ))}
              {(week?.days || []).length === 0 && (
                <Text style={styles.muted}>No punches yet this week.</Text>
              )}
            </View>
          </View>

          <View style={styles.card} testID="landscape-time-clock-recent">
            <Text style={styles.h2}>Today&apos;s punches</Text>
            {(today?.punches || []).length === 0 ? (
              <Text style={styles.muted}>No punches yet today.</Text>
            ) : (today?.punches || []).map((p) => (
              <View key={p.id} style={styles.punchRow}
                    testID={`landscape-time-clock-punch-${p.id}`}>
                <Ionicons name={p.punch_type === "in" ? "arrow-down-circle" : "arrow-up-circle"}
                          size={16} color={p.punch_type === "in" ? colors.brand : "#DC2626"} />
                <Text style={styles.punchText}>
                  {p.punch_type === "in" ? "In" : "Out"} · {fmtTime(p.timestamp)}
                </Text>
                <Text style={styles.punchMeta}>
                  {p.geo_denied || p.lat == null
                    ? "no GPS"
                    : `±${Math.round(p.accuracy_m || 0)}m`}
                </Text>
              </View>
            ))}
          </View>
        </>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  h1: { fontFamily: font.bold, fontSize: 26, color: colors.onSurface, marginBottom: 4 },
  h2: { fontFamily: font.bold, fontSize: 13, color: colors.muted, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: spacing.sm },
  hint: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginBottom: spacing.lg },
  card: { backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.lg,
          borderWidth: 1, borderColor: colors.border, marginBottom: spacing.md },
  timerRow: { flexDirection: "row", alignItems: "baseline", gap: spacing.md, marginBottom: spacing.md },
  timer: { fontFamily: font.bold, fontSize: 40, color: colors.onSurface, letterSpacing: 2 },
  badge: { paddingHorizontal: spacing.sm, paddingVertical: 4, borderRadius: 999 },
  badgeOn: { backgroundColor: "#DCFCE7" },
  badgeOff: { backgroundColor: colors.surfaceSecondary },
  badgeText: { fontFamily: font.bold, fontSize: 11, textTransform: "uppercase", letterSpacing: 0.5 },
  badgeTextOn: { color: "#166534" },
  badgeTextOff: { color: colors.muted },
  btnRow: { flexDirection: "row", gap: spacing.md },
  btn: { flexDirection: "row", alignItems: "center", justifyContent: "center",
         paddingVertical: 12, borderRadius: radius.md, gap: 8 },
  btnPrimary: { backgroundColor: colors.brand },
  btnDanger: { backgroundColor: "#DC2626" },
  btnDisabled: { backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border },
  btnText: { fontFamily: font.bold, fontSize: 14 },
  btnTextPrimary: { color: "#fff" },
  btnTextDisabled: { color: colors.muted },
  errText: { marginTop: spacing.sm, backgroundColor: "#FEF2F2", color: "#B91C1C",
             borderColor: "#FECACA", borderWidth: 1, padding: spacing.sm,
             borderRadius: radius.sm, fontSize: 12, fontFamily: font.semibold },
  weekHeader: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: spacing.sm },
  weekTotal: { fontFamily: font.bold, fontSize: 15, color: colors.onSurface },
  daysWrap: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  dayCell: { minWidth: 100, backgroundColor: colors.surfaceSecondary,
             borderRadius: radius.sm, paddingHorizontal: 10, paddingVertical: 6,
             borderWidth: 1, borderColor: colors.border },
  dayLabel: { fontFamily: font.regular, fontSize: 11, color: colors.muted },
  dayHours: { fontFamily: font.bold, fontSize: 13, color: colors.onSurface, marginTop: 2 },
  muted: { fontFamily: font.regular, fontSize: 12, color: colors.muted },
  punchRow: { flexDirection: "row", alignItems: "center", gap: 8,
              backgroundColor: colors.surfaceSecondary, paddingHorizontal: 10, paddingVertical: 8,
              borderRadius: radius.sm, marginBottom: 4 },
  punchText: { flex: 1, fontFamily: font.semibold, fontSize: 13, color: colors.onSurface },
  punchMeta: { fontFamily: font.regular, fontSize: 11, color: colors.muted },
  blockedCard: { flexDirection: "row", alignItems: "center", gap: spacing.sm,
                 backgroundColor: "#FEF9C3", borderColor: "#FDE68A", borderWidth: 1,
                 padding: spacing.md, borderRadius: radius.md },
  blockedText: { flex: 1, fontFamily: font.semibold, fontSize: 13, color: "#854D0E" },
});
