/**
 * Phase 49.3 — Landscape Time Clock Widget (mobile).
 *
 * Mirror of the web widget. Renders nothing for non-landscaping users.
 * Mounted at the very top of `mobile/app/(app)/index.tsx`.
 */
import React, { useEffect, useMemo, useState } from "react";
import { View, Text, StyleSheet, Pressable } from "react-native";
import * as Location from "expo-location";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { useAuth } from "@/src/auth";
import { api } from "@/src/api";
import { offlineWrite } from "@/src/services/offlineWrite";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";

function weekBounds() {
  const d = new Date();
  const day = d.getDay();
  const diff = (day + 6) % 7;
  const start = new Date(d); start.setDate(start.getDate() - diff);
  const end = new Date(start); end.setDate(end.getDate() + 6);
  return { start: start.toISOString().slice(0, 10), end: end.toISOString().slice(0, 10) };
}

function fmtHms(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds || 0));
  return `${Math.floor(s / 3600)}h ${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}m`;
}

async function readGeo() {
  try {
    const perm = await Location.requestForegroundPermissionsAsync();
    if (perm.status !== "granted") return { lat: null, lng: null, accuracy_m: null, geo_denied: true };
    const pos = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
    return {
      lat: pos.coords.latitude, lng: pos.coords.longitude,
      accuracy_m: pos.coords.accuracy ?? null, geo_denied: false,
    };
  } catch {
    return { lat: null, lng: null, accuracy_m: null, geo_denied: true };
  }
}

