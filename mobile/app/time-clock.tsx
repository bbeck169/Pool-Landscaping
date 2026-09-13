/**
 * Phase 16A + G1 · Technician Time Clock (Expo web + native).
 *
 * Foreground GPS clock-in against today's assigned jobs. Ping loop sends a
 * location-ping every 30s while a shift is open; pings queue in AsyncStorage
 * when offline and flush on reconnect. Background pings (app closed) require
 * a native build with `expo-task-manager` — this screen relies on foreground
 * only, keeping web/Expo-Go compatible.
 *
 * G1: Adds batched GPS pings via POST /api/gps/pings (gpsTracker service).
 * Auto-starts on clock-in, stops+flushes on clock-out. Shows green pill.
 */
import React, { useEffect, useRef, useState, useCallback } from "react";
import { View, Text, StyleSheet, Pressable, ScrollView, Alert } from 'react-native';
import * as Location from "expo-location";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import NetInfo from "@react-native-community/netinfo";

import { useAuth } from "@/src/auth";
import { api, getAuthToken } from "@/src/api";
import { offlineWrite } from "@/src/services/offlineWrite";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { useToast } from "@/src/components/ToastProvider";
import BreadcrumbBar from "@/src/components/nav/BreadcrumbBar";
import * as GpsTracker from "@/src/services/gpsTracker";
import { formatCustomerName } from "@/src/utils/formatCustomerName";

const QUEUE_KEY = "workforce_ping_queue_v1";
const PING_MS = 30_000;

