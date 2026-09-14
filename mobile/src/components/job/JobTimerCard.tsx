import React, { useEffect, useRef, useState } from "react";
import { View, Text, StyleSheet, Platform } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import * as Location from "expo-location";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";

// Must stay in sync with backend DEFAULT_ARRIVAL_RADIUS_M in
// backend/routers/gps_auto_start.py (currently 75m).
const ARRIVE_RADIUS_M = 75;

function fmt(s: number) {
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  return h > 0 ? `${h}h ${m}m ${sec}s` : `${m}m ${sec}s`;
}
function distanceM(a: { lat: number; lng: number }, b: { lat: number; lng: number }) {
  const R = 6371000, toRad = (d: number) => (d * Math.PI) / 180;
  const dLat = toRad(b.lat - a.lat), dLng = toRad(b.lng - a.lng);
  const x = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(x));
}

/**
 * Automated job timer. Auto-starts when the tech's GPS enters the job site (75m),
 * and stops automatically when the job is marked completed (handled server-side).
 * No manual start/stop. Foreground detection here; background geofencing runs in a native build.
 */
export default function JobTimerCard({ job, isTech, onStarted }: { job: any; isTech: boolean; onStarted?: () => void }) {
  const started = job?.timer_started_at;
  const stopped = job?.timer_stopped_at;
  const [elapsed, setElapsed] = useState(0);
  const [status, setStatus] = useState<string>(isTech ? "Waiting for arrival…" : "Not started");
  const watchRef = useRef<Location.LocationSubscription | null>(null);
  const arrivedRef = useRef(false);

  // Live elapsed counter while running
  useEffect(() => {
    if (!started || stopped) return;
    const base = new Date(started).getTime();
    const tick = () => setElapsed(Math.max(0, Math.floor((Date.now() - base) / 1000)));
    tick();
    const iv = setInterval(tick, 1000);
    return () => clearInterval(iv);
  }, [started, stopped]);

  // Foreground GPS arrival auto-start (native only; web/Expo Go geocode may be unavailable)
  useEffect(() => {
    let cancelled = false;
    if (!isTech || started || job?.status === "completed" || Platform.OS === "web") return;
    const address = job?.address;
    (async () => {
      try {
        const perm = await Location.getForegroundPermissionsAsync();
        let ok = perm.status === "granted";
        if (!ok && perm.canAskAgain) {
          const req = await Location.requestForegroundPermissionsAsync();
          ok = req.status === "granted";
        }
        if (!ok || cancelled) { setStatus("Enable location for auto-timer"); return; }
        // Resolve the job site coordinates (stored or geocoded from the address)
        let site = job?.site_lat && job?.site_lng ? { lat: job.site_lat, lng: job.site_lng } : null;
        if (!site && address) {
          try {
            const g = await Location.geocodeAsync(address);
            if (g?.[0]) site = { lat: g[0].latitude, lng: g[0].longitude };
          } catch {}
        }
        if (!site || cancelled) { setStatus("Timer starts automatically on arrival"); return; }
        watchRef.current = await Location.watchPositionAsync(
          { accuracy: Location.Accuracy.Balanced, distanceInterval: 20, timeInterval: 10000 },
          async (pos) => {
            if (arrivedRef.current) return;
            const d = distanceM({ lat: pos.coords.latitude, lng: pos.coords.longitude }, site!);
            setStatus(`~${Math.round(d)} m away — auto-starts within ${ARRIVE_RADIUS_M} m`);
            if (d <= ARRIVE_RADIUS_M) {
              arrivedRef.current = true;
              try {
                await api.post(`/jobs/${job.id}/arrive`, {
                  lat: pos.coords.latitude, lng: pos.coords.longitude, site_lat: site!.lat, site_lng: site!.lng,
                });
                onStarted?.();
              } catch {}
            }
          }
        );
      } catch {
        setStatus("Timer starts automatically on arrival");
      }
    })();
    return () => { cancelled = true; watchRef.current?.remove(); watchRef.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isTech, started, job?.status, job?.id, job?.address]);

  const state = stopped ? "done" : started ? "running" : "idle";
  const color = state === "done" ? "#16A34A" : state === "running" ? "#7C3AED" : colors.muted;

  return (
    <View style={[styles.card, { borderColor: state === "idle" ? colors.border : color }]} testID="job-timer-card">
      <View style={[styles.iconWrap, { backgroundColor: color }]}>
        <Ionicons name={state === "done" ? "checkmark-done" : state === "running" ? "timer" : "timer-outline"} size={20} color="#fff" />
      </View>
      <View style={{ flex: 1 }}>
        <Text style={styles.label}>Automated Job Timer</Text>
        {state === "done" ? (
          <Text style={styles.value} testID="job-timer-value">{fmt(job.timer_duration_seconds || 0)} on-site</Text>
        ) : state === "running" ? (
          <Text style={[styles.value, { color: "#7C3AED" }]} testID="job-timer-value">{fmt(elapsed)} — running</Text>
        ) : (
          <Text style={styles.hint} testID="job-timer-status">{status}</Text>
        )}
        {state !== "idle" ? (
          <Text style={styles.sub}>
            {state === "done" ? "Auto-stopped on completion" : "Auto-started on arrival · stops when completed"}
          </Text>
        ) : (
          <Text style={styles.sub}>Starts on arrival · stops on completion (no manual control)</Text>
        )}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: { flexDirection: "row", alignItems: "center", gap: spacing.md, backgroundColor: colors.surface, borderRadius: radius.md, borderWidth: 1.5, padding: spacing.md, marginTop: spacing.md },
  iconWrap: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center" },
  label: { fontFamily: font.semibold, fontSize: 11, letterSpacing: 0.6, color: colors.onSurfaceSecondary, textTransform: "uppercase" },
  value: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface, marginTop: 2 },
  hint: { fontFamily: font.medium, fontSize: fontSize.base, color: colors.onSurface, marginTop: 2 },
  sub: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
});