export default function LandscapingClockWidget() {
  const { user } = useAuth();
  const router = useRouter();
  // Phase 56.3 follow-up — mirror the web gate: admins + super_admins
  // should NOT see the timeclock; only landscape/both-dept techs & managers
  // see it. Pool techs / customers / unassigned techs are also hidden.
  const role = String((user as any)?.role || "").toLowerCase();
  const isAdminLike = role === "admin" || role === "super_admin";
  const hasLandscapeDept = ["landscaping", "both"].includes(String((user as any)?.department || "").toLowerCase());
  const isLandscaper = !isAdminLike && hasLandscapeDept;
  const [today, setToday] = useState<any>(null);
  const [week, setWeek] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  // Phase 50.H — landscape techs may attach a shift to a specific job.
  const [assignedJobs, setAssignedJobs] = useState<any[]>([]);
  const [selectedJobId, setSelectedJobId] = useState<string>("");
  const [pickerOpen, setPickerOpen] = useState(false);

  useEffect(() => {
    if (!isLandscaper) return;
    let alive = true;
    (async () => {
      try { const t = await api.get("/timeclock/mine-today"); if (alive) setToday(t); } catch {}
      try {
        const { start, end } = weekBounds();
        const s = await api.get(`/timeclock/mine-summary?start=${start}&end=${end}`);
        if (alive) setWeek(s);
      } catch {}
      try {
        const j: any = await api.get("/timeclock/mine-jobs-today");
        if (alive) setAssignedJobs(j?.items || []);
      } catch {}
    })();
    return () => { alive = false; };
  }, [isLandscaper]);

  useEffect(() => {
    if (!today?.clocked_in) return;
    const int = setInterval(() => setTick((n) => n + 1), 1000);
    return () => clearInterval(int);
  }, [today?.clocked_in]);

  const openInAt = useMemo(() => {
    let last: any = null;
    for (const p of today?.punches || []) {
      if (p.punch_type === "in") last = p;
      else if (p.punch_type === "out" && last) last = null;
    }
    return last?.timestamp || null;
  }, [today]);

  const runningSeconds = useMemo(() => {
    const base = today?.seconds || 0;
    if (!today?.clocked_in || !openInAt) return base;
    return base + Math.max(0, Math.floor((Date.now() - new Date(openInAt).getTime()) / 1000));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [today, openInAt, tick]);

  const doPunch = async () => {
    setBusy(true); setError(null);
    try {
      const geo = await readGeo();
      const punch_type = today?.clocked_in ? "out" : "in";
      const payload = {
        punch_type,
        lat: geo.lat, lng: geo.lng, accuracy_m: geo.accuracy_m,
        source: "mobile", geo_denied: geo.geo_denied,
        job_id: punch_type === "in" ? (selectedJobId || null) : null,
      };
      const { queued } = await offlineWrite({
        op_type: "clock.landscape",
        entity_id: "self",
        endpoint: "/timeclock/punch",
        method: "POST",
        payload,
        onlineFn: () => api.post("/timeclock/punch", payload),
      });
      if (!queued) {
        const t = await api.get("/timeclock/mine-today"); setToday(t);
        const { start, end } = weekBounds();
        try {
          const w = await api.get(`/timeclock/mine-summary?start=${start}&end=${end}`);
          setWeek(w);
        } catch {}
      }
      if (geo.geo_denied) setError("GPS denied — punch recorded without location.");
      if (queued) setError("Queued offline — will sync later.");
    } catch (e: any) {
      setError(e?.message || "Punch failed");
    } finally { setBusy(false); }
  };

  if (!isLandscaper) return null;
  const clocked = !!today?.clocked_in;

  return (
    <View style={[styles.card, clocked && styles.cardOn]} testID="landscape-clock-widget">
      <View style={styles.headerRow}>
        <View style={[styles.icon, clocked ? styles.iconOn : styles.iconOff]}>
          <Ionicons name="time-outline" size={20}
            color={clocked ? "#fff" : colors.onBrandTertiary} />
        </View>
        <View style={{ flex: 1 }}>
          <Text style={styles.status}>
            {clocked ? "On the clock" : "Off the clock"}
          </Text>
          <Text style={styles.timer} testID="landscape-clock-widget-timer">
            {fmtHms(runningSeconds)}
          </Text>
          <Text style={styles.sub}>
            This week: <Text style={styles.subStrong}>{fmtHms(week?.total_seconds || 0)}</Text>
            {"  ·  "}
            <Text
              style={styles.link}
              testID="landscape-clock-widget-open-full"
              onPress={() => router.push("/(app)/landscape-time-clock" as any)}
            >
              Full view
            </Text>
          </Text>
        </View>
      </View>
      <Pressable
        onPress={doPunch}
        disabled={busy}
        style={[styles.btn, clocked ? styles.btnOut : styles.btnIn]}
        testID={clocked ? "landscape-clock-widget-out" : "landscape-clock-widget-in"}
      >
        <Ionicons name={clocked ? "log-out-outline" : "log-in-outline"} size={18} color="#fff" />
        <Text style={styles.btnText}>{clocked ? "Clock Out" : "Clock In"}</Text>
      </Pressable>
      {!clocked && assignedJobs.length > 0 ? (
        <Pressable
          onPress={() => setPickerOpen((v) => !v)}
          style={styles.jobPickBtn}
          testID="landscape-clock-widget-job-picker"
        >
          <Ionicons name="briefcase-outline" size={14} color={colors.onSurface} />
          <Text style={styles.jobPickText} numberOfLines={1}>
            {selectedJobId
              ? `Attached: ${assignedJobs.find((j) => j.id === selectedJobId)?.customer_name || "job"}`
              : "General work (no job)"}
          </Text>
          <Ionicons name={pickerOpen ? "chevron-up" : "chevron-down"} size={14} color={colors.muted} />
        </Pressable>
      ) : null}
      {pickerOpen && !clocked ? (
        <View style={styles.jobList} testID="landscape-clock-widget-job-list">
          <Pressable
            onPress={() => { setSelectedJobId(""); setPickerOpen(false); }}
            style={[styles.jobItem, selectedJobId === "" && styles.jobItemActive]}
            testID="landscape-clock-widget-job-item-none"
          >
            <Text style={styles.jobItemText}>General work (no job)</Text>
          </Pressable>
          {assignedJobs.map((j) => (
            <Pressable
              key={j.id}
              onPress={() => { setSelectedJobId(j.id); setPickerOpen(false); }}
              style={[styles.jobItem, selectedJobId === j.id && styles.jobItemActive]}
              testID={`landscape-clock-widget-job-item-${j.id}`}
            >
              <Text style={styles.jobItemText} numberOfLines={1}>
                {j.customer_name || j.title || "Unnamed job"}
                {j.scheduled_start ? ` @ ${String(j.scheduled_start).slice(11, 16)}` : ""}
              </Text>
            </Pressable>
          ))}
        </View>
      ) : null}
      {error ? (
        <View style={styles.warn} testID="landscape-clock-widget-warning">
          <Ionicons name="warning-outline" size={13} color="#854D0E" />
          <Text style={styles.warnText}>{error}</Text>
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.surface, borderRadius: radius.lg,
    padding: spacing.md, borderWidth: 1, borderColor: colors.border,
    marginBottom: spacing.md,
  },
  cardOn: { backgroundColor: "#DCFCE7", borderColor: "#86EFAC" },
  headerRow: { flexDirection: "row", alignItems: "center", gap: spacing.md, marginBottom: spacing.sm },
  icon: { width: 44, height: 44, borderRadius: radius.md, alignItems: "center", justifyContent: "center" },
  iconOn: { backgroundColor: "#16A34A" },
  iconOff: { backgroundColor: colors.brandTertiary },
  status: { fontFamily: font.bold, fontSize: 10, textTransform: "uppercase", letterSpacing: 0.5, color: colors.muted },
  timer: { fontFamily: font.bold, fontSize: 24, color: colors.onSurface, letterSpacing: 1, marginTop: 1 },
  sub: { fontFamily: font.regular, fontSize: 11, color: colors.muted, marginTop: 2 },
  subStrong: { fontFamily: font.bold, color: colors.onSurface },
  link: { color: colors.brand, textDecorationLine: "underline", fontFamily: font.semibold },
  btn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    paddingVertical: 12, borderRadius: radius.md,
  },
  btnIn: { backgroundColor: colors.brand },
  btnOut: { backgroundColor: "#DC2626" },
  btnText: { fontFamily: font.bold, fontSize: 14, color: "#fff", letterSpacing: 0.5 },
  jobPickBtn: {
    marginTop: spacing.sm,
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 10,
    paddingVertical: 8,
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  jobPickText: { flex: 1, fontFamily: font.semibold, fontSize: 12, color: colors.onSurface },
  jobList: {
    marginTop: 6,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.sm,
    backgroundColor: colors.surface,
    overflow: "hidden",
  },
  jobItem: {
    paddingHorizontal: 10, paddingVertical: 8,
    borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  jobItemActive: { backgroundColor: colors.brandTertiary },
  jobItemText: { fontFamily: font.semibold, fontSize: 12, color: colors.onSurface },
  warn: {
    marginTop: spacing.sm, flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: "#FEF9C3", borderColor: "#FDE68A", borderWidth: 1,
    borderRadius: radius.sm, paddingHorizontal: 10, paddingVertical: 6,
  },
  warnText: { flex: 1, fontFamily: font.semibold, fontSize: 11, color: "#854D0E" },
});
