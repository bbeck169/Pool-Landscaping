/**
 * Phase 29A · Mobile Wave A parity — Dispatch Board.
 *
 * Mobile port of the web `/admin/dispatch` screen. Same endpoints, same
 * behavior. Admin-only (backend also enforces; we hard-gate the UI so techs
 * see a friendly "admins only" state instead of an ugly error).
 *
 * Endpoints hit (all pre-existing, Phase 26 Wave A):
 *   GET  /api/jobs?limit=500          — client filters unassigned + future
 *   GET  /api/dispatch/settings       — auto_assign_on_create + weather flags
 *   GET  /api/dispatch/technician-skills — dedupe by user_id/id (known
 *                                          cosmetic dup issue from P26 polish)
 *   POST /api/dispatch/auto-assign  { job_id } → { tech_name, insertion_cost_meters }
 *   PUT  /api/dispatch/settings     { auto_assign_on_create: bool }
 */
import React, { useCallback, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, Alert,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { writeCache, readCache } from "@/src/services/readCache";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { formatCustomerName } from "@/src/utils/formatCustomerName";
import { Header } from "@/src/components/widgets";
import { TechLoadStrip, TechLoad } from "@/src/components/dispatch/TechLoadStrip";
import { UnroutedPanel, UnroutedPin } from "@/src/components/dispatch/UnroutedPanel";
import { LiveTechPinsWrapper } from "@/src/components/dispatch/LiveTechPinsWrapper";

type Job = {
  id: string;
  scheduled_date?: string | null;
  customer_name?: string;
  technician_id?: string | null;
  assigned_to?: string | null;
  service_type?: string;
  address?: string;
};

type TechSkill = {
  id: string;
  user_id?: string;
  name: string;
  email: string;
  preferred_service_types?: string[];
};

type DispatchSettings = {
  auto_assign_on_create: boolean;
  weather_reschedule_mode: string;
  rain_threshold_pct: number;
  wind_threshold_mph: number;
};

export default function DispatchBoardMobile() {
  const router = useRouter();
  const { user } = useAuth();
  const role = (user?.role as string) || "";
  const isAdmin = role === "admin" || role === "super_admin";

  const [jobs, setJobs] = useState<Job[]>([]);
  const [techs, setTechs] = useState<TechSkill[]>([]);
  const [settings, setSettings] = useState<DispatchSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [busyJob, setBusyJob] = useState<string | null>(null);
  const [bulkBusy, setBulkBusy] = useState(false);
  const [msg, setMsg] = useState<{ text: string; kind: "info" | "err" } | null>(null);
  // Phase 38 · Feb-2026 — Dispatch parity (P1.4). Lightweight board
  // load so we can render TechLoadStrip + UnroutedPanel without a
  // full map. The `/dispatch/board` response drives both.
  const [boardPins, setBoardPins] = useState<any[]>([]);
  const [techDirectory, setTechDirectory] = useState<Record<string, any>>({});
  const [selectedTech, setSelectedTech] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true); setMsg(null);
    try {
      const today = new Date().toISOString().slice(0, 10);
      const [jRes, sRes, tRes, bRes] = await Promise.all([
        api.get("/jobs?limit=500"),
        api.get("/dispatch/settings"),
        api.get("/dispatch/technician-skills"),
        api.get("/dispatch/board?day=all").catch(() => ({ pins: [], tech_directory: {} })),
      ]);
      const arr: Job[] = Array.isArray(jRes) ? jRes : (jRes.items || jRes.data || []);
      setJobs(arr.filter((j) =>
        !j.technician_id && !j.assigned_to
        && (j.scheduled_date || "").slice(0, 10) >= today
      ));
      setSettings(sRes);
      // Dedup techs. The backend returns the same person from both the
      // `technicians` collection and a legacy `users` row with DIFFERENT ids
      // (known Phase 26 polish cosmetic issue — HANDOFF_P26_POLISH.md#40).
      // Since the two rows share the human identity but not any id field, we
      // key by (email → name → id) instead of user_id, and when a duplicate
      // shows up we keep whichever row has more populated skill fields.
      const skillScore = (t: TechSkill) =>
        (t.preferred_service_types?.filter((s) => (s || "").trim()).length || 0);
      const key = (t: TechSkill) => {
        const e = (t.email || "").trim().toLowerCase();
        if (e) return `e:${e}`;
        const n = (t.name || "").trim().toLowerCase();
        if (n) return `n:${n}`;
        return `i:${t.user_id || t.id}`;
      };
      const byKey = new Map<string, TechSkill>();
      for (const t of (tRes.items || []) as TechSkill[]) {
        const k = key(t);
        const existing = byKey.get(k);
        if (!existing || skillScore(t) > skillScore(existing)) {
          byKey.set(k, t);
        }
      }
      setTechs(Array.from(byKey.values()));
      // Phase 38 — hydrate board data for the new sub-panels.
      setBoardPins(Array.isArray((bRes as any)?.pins) ? (bRes as any).pins : []);
      setTechDirectory((bRes as any)?.tech_directory || {});
      // Phase O5 · Cache dispatch board data for offline.
      writeCache("dispatch:board", {
        jobs: arr, techs: Array.from(byKey.values()),
        settings: sRes, boardPins: (bRes as any)?.pins || [], techDirectory: (bRes as any)?.tech_directory || {},
      }).catch(() => {});
    } catch (e: any) {
      // Phase O5 · Offline fallback for dispatch board.
      const cached = await readCache<any>("dispatch:board");
      if (cached) {
        setJobs(cached.jobs || []);
        setTechs(cached.techs || []);
        setSettings(cached.settings || {});
        setBoardPins(cached.boardPins || []);
        setTechDirectory(cached.techDirectory || {});
      } else {
        setMsg({ text: e.message || "Failed to load", kind: "err" });
      }
    } finally { setLoading(false); }
  }, []);

  useFocusEffect(useCallback(() => {
    if (isAdmin) load();
  }, [isAdmin, load]));

  const assignOne = async (jobId: string) => {
    setBusyJob(jobId); setMsg(null);
    try {
      const r = await api.post("/dispatch/auto-assign", { job_id: jobId });
      setMsg({
        text: `Assigned to ${r.tech_name || "tech"} · cost ${Math.round(r.insertion_cost_meters || 0)}m`,
        kind: "info",
      });
      await load();
    } catch (e: any) {
      setMsg({ text: e.message || "Auto-assign failed", kind: "err" });
    } finally { setBusyJob(null); }
  };

  const assignAll = async () => {
    if (jobs.length === 0) return;
    setBulkBusy(true); setMsg(null);
    let ok = 0, fail = 0;
    let firstError = "";
    // FastAPI returns either a plain-string `detail` (HTTPException) or a list
    // of validation-error dicts (422 body). Either way, tease out a single
    // human-readable line so the banner + Alert don't dump raw JSON at the user.
    const errText = (e: any): string => {
      const m = e?.message || "";
      if (!m) return "unknown error";
      // Try to unwrap detail if it looks like JSON-in-a-message.
      try {
        const parsed = JSON.parse(m);
        const d = parsed?.detail ?? parsed;
        if (typeof d === "string") return d;
        if (Array.isArray(d) && d[0]) {
          const first = d[0];
          if (first?.msg) return first.msg;
          return JSON.stringify(first).slice(0, 120);
        }
        return typeof d === "object" ? JSON.stringify(d).slice(0, 120) : String(d);
      } catch { /* not JSON — fall through */ }
      return m;
    };
    for (const j of jobs) {
      try {
        await api.post("/dispatch/auto-assign", { job_id: j.id });
        ok++;
      } catch (e: any) {
        fail++;
        if (!firstError) firstError = errText(e);
      }
    }
    // load() resets `msg` at its start (see the top of this component), so we
    // MUST refresh the list first and set the banner AFTER, otherwise the
    // toast is nuked before it ever paints. In addition, fire a native
    // Alert.alert which survives any state churn — matches the Weather
    // screen's "Scanned N · affected N" idiom.
    await load();
    setBulkBusy(false);
    const summary = fail && firstError
      ? `Bulk: ${ok} assigned · ${fail} failed — first error: ${firstError}`
      : `Bulk: ${ok} assigned · ${fail} failed`;
    setMsg({ text: summary, kind: ok >= fail ? "info" : "err" });
    Alert.alert(
      fail > 0 && ok === 0 ? "Auto-assign failed" : "Auto-assign complete",
      fail > 0 && firstError
        ? `${ok} assigned · ${fail} failed\n\nFirst error: ${firstError}`
        : `${ok} assigned · ${fail} failed`,
    );
  };

  const toggleAuto = async () => {
    if (!settings) return;
    try {
      const r = await api.put("/dispatch/settings",
        { auto_assign_on_create: !settings.auto_assign_on_create });
      setSettings(r);
    } catch (e: any) {
      setMsg({ text: e.message || "Failed", kind: "err" });
    }
  };

  const jobsPreview = useMemo(() => jobs.slice(0, 100), [jobs]);

  // Phase 38 — derive TechLoadStrip data from board pins + directory.
  const techLoads: TechLoad[] = useMemo(() => {
    const bucket = new Map<string, number>();
    for (const p of boardPins) {
      const tid = (p.assigned_tech_ids || [])[0];
      if (!tid) continue;
      bucket.set(tid, (bucket.get(tid) || 0) + 1);
    }
    return Array.from(bucket.entries())
      .map(([tid, drop_count]) => ({
        tech_user_id: tid,
        drop_count,
        name: techDirectory[tid]?.name || tid.slice(0, 8),
        color_hex: techDirectory[tid]?.color_hex,
      }))
      .sort((a, b) => b.drop_count - a.drop_count);
  }, [boardPins, techDirectory]);

  const unroutedPins: UnroutedPin[] = useMemo(() => {
    return boardPins
      .filter((p: any) => !(p.assigned_tech_ids || []).length)
      .map((p: any) => ({
        customer_id: p.customer_id || p.id,
        customer_name: formatCustomerName(p) || p.name || "—",
        service_days: p.service_days,
        category_ids: p.category_ids,
      }));
  }, [boardPins]);

  const openOptimize = useCallback((techUserId: string) => {
    const today = new Date().toISOString().slice(0, 10);
    const name = techDirectory[techUserId]?.name;
    router.push({
      pathname: "/dispatch/optimize",
      params: { tech: techUserId, day: today, techName: name || "" },
    } as any);
  }, [techDirectory, router]);

  const openShiftRoute = useCallback((customerId?: string) => {
    router.push({
      pathname: "/dispatch/shift-route",
      params: {
        source: selectedTech || techLoads[0]?.tech_user_id || "",
        sourceName: techDirectory[selectedTech || techLoads[0]?.tech_user_id]?.name || "",
        customerIds: customerId || "",
        scope: customerId ? "partial" : "whole_route",
      },
    } as any);
  }, [selectedTech, techLoads, techDirectory, router]);

  if (!isAdmin) {
    return (
      <View style={styles.root}>
        <Header title="Dispatch board" />
        <View style={styles.forbid}>
          <Ionicons name="lock-closed-outline" size={28} color={colors.muted} />
          <Text style={styles.forbidTitle}>Admins only</Text>
          <Text style={styles.forbidSub}>Dispatch is an admin surface. Sign in as admin@aquaterra.com to use it.</Text>
        </View>
      </View>
    );
  }

  return (
    <View style={styles.root}>
      <Header title="Dispatch board" subtitle="Auto-route unassigned jobs" />
      <ScrollView
        contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}
        refreshControl={undefined}
      >
        {loading && !settings ? (
          <View style={styles.center} testID="dispatch-loading">
            <ActivityIndicator color={colors.brand} />
          </View>
        ) : null}

        {settings ? (
          <View style={styles.settingsCard} testID="dispatch-settings-bar">
            <View style={styles.settingsRow}>
              <Ionicons name="flash-outline" size={16} color={colors.brand} />
              <Text style={styles.settingsLabel}>Auto-assign on job create</Text>
              <Pressable
                onPress={toggleAuto}
                style={[styles.pill, {
                  backgroundColor: settings.auto_assign_on_create ? "#DCFCE7" : "#F3F4F6",
                }]}
                testID="dispatch-autoassign-toggle"
              >
                <Text style={[styles.pillText, {
                  color: settings.auto_assign_on_create ? "#059669" : "#6B7280",
                }]}>
                  {settings.auto_assign_on_create ? "ON" : "OFF"}
                </Text>
              </Pressable>
            </View>
            <Text style={styles.settingsMeta}>
              Weather: <Text style={{ fontFamily: font.semibold }}>{settings.weather_reschedule_mode}</Text>
              {" · "}Rain {settings.rain_threshold_pct}%
              {" · "}Wind {settings.wind_threshold_mph} mph
            </Text>
            <Pressable
              onPress={() => router.push("/(app)/dispatch/weather" as any)}
              style={styles.weatherLink}
              testID="dispatch-weather-link"
            >
              <Ionicons name="cloud-outline" size={14} color={colors.brand} />
              <Text style={styles.weatherLinkText}>Open Weather Reschedule</Text>
              <Ionicons name="chevron-forward" size={14} color={colors.brand} />
            </Pressable>
          </View>
        ) : null}

        {/* Phase 38b · Feb-2026 — Live tech pins on Mapbox (dev-client only). */}
        <LiveTechPinsWrapper
          onNavigateToShift={(uid, uname) => {
            router.push({
              pathname: "/dispatch/shift-route",
              params: { source: uid, sourceName: uname, scope: "whole_route" },
            } as any);
          }}
        />

        {/* Phase 38 · Feb-2026 — Dispatch parity (P1.4) tools row. */}
        <View style={styles.p38Tools} testID="dispatch-tools-row">
          <Pressable
            onPress={() => openOptimize(selectedTech || techLoads[0]?.tech_user_id || "")}
            style={styles.p38Btn}
            disabled={techLoads.length === 0}
            testID="dispatch-open-optimize"
          >
            <Ionicons name="git-branch-outline" size={16} color={colors.brand} />
            <Text style={styles.p38BtnText}>Optimize route</Text>
          </Pressable>
          <Pressable
            onPress={() => openShiftRoute()}
            style={styles.p38Btn}
            disabled={techLoads.length === 0}
            testID="dispatch-open-shift-route"
          >
            <Ionicons name="swap-horizontal-outline" size={16} color={colors.brand} />
            <Text style={styles.p38BtnText}>Shift route</Text>
          </Pressable>
        </View>

        {/* Phase 38 — Tech load strip. */}
        <TechLoadStrip
          loads={techLoads}
          selectedTechId={selectedTech}
          onSelect={setSelectedTech}
        />

        {/* Phase 38 — Unrouted panel. */}
        <UnroutedPanel
          pins={unroutedPins}
          onSelect={(cid) => openShiftRoute(cid)}
        />

        <View style={styles.techsCard} testID="dispatch-techs">
          <Text style={styles.techsTitle}>
            <Ionicons name="people-outline" size={14} color={colors.muted} />{" "}
            Active techs · {techs.length}
          </Text>
          {techs.length === 0 ? (
            <Text style={styles.emptyLine}>No active techs found.</Text>
          ) : techs.map((t) => (
            <View key={t.user_id || t.id} style={styles.techRow} testID={`tech-row-${t.user_id || t.id}`}>
              <Ionicons name="person-circle-outline" size={22} color={colors.brand} />
              <View style={{ flex: 1 }}>
                <Text style={styles.techName}>{t.name}</Text>
                <Text style={styles.techMeta}>
                  {t.preferred_service_types?.length
                    ? t.preferred_service_types.join(" · ")
                    : "no specialties set"}
                </Text>
              </View>
            </View>
          ))}
        </View>

        <View style={styles.jobsHeader}>
          <Text style={styles.jobsTitle}>Unassigned · {jobs.length}</Text>
          <Pressable
            onPress={assignAll}
            disabled={bulkBusy || jobs.length === 0}
            style={[styles.bulkBtn, (bulkBusy || jobs.length === 0) && { opacity: 0.4 }]}
            testID="dispatch-assignall-btn"
          >
            {bulkBusy
              ? <ActivityIndicator color="#fff" size="small" />
              : <Ionicons name="play" size={12} color="#fff" />}
            <Text style={styles.bulkBtnText}>
              {bulkBusy ? "Assigning…" : "Auto-assign all"}
            </Text>
          </Pressable>
        </View>

        {msg ? (
          <View
            style={[styles.msg, msg.kind === "err" ? styles.msgErr : styles.msgInfo]}
            testID="dispatch-msg"
          >
            <Ionicons
              name={msg.kind === "err" ? "warning-outline" : "checkmark-circle-outline"}
              size={14}
              color={msg.kind === "err" ? colors.error : "#059669"}
            />
            <Text style={[styles.msgText, msg.kind === "err" ? { color: colors.error } : { color: "#166534" }]}>
              {msg.text}
            </Text>
          </View>
        ) : null}

        {loading ? null : jobs.length === 0 ? (
          <View style={styles.empty} testID="dispatch-empty">
            <Ionicons name="checkmark-circle" size={32} color="#059669" />
            <Text style={styles.emptyText}>All jobs assigned</Text>
            <Text style={styles.emptySub}>New jobs on the calendar today or later are unassigned show up here.</Text>
          </View>
        ) : (
          jobsPreview.map((j) => (
            <View key={j.id} style={styles.jobCard} testID={`dispatch-job-row-${j.id}`}>
              <View style={{ flex: 1 }}>
                <Text style={styles.jobCustomer}>{formatCustomerName(j)}</Text>
                <Text style={styles.jobMeta} numberOfLines={1}>
                  {(j.scheduled_date || "").slice(0, 10)}
                  {" · "}{j.service_type || j.address || "no address"}
                </Text>
                {j.address ? (
                  <Text style={styles.jobAddress} numberOfLines={1}>{j.address}</Text>
                ) : null}
              </View>
              <Pressable
                onPress={() => assignOne(j.id)}
                disabled={busyJob === j.id}
                style={[styles.assignBtn, busyJob === j.id && { opacity: 0.5 }]}
                testID={`dispatch-assign-${j.id}`}
              >
                {busyJob === j.id
                  ? <ActivityIndicator color="#fff" size="small" />
                  : <Ionicons name="flash" size={12} color="#fff" />}
                <Text style={styles.assignBtnText}>
                  {busyJob === j.id ? "…" : "Auto"}
                </Text>
              </Pressable>
            </View>
          ))
        )}

        {jobs.length > 100 ? (
          <Text style={styles.moreHint}>
            Showing first 100 of {jobs.length} unassigned. Open desktop to see all.
          </Text>
        ) : null}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  center: { padding: spacing.xl, alignItems: "center" },
  forbid: { flex: 1, alignItems: "center", justifyContent: "center", padding: spacing.xl, gap: spacing.sm },
  forbidTitle: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.muted },
  forbidSub: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, textAlign: "center" },
  settingsCard: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
    marginBottom: spacing.md,
    gap: spacing.sm,
  },
  settingsRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  settingsLabel: { flex: 1, fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface },
  settingsMeta: { fontFamily: font.regular, fontSize: fontSize.xs, color: colors.muted },
  pill: { paddingHorizontal: 10, paddingVertical: 3, borderRadius: radius.pill },
  pillText: { fontFamily: font.bold, fontSize: 11, letterSpacing: 0.5 },
  weatherLink: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.xs,
    paddingVertical: spacing.xs,
  },
  weatherLinkText: { flex: 1, fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.brand },
  techsCard: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
    marginBottom: spacing.md,
  },
  techsTitle: {
    fontFamily: font.semibold,
    fontSize: 11,
    letterSpacing: 1,
    textTransform: "uppercase",
    color: colors.muted,
    marginBottom: spacing.sm,
  },
  techRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    paddingVertical: spacing.xs,
  },
  techName: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface },
  techMeta: { fontFamily: font.regular, fontSize: fontSize.xs, color: colors.muted, marginTop: 1 },
  jobsHeader: {
    flexDirection: "row",
    alignItems: "center",
    marginBottom: spacing.sm,
    gap: spacing.sm,
  },
  jobsTitle: { flex: 1, fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  bulkBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.xs,
    backgroundColor: colors.brand,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs + 2,
    borderRadius: radius.md,
  },
  bulkBtnText: { fontFamily: font.bold, fontSize: fontSize.sm, color: "#fff" },
  msg: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.xs,
    padding: spacing.sm,
    borderRadius: radius.md,
    marginBottom: spacing.sm,
  },
  msgInfo: { backgroundColor: "#F0FDF4", borderWidth: 1, borderColor: "#86EFAC" },
  msgErr: { backgroundColor: "#FEE2E2", borderWidth: 1, borderColor: "#FCA5A5" },
  msgText: { flex: 1, fontFamily: font.medium, fontSize: fontSize.sm },
  jobCard: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
    marginBottom: spacing.sm,
  },
  jobCustomer: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  jobMeta: { fontFamily: font.regular, fontSize: fontSize.xs, color: colors.muted, marginTop: 2 },
  jobAddress: { fontFamily: font.regular, fontSize: fontSize.xs, color: colors.muted, marginTop: 1 },
  assignBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    backgroundColor: colors.brand,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs + 2,
    borderRadius: radius.md,
    minWidth: 66,
    justifyContent: "center",
  },
  assignBtnText: { fontFamily: font.bold, fontSize: fontSize.xs, color: "#fff" },
  empty: {
    alignItems: "center",
    justifyContent: "center",
    padding: spacing["3xl"],
    gap: spacing.xs,
  },
  emptyText: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface, marginTop: spacing.xs },
  emptySub: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, textAlign: "center" },
  emptyLine: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  moreHint: {
    marginTop: spacing.md,
    fontFamily: font.regular,
    fontSize: fontSize.xs,
    color: colors.muted,
    textAlign: "center",
  },
  // Phase 38 · Feb-2026 — Dispatch parity (P1.4).
  p38Tools: {
    flexDirection: "row",
    gap: spacing.sm,
    marginTop: spacing.md,
    marginBottom: spacing.sm,
  },
  p38Btn: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  p38BtnText: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.brand,
  },
});