export default function TimeClockScreen() {
  const { user } = useAuth();
  const { showToast } = useToast();
  const router = useRouter();

  const [jobs, setJobs] = useState<any[]>([]);
  const [entry, setEntry] = useState<any>(null);      // open time_entry
  const [selectedJob, setSelectedJob] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [shiftSeconds, setShiftSeconds] = useState(0);
  const [breakOpen, setBreakOpen] = useState(false);
  const [inGeofence, setInGeofence] = useState<boolean | null>(null);
  const [gpsActive, setGpsActive] = useState(false);
  const pingTimer = useRef<any>(null);
  const shiftTimer = useRef<any>(null);

  // Load assigned jobs + last known open entry (best-effort).
  useEffect(() => {
    (async () => {
      try {
        const list = await api.get("/jobs");
        const mine = (list || []).filter((j: any) =>
          ["pending", "active", "in_progress"].includes(j.status));
        setJobs(mine);
        if (!selectedJob && mine.length) setSelectedJob(mine[0].id);
      } catch { /* ignore */ }
      try {
        const ts = await api.get("/workforce/timesheets?status=open");
        const open = (ts || []).find((r: any) => !r.clock_out_at);
        if (open) {
          setEntry(open);
          setSelectedJob(open.job_id);
        }
      } catch { /* ignore */ }
    })();
    // Mount-only: ``selectedJob`` is read as the initial-default check,
    // not to react to updates. Re-running this effect on selection
    // changes would clobber the picker with the first job again.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /* G1 — Best-effort resume GPS tracker when screen mounts with open shift */
  useEffect(() => {
    if (entry && !GpsTracker.isTracking()) {
      (async () => {
        const token = await getAuthToken();
        const ok = await GpsTracker.startTracking(token).catch(() => false);
        setGpsActive(!!ok);
      })();
    }
    if (!entry && GpsTracker.isTracking()) {
      GpsTracker.stopTracking();
      setGpsActive(false);
    }
    // Deliberately keyed on entry?.id: we only re-run when the active
    // shift row changes identity, not on every autosave that mutates
    // the entry object.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entry?.id]);

  /* G1 — Stop callback when server returns 409 */
  useEffect(() => {
    GpsTracker.onTrackingStopped(() => setGpsActive(false));
  }, []);

  /** Persist offline ping queue */
  const enqueuePing = async (payload: any) => {
    const raw = await AsyncStorage.getItem(QUEUE_KEY);
    const arr = raw ? JSON.parse(raw) : [];
    arr.push(payload);
    await AsyncStorage.setItem(QUEUE_KEY, JSON.stringify(arr));
  };

  const flushQueue = useCallback(async () => {
    try {
      const raw = await AsyncStorage.getItem(QUEUE_KEY);
      if (!raw) return;
      const arr = JSON.parse(raw);
      if (!arr.length) return;
      const remaining: any[] = [];
      for (const p of arr) {
        try {
          await api.post("/workforce/location-ping", p);
        } catch {
          remaining.push(p);
        }
      }
      await AsyncStorage.setItem(QUEUE_KEY, JSON.stringify(remaining));
    } catch { /* ignore */ }
  }, []);

  // Flush on reconnect
  useEffect(() => {
    const unsub = NetInfo.addEventListener((st) => { if (st.isConnected) flushQueue(); });
    return () => unsub();
  }, [flushQueue]);

  // Shift timer + ping loop while clocked in
  useEffect(() => {
    if (!entry) {
      if (shiftTimer.current) clearInterval(shiftTimer.current);
      if (pingTimer.current) clearInterval(pingTimer.current);
      setShiftSeconds(0);
      return;
    }
    const started = new Date(entry.clock_in_at).getTime();
    shiftTimer.current = setInterval(() => {
      setShiftSeconds(Math.max(0, Math.floor((Date.now() - started) / 1000)));
    }, 1000);
    // Kick a ping loop
    const doPing = async () => {
      try {
        const pos = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
        const payload = {
          entry_id: entry.id,
          lat: pos.coords.latitude,
          lng: pos.coords.longitude,
          speed: pos.coords.speed ?? undefined,
          heading: pos.coords.heading ?? undefined,
          battery: undefined,
        };
        try {
          await api.post("/workforce/location-ping", payload);
        } catch {
          await enqueuePing(payload);
        }
      } catch { /* GPS unavailable this tick */ }
    };
    doPing();  // kick immediately
    pingTimer.current = setInterval(doPing, PING_MS);
    return () => {
      if (shiftTimer.current) clearInterval(shiftTimer.current);
      if (pingTimer.current) clearInterval(pingTimer.current);
    };
    // Deliberately keyed on entry?.id — the ping/timer loop only
    // needs to restart when a new shift begins, not on every entry
    // field mutation (e.g. autosaved elapsed time).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entry?.id]);

  const requestGps = async (): Promise<{ lat: number; lng: number; acc?: number } | null> => {
    const { status } = await Location.requestForegroundPermissionsAsync();
    if (status !== "granted") {
      Alert.alert("Location required", "Please allow GPS to clock in.");
      return null;
    }
    const pos = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.High });
    return { lat: pos.coords.latitude, lng: pos.coords.longitude, acc: pos.coords.accuracy || undefined };
  };

  const clockIn = async () => {
    if (!selectedJob) { Alert.alert("Pick a job"); return; }
    setBusy(true);
    try {
      const g = await requestGps();
      if (!g) return;
      const body = { job_id: selectedJob, lat: g.lat, lng: g.lng, accuracy: g.acc };
      const { data: r, queued } = await offlineWrite({
        op_type: "clock.punch",
        entity_id: selectedJob,
        endpoint: "/workforce/clock-in",
        method: "POST",
        payload: body,
        onlineFn: () => api.post("/workforce/clock-in", body),
      });
      if (r) {
        setEntry(r);
        setInGeofence(!r.out_of_geofence);
      }
      if (queued) showToast("Clock-in queued — will sync when online.", "info");
      // G1: Start GPS batch tracker
      const token = await getAuthToken();
      GpsTracker.startTracking(token).then((ok) => setGpsActive(ok)).catch(() => {});
    } catch (e: any) {
      Alert.alert("Clock-in failed", e?.message || "Try again");
    } finally { setBusy(false); }
  };

  const clockOut = async () => {
    if (!entry) return;
    setBusy(true);
    try {
      // G1: Stop GPS tracker and flush remaining pings before clock-out
      await GpsTracker.stopTracking();
      setGpsActive(false);
      await GpsTracker.flushBufferedPings().catch(() => {});

      const g = await requestGps();
      if (!g) return;
      const r = await api.post("/workforce/clock-out", {
        entry_id: entry.id, lat: g.lat, lng: g.lng,
      });
      Alert.alert("Shift closed",
        `Duration: ${(r.duration_minutes / 60).toFixed(2)}h · Mileage: ${(r.mileage_miles || 0).toFixed(2)}mi`);
      setEntry(null);
      setBreakOpen(false);
      setInGeofence(null);
    } catch (e: any) {
      Alert.alert("Clock-out failed", e?.message || "Try again");
    } finally { setBusy(false); }
  };

  const toggleBreak = async () => {
    if (!entry) return;
    try {
      const path = breakOpen ? "/workforce/break/end" : "/workforce/break/start";
      await api.post(path, { entry_id: entry.id });
      setBreakOpen((b) => !b);
    } catch (e: any) { Alert.alert("Break failed", e?.message || "Try again"); }
  };

  const goTimesheet = () => router.push("/timesheets" as any);

  const hh = Math.floor(shiftSeconds / 3600);
  const mm = Math.floor((shiftSeconds % 3600) / 60);
  const ss = shiftSeconds % 60;
  const timeStr = `${hh.toString().padStart(2, "0")}:${mm.toString().padStart(2, "0")}:${ss.toString().padStart(2, "0")}`;

  return (
    <ScrollView style={styles.root} contentContainerStyle={{ padding: spacing.lg, paddingBottom: 120 }}
                testID="time-clock-screen">
      <Text style={styles.h1}>Time Clock</Text>
      <BreadcrumbBar title="Time Clock" />
      <Text style={styles.hint}>
        Clock into a job to start GPS tracking. Foreground pings only —
        background pings require a native build.
      </Text>

      {!entry ? (
        <View style={styles.card} testID="time-clock-idle-card">
          <Text style={styles.h2}>Select a job</Text>
          {jobs.length === 0 ? (
            <Text style={styles.muted}>No assigned jobs today.</Text>
          ) : (
            jobs.map((j) => (
              <Pressable key={j.id} onPress={() => setSelectedJob(j.id)}
                         style={[styles.jobRow, selectedJob === j.id && styles.jobRowActive]}
                         testID={`time-clock-job-${j.id}`}>
                <Ionicons name="briefcase-outline" size={18}
                          color={selectedJob === j.id ? colors.brand : colors.muted}/>
                <View style={{ marginLeft: spacing.sm, flex: 1 }}>
                  <Text style={styles.jobTitle}>{j.title}</Text>
                  <Text style={styles.jobSub}>{formatCustomerName(j) || j.address}</Text>
                </View>
              </Pressable>
            ))
          )}
          <Pressable onPress={clockIn} disabled={busy || !selectedJob}
                     style={[styles.bigBtn, styles.btnPrimary]}
                     testID="time-clock-clock-in-btn">
            <Ionicons name="log-in-outline" size={22} color="#fff"/>
            <Text style={styles.bigBtnLabel}>{busy ? "Clocking in…" : "Clock In"}</Text>
          </Pressable>
        </View>
      ) : (
        <View style={styles.card} testID="time-clock-open-card">
          <View style={styles.pillRow}>
            <View style={[styles.pill, { backgroundColor: colors.brandTertiary }]}>
              <Text style={[styles.pillText, { color: colors.onBrandTertiary }]}>
                {entry.job_title || "Active shift"}
              </Text>
            </View>
            {inGeofence !== null && (
              <View style={[styles.pill,
                            { backgroundColor: inGeofence ? "#DCFCE7" : "#FEE2E2" }]}
                    testID="time-clock-geofence-pill">
                <Text style={[styles.pillText,
                              { color: inGeofence ? colors.success : colors.error }]}>
                  {inGeofence ? "In site" : "Out of site"}
                </Text>
              </View>
            )}
            {gpsActive && (
              <View style={[styles.pill, styles.gpsPill]}
                    testID="time-clock-gps-tracking-pill">
                <Ionicons name="navigate" size={10} color="#16A34A" />
                <Text style={[styles.pillText, { color: "#16A34A", marginLeft: 4 }]}>
                  Location tracking on
                </Text>
              </View>
            )}
          </View>
          <Text style={styles.timerBig} testID="time-clock-timer">{timeStr}</Text>

          <View style={{ flexDirection: "row", gap: spacing.md, marginTop: spacing.lg }}>
            <Pressable onPress={toggleBreak}
                       style={[styles.btnGhost, { flex: 1 }]}
                       testID="time-clock-break-btn">
              <Ionicons name={breakOpen ? "play" : "pause"} size={18} color={colors.brand}/>
              <Text style={styles.btnGhostLabel}>{breakOpen ? "End break" : "Start break"}</Text>
            </Pressable>
            <Pressable onPress={clockOut} disabled={busy}
                       style={[styles.bigBtn, styles.btnDanger, { flex: 1 }]}
                       testID="time-clock-clock-out-btn">
              <Ionicons name="log-out-outline" size={20} color="#fff"/>
              <Text style={styles.bigBtnLabel}>{busy ? "Clocking out…" : "Clock out"}</Text>
            </Pressable>
          </View>
        </View>
      )}

      <Pressable onPress={goTimesheet} style={styles.linkRow} testID="time-clock-view-timesheet">
        <Text style={styles.link}>View my timesheet →</Text>
      </Pressable>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  h1: { fontFamily: font.bold, fontSize: 26, color: colors.onSurface, marginBottom: 4 },
  hint: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginBottom: spacing.lg },
  h2: { fontFamily: font.semibold, fontSize: 16, color: colors.onSurface, marginBottom: spacing.md },
  card: { backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.lg,
          borderWidth: 1, borderColor: colors.border, marginBottom: spacing.lg },
  jobRow: { flexDirection: "row", alignItems: "center", padding: spacing.md,
            borderRadius: radius.md, borderWidth: 1, borderColor: colors.border,
            marginBottom: spacing.sm, backgroundColor: colors.surface },
  jobRowActive: { borderColor: colors.brand, backgroundColor: colors.brandTertiary },
  jobTitle: { fontFamily: font.semibold, fontSize: 14, color: colors.onSurface },
  jobSub: { fontFamily: font.regular, fontSize: 12, color: colors.muted, marginTop: 2 },
  muted: { fontFamily: font.regular, fontSize: 14, color: colors.muted },
  bigBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center",
            paddingVertical: spacing.md, borderRadius: radius.md, gap: spacing.sm,
            marginTop: spacing.lg },
  btnPrimary: { backgroundColor: colors.brand },
  btnDanger: { backgroundColor: colors.error },
  bigBtnLabel: { color: "#fff", fontFamily: font.bold, fontSize: 16 },
  btnGhost: { flexDirection: "row", alignItems: "center", justifyContent: "center",
              paddingVertical: spacing.md, borderRadius: radius.md, gap: spacing.sm,
              backgroundColor: colors.surfaceSecondary,
              borderWidth: 1, borderColor: colors.border },
  btnGhostLabel: { color: colors.onSurface, fontFamily: font.semibold, fontSize: 14 },
  pillRow: { flexDirection: "row", gap: spacing.sm, marginBottom: spacing.md, flexWrap: "wrap" },
  pill: { paddingHorizontal: spacing.md, paddingVertical: 4, borderRadius: 999 },
  pillText: { fontFamily: font.bold, fontSize: 11, textTransform: "uppercase", letterSpacing: 0.5 },
  gpsPill: { backgroundColor: "#DCFCE7", flexDirection: "row", alignItems: "center" },
  timerBig: { fontFamily: font.bold, fontSize: 48, textAlign: "center",
              color: colors.onSurface, marginVertical: spacing.md, letterSpacing: 2 },
  linkRow: { alignItems: "center", padding: spacing.md },
  link: { fontFamily: font.semibold, fontSize: 14, color: colors.brand },
});
