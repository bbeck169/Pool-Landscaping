/**
 * Phase 30 · Calendar Schedule (Expo mobile) — fix pass.
 *
 * Top-level mode is now a binary toggle: `[Calendar] [Grid]`. Default = Grid
 * (persists in AsyncStorage). Layout matches the two reference screenshots
 * the user provided.
 *
 *   Grid view (default)
 *     • Day header with < prev / today / next > controls
 *     • Bulk-action pill row: Complete · Move · Rearrange (all Jobs.write gated)
 *     • Stacked cards per job with a circular checkbox, service-type tag,
 *       customer + address, notepad+billable-hours row, status pill.
 *
 *   Calendar view
 *     • Multi-day columns (Mon–Sun sticky headers) with events stacked in
 *       each column. Colour-coded by service type. Recurring jobs get 🔁.
 *     • `BH 👁` toggle to hide/show billable hours on cards.
 *
 * Endpoints used (all pre-existing):
 *   GET  /api/jobs?start=&end=            (Phase 30 range filter)
 *   PUT  /api/jobs/{id}   {status,scheduled_date}   (mark complete / move)
 *   POST /api/jobs/reorder  {job_ids:[…]}           (admin rearrange)
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, TextInput, Platform,
  ActivityIndicator, Alert,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter, Redirect } from "expo-router";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { storage } from "@/src/utils/storage";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header, NotificationBell } from "@/src/components/widgets";
import LandscapingClockWidget from "@/src/components/LandscapingClockWidget";
import WeatherWidget from "@/src/components/weather/WeatherWidget";
import RainFlag from "@/src/components/weather/RainFlag";
import WeekStrip from "@/src/components/schedule/WeekStrip";
import { getStatusBorderColor } from "@/src/utils/scheduleStatus";
import type { HourlyEntry } from "@/src/api/weather";

type Job = {
  id: string;
  scheduled_date?: string | null;
  scheduled_time?: string | null;
  service_type?: string;
  status?: string;
  customer_name?: string;
  address?: string;
  property_id?: string | null;
  property_label?: string | null;
  property_address?: string | null;
  technician_id?: string | null;
  estimated_hours?: number | null;
  actual_hours?: number | null;
  billable_hours?: number | null;
  duration_minutes?: number | null;
  route_order?: number | null;
  is_recurring?: boolean;
  recurring?: boolean;
  recurrence?: string | null;
  title?: string;
};

type Mode = "grid" | "calendar";
const MODE_KEY = "aq-schedule-mode-v1";

const iso = (d: Date) => d.toISOString().slice(0, 10);
const addDays = (d: Date, n: number) => { const c = new Date(d); c.setDate(c.getDate() + n); return c; };
const dayLabel = (d: Date) =>
  d.toLocaleDateString(undefined, { weekday: "long", year: "numeric", month: "short", day: "numeric" });

// Status pill palette. "Closed" (=completed) is green; open/scheduled is amber.
const STATUS_PILL: Record<string, { bg: string; fg: string; label: string }> = {
  completed:  { bg: "#DCFCE7", fg: "#166534", label: "Closed" },
  active:     { bg: "#DBEAFE", fg: "#1E40AF", label: "In progress" },
  scheduled:  { bg: "#FEF3C7", fg: "#92400E", label: "Open" },
  pending:    { bg: "#FEF3C7", fg: "#92400E", label: "Pending" },
  requested:  { bg: "#EDE9FE", fg: "#5B21B6", label: "Requested" },
  reopened:   { bg: "#FEE2E2", fg: "#991B1B", label: "Reopened" },
  cancelled:  { bg: "#F3F4F6", fg: "#4B5563", label: "Cancelled" },
  on_hold:    { bg: "#FFEDD5", fg: "#9A3412", label: "On hold" },
};

// Service-type → column card colour. Distinct hues for the Calendar view;
// unknown types fall back to a neutral surface.
const SERVICE_COLOR = (raw?: string): { bg: string; fg: string; tag: string } => {
  const s = (raw || "").toLowerCase();
  if (s.includes("weekly") && s.includes("landsc")) return { bg: "#DCFCE7", fg: "#166534", tag: "#059669" };
  if (s.includes("monthly") && s.includes("landsc")) return { bg: "#E0E7FF", fg: "#3730A3", tag: "#4F46E5" };
  if (s.includes("irrig")) return { bg: "#DBEAFE", fg: "#1E3A8A", tag: "#2563EB" };
  if (s.includes("rock")) return { bg: "#FEF3C7", fg: "#78350F", tag: "#B45309" };
  if (s.includes("pool") || s.includes("chem")) return { bg: "#CFFAFE", fg: "#155E75", tag: "#0891B2" };
  if (s.includes("clean")) return { bg: "#FCE7F3", fg: "#831843", tag: "#BE185D" };
  return { bg: "#F3F4F6", fg: "#111827", tag: "#6B7280" };
};

const jobHours = (j: Job): string => {
  const h = j.actual_hours ?? j.billable_hours ?? j.estimated_hours ?? 0;
  return `${(Number(h) || 0).toFixed(2)} BH`;
};
const isRecurring = (j: Job): boolean =>
  Boolean(j.is_recurring || j.recurring || (j.recurrence && j.recurrence !== "none"));

export default function ScheduleCalendar() {
  const router = useRouter();
  const { user } = useAuth();
  const role = (user?.role as string) || "";
  const isAdmin = role === "admin" || role === "super_admin";
  const isTech = role === "technician";
  const canWriteJobs = isAdmin || isTech;

  if (role === "customer") return <Redirect href="/(app)/jobs" />;

  const [mode, setMode] = useState<Mode>("grid");
  const [modeLoaded, setModeLoaded] = useState(false);
  const [focus, setFocus] = useState(new Date());                // Grid: single day; Calendar: anchors the week
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [showBH, setShowBH] = useState(true);
  const [rearrangeMode, setRearrangeMode] = useState(false);
  const [moveOpen, setMoveOpen] = useState(false);
  const [moveDate, setMoveDate] = useState("");
  const [hourlyData, setHourlyData] = useState<HourlyEntry[]>([]);

  // Load persisted mode.
  useEffect(() => {
    (async () => {
      try {
        const saved = await storage.getItem<string>(MODE_KEY, "grid");
        if (saved === "grid" || saved === "calendar") setMode(saved);
      } finally { setModeLoaded(true); }
    })();
  }, []);
  const setModePersist = (m: Mode) => {
    setMode(m);
    storage.setItem(MODE_KEY, m).catch(() => {/* incognito — in-memory only */});
  };

  const load = useCallback(async () => {
    setLoading(true); setErr("");
    try {
      const start = iso(addDays(focus, -14));
      const end   = iso(addDays(focus,  60));
      const data = await api.get(`/jobs?start=${start}&end=${end}`);
      const arr = Array.isArray(data) ? data : (data.items || data.data || []);
      setJobs(arr);
    } catch (e: any) {
      setErr(e.message || "Failed to load schedule");
    } finally { setLoading(false); }
  }, [focus]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const focusISO = iso(focus);
  const dayJobs = useMemo(() => {
    const list = jobs.filter((j) => j.scheduled_date === focusISO);
    list.sort((a, b) => (a.route_order ?? 999) - (b.route_order ?? 999));
    // Phase 30X · schedule is per-day; no time-of-day tiebreaker.
    return list;
  }, [jobs, focusISO]);

  /** Job-count map for the 7 visible WeekStrip days (client-side). */
  const weekCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const j of jobs) {
      const d = j.scheduled_date?.slice(0, 10);
      if (d) counts[d] = (counts[d] || 0) + 1;
    }
    return counts;
  }, [jobs]);

  const [reorderList, setReorderList] = useState<Job[]>([]);
  useEffect(() => { setReorderList(dayJobs); }, [dayJobs]);

  const gridList = rearrangeMode ? reorderList : dayJobs;

  const toggleCheck = (id: string) => {
    setChecked((cur) => {
      const next = new Set(cur);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const bulkComplete = async () => {
    if (!checked.size) return;
    setBusy(true);
    let ok = 0, fail = 0;
    for (const id of checked) {
      try { await api.put(`/jobs/${id}`, { status: "completed" }); ok++; }
      catch { fail++; }
    }
    setBusy(false);
    setChecked(new Set());
    Alert.alert("Marked complete", `${ok} closed · ${fail} failed`);
    await load();
  };

  const bulkMove = async () => {
    if (!checked.size || !moveDate.match(/^\d{4}-\d{2}-\d{2}$/)) {
      Alert.alert("Pick a date", "Enter a YYYY-MM-DD target date to move to.");
      return;
    }
    setBusy(true);
    let ok = 0, fail = 0;
    for (const id of checked) {
      try { await api.put(`/jobs/${id}`, { scheduled_date: moveDate }); ok++; }
      catch { fail++; }
    }
    setBusy(false);
    setChecked(new Set());
    setMoveOpen(false); setMoveDate("");
    Alert.alert("Move complete", `${ok} moved · ${fail} failed`);
    await load();
  };

  const bulkDelete = async () => {
    if (!checked.size) return;
    Alert.alert(
      `Delete ${checked.size} job${checked.size === 1 ? "" : "s"}?`,
      "Soft-deleted jobs can be recovered by a super admin.",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Delete", style: "destructive", onPress: async () => {
            setBusy(true);
            try {
              await api.post("/jobs/bulk-soft-delete", { job_ids: [...checked] });
              Alert.alert("Deleted", `${checked.size} job${checked.size === 1 ? "" : "s"} removed.`);
              setChecked(new Set());
              await load();
            } catch (e: any) {
              Alert.alert("Delete failed", e.message || "Unknown error");
            } finally { setBusy(false); }
          },
        },
      ],
    );
  };

  const saveReorder = async () => {
    if (!isAdmin) {
      setRearrangeMode(false);
      Alert.alert("Rearrange saved locally", "Only admins can persist a new route order — the reorder endpoint is admin-only.");
      return;
    }
    setBusy(true);
    try {
      await api.post("/jobs/reorder", { job_ids: reorderList.map((j) => j.id) });
      Alert.alert("Route saved", `New order saved for ${reorderList.length} jobs.`);
      await load();
    } catch (e: any) {
      Alert.alert("Reorder failed", e.message || "Try again.");
    } finally {
      setBusy(false);
      setRearrangeMode(false);
    }
  };

  const shift = (id: string, dir: -1 | 1) => {
    setReorderList((cur) => {
      const i = cur.findIndex((j) => j.id === id);
      if (i < 0) return cur;
      const j = i + dir;
      if (j < 0 || j >= cur.length) return cur;
      const c = [...cur];
      [c[i], c[j]] = [c[j], c[i]];
      return c;
    });
  };

  /* ─── Calendar view — build 7-day column layout ─────────────────── */
  const weekStart = useMemo(() => {
    const d = new Date(focus);
    const day = d.getDay();
    d.setDate(d.getDate() - day + 1);         // Monday
    return d;
  }, [focus]);
  const weekDays = useMemo(
    () => Array.from({ length: 7 }, (_, i) => addDays(weekStart, i)),
    [weekStart],
  );
  const weekTitle = useMemo(
    () => focus.toLocaleDateString(undefined, { month: "long", year: "numeric" }),
    [focus],
  );
  const jobsByDay = useMemo(() => {
    const m: Record<string, Job[]> = {};
    for (const j of jobs) {
      const d = j.scheduled_date || "";
      (m[d] = m[d] || []).push(j);
    }
    return m;
  }, [jobs]);

  if (!modeLoaded) return null;

  return (
    <View style={styles.root}>
      <Header
        title="Schedule"
        subtitle={loading ? "Loading…" : `${jobs.length} jobs in window · ${mode}`}
        right={isTech ? <NotificationBell /> : undefined}
      />
      <View style={{ paddingHorizontal: spacing.lg, paddingTop: spacing.md }}>
        {user?.role !== "admin" && user?.role !== "super_admin" && <LandscapingClockWidget />}
      </View>

      {/* Feb-2026 · Schedule-UI · 7-day toggle strip.
          The strip drives the shared `focus` state — tapping a day
          updates focus which triggers the existing ±14/+60 fetch window. */}
      <WeekStrip
        selectedDate={focusISO}
        onSelectDate={(dateIso) => {
          const [y, m, d] = dateIso.split("-").map(Number);
          setFocus(new Date(y, m - 1, d));
        }}
        counts={weekCounts}
      />

      {/* Top-level Grid ↔ Calendar toggle. */}
      <View style={styles.modeSwitch} testID="schedule-mode-switch">
        {(["calendar", "grid"] as const).map((m) => {
          const active = mode === m;
          return (
            <Pressable
              key={m}
              onPress={() => setModePersist(m)}
              style={[styles.modeBtn, active && styles.modeBtnActive]}
              testID={`schedule-mode-${m}`}
            >
              <Ionicons
                name={m === "grid" ? "list-outline" : "calendar-outline"}
                size={14}
                color={active ? "#fff" : colors.onSurfaceSecondary}
              />
              <Text style={[styles.modeBtnText, active && { color: "#fff" }]}>
                {m === "grid" ? "Grid" : "Calendar"}
              </Text>
            </Pressable>
          );
        })}
      </View>

      {err ? (
        <View style={styles.errBar} testID="schedule-error">
          <Ionicons name="warning-outline" size={12} color="#991B1B" />
          <Text style={styles.errText}>{err}</Text>
        </View>
      ) : null}

      {mode === "grid" ? (
        <GridView
          focus={focus} setFocus={setFocus}
          jobs={gridList} loading={loading}
          checked={checked} onToggle={toggleCheck}
          canWrite={canWriteJobs}
          rearrangeMode={rearrangeMode}
          onToggleRearrange={() => setRearrangeMode((v) => !v)}
          onSaveReorder={saveReorder}
          onShift={shift}
          onBulkComplete={bulkComplete}
          onBulkDelete={bulkDelete}
          onOpenMove={() => setMoveOpen(true)}
          moveOpen={moveOpen} setMoveOpen={setMoveOpen}
          moveDate={moveDate} setMoveDate={setMoveDate}
          onConfirmMove={bulkMove}
          busy={busy}
          onOpenJob={(id: string) => router.push(`/job/${id}/checklist` as any)}
          onNewJob={() => router.push(`/job/new?date=${focusISO}` as any)}
          isAdmin={isAdmin}
          hourlyData={hourlyData}
          weatherWidget={(isTech || isAdmin) ? <WeatherWidget onHourlyLoaded={setHourlyData} /> : null}
        />
      ) : (
        <CalendarView
          weekDays={weekDays}
          weekTitle={weekTitle}
          jobsByDay={jobsByDay}
          showBH={showBH}
          onToggleBH={() => setShowBH((v) => !v)}
          onPrev={() => setFocus((d) => addDays(d, -7))}
          onNext={() => setFocus((d) => addDays(d, 7))}
          onOpenJob={(id) => router.push(`/job/${id}/checklist` as any)}
          weatherWidget={(isTech || isAdmin) ? <WeatherWidget onHourlyLoaded={setHourlyData} /> : null}
        />
      )}
    </View>
  );
}

/* ═══ Grid view ══════════════════════════════════════════════════════ */
function GridView(props: any) {
  const {
    focus, setFocus, jobs, loading, checked, onToggle, canWrite,
    rearrangeMode, onToggleRearrange, onSaveReorder, onShift,
    onBulkComplete, onBulkDelete, onOpenMove, moveOpen, setMoveOpen, moveDate, setMoveDate,
    onConfirmMove, busy, onOpenJob, onNewJob, isAdmin, hourlyData,
    weatherWidget,
  } = props;
  const focusISO = iso(focus);
  const isToday = focusISO === iso(new Date());

  return (
    <ScrollView contentContainerStyle={{ padding: spacing.md, paddingBottom: spacing["3xl"] }}>
      <View style={gStyles.dayHead} testID="schedule-day-head">
        <Pressable onPress={() => setFocus(addDays(focus, -1))} style={gStyles.navBtn} testID="grid-prev-day">
          <Ionicons name="chevron-back" size={18} color={colors.onSurface} />
        </Pressable>
        <Pressable
          onPress={() => setFocus(new Date())}
          style={[gStyles.todayPill, isToday && gStyles.todayPillActive]}
          testID="grid-today"
        >
          <Text style={[gStyles.todayText, isToday && { color: "#fff" }]}>Today</Text>
        </Pressable>
        <Pressable onPress={() => setFocus(addDays(focus, 1))} style={gStyles.navBtn} testID="grid-next-day">
          <Ionicons name="chevron-forward" size={18} color={colors.onSurface} />
        </Pressable>
        <Text style={gStyles.dayLabel} testID="grid-day-label">{dayLabel(focus)}</Text>
      </View>

      {/* Bulk-action pills. Buttons stay visible but disable when nothing is checked. */}
      {canWrite ? (
        <View style={gStyles.pillRow} testID="grid-bulk-pills">
          <Pressable
            onPress={onBulkComplete}
            disabled={busy || checked.size === 0}
            style={[gStyles.pill, gStyles.pillGreen, (busy || checked.size === 0) && { opacity: 0.4 }]}
            testID="grid-bulk-complete"
          >
            <Ionicons name="checkmark-circle" size={13} color="#fff" />
            <Text style={gStyles.pillText}>Complete ({checked.size})</Text>
          </Pressable>
          <Pressable
            onPress={onOpenMove}
            disabled={busy || checked.size === 0}
            style={[gStyles.pill, gStyles.pillBlue, (busy || checked.size === 0) && { opacity: 0.4 }]}
            testID="grid-bulk-move"
          >
            <Ionicons name="calendar-outline" size={13} color="#fff" />
            <Text style={gStyles.pillText}>Move ({checked.size})</Text>
          </Pressable>
          <Pressable
            onPress={onBulkDelete}
            disabled={busy || checked.size === 0}
            style={[gStyles.pill, gStyles.pillRed, (busy || checked.size === 0) && { opacity: 0.4 }]}
            testID="grid-bulk-delete"
          >
            <Ionicons name="trash-outline" size={13} color="#fff" />
            <Text style={gStyles.pillText}>Delete ({checked.size})</Text>
          </Pressable>
          <Pressable
            onPress={rearrangeMode ? onSaveReorder : onToggleRearrange}
            style={[gStyles.pill, rearrangeMode ? gStyles.pillGreen : gStyles.pillPurple]}
            testID="grid-bulk-rearrange"
          >
            <Ionicons name={rearrangeMode ? "save-outline" : "reorder-three-outline"} size={13} color="#fff" />
            <Text style={gStyles.pillText}>{rearrangeMode ? "Save order" : "Rearrange"}</Text>
          </Pressable>
        </View>
      ) : null}

      {moveOpen ? (
        <View style={gStyles.moveBox} testID="grid-move-box">
          <Text style={gStyles.moveLabel}>Move {checked.size} job{checked.size === 1 ? "" : "s"} to:</Text>
          <TextInput
            value={moveDate}
            onChangeText={setMoveDate}
            placeholder="YYYY-MM-DD"
            placeholderTextColor={colors.muted}
            autoCapitalize="none"
            style={gStyles.moveInput}
            testID="grid-move-input"
          />
          <View style={{ flexDirection: "row", gap: spacing.xs }}>
            <Pressable
              onPress={() => { setMoveOpen(false); setMoveDate(""); }}
              style={[gStyles.moveBtn, gStyles.moveBtnCancel]}
              testID="grid-move-cancel"
            >
              <Text style={gStyles.moveBtnCancelText}>Cancel</Text>
            </Pressable>
            <Pressable
              onPress={onConfirmMove}
              disabled={busy}
              style={[gStyles.moveBtn, gStyles.moveBtnGo, busy && { opacity: 0.5 }]}
              testID="grid-move-confirm"
            >
              <Text style={gStyles.moveBtnGoText}>Move</Text>
            </Pressable>
          </View>
        </View>
      ) : null}

      {loading ? (
        <View style={{ padding: spacing.xl, alignItems: "center" }}><ActivityIndicator color={colors.brand} /></View>
      ) : jobs.length === 0 ? (
        <View style={gStyles.empty} testID="grid-empty">
          <Ionicons name="calendar-outline" size={28} color={colors.muted} />
          <Text style={gStyles.emptyTitle}>Nothing on {focusISO}</Text>
          {isAdmin ? (
            <Pressable onPress={onNewJob} style={gStyles.newBtn} testID="grid-new-job">
              <Ionicons name="add-circle" size={14} color="#fff" />
              <Text style={gStyles.newBtnText}>New job</Text>
            </Pressable>
          ) : null}
        </View>
      ) : jobs.map((j: Job, idx: number) => (
        <JobRow
          key={j.id}
          job={j}
          idx={idx}
          checked={checked.has(j.id)}
          onCheck={() => onToggle(j.id)}
          onOpen={() => onOpenJob(j.id)}
          rearrangeMode={rearrangeMode}
          onShift={onShift}
          first={idx === 0}
          last={idx === jobs.length - 1}
          hourlyData={hourlyData}
        />
      ))}
      {weatherWidget ? (
        <View style={{ paddingHorizontal: spacing.xs, paddingTop: spacing.lg }} testID="schedule-weather-bottom">
          {weatherWidget}
        </View>
      ) : null}
    </ScrollView>
  );
}

function JobRow({ job, idx, checked, onCheck, onOpen, rearrangeMode, onShift, first, last, hourlyData }: any) {
  const pill = STATUS_PILL[(job.status || "scheduled").toLowerCase()] || STATUS_PILL.scheduled;
  const svc = SERVICE_COLOR(job.service_type);
  // Feb-2026 · Schedule-UI · colored left border.
  const statusBorder = getStatusBorderColor(job.status);
  // Phase 31 · Step 2a hotfix — the entire row body is now the primary
  // tap target and routes to /job/{id}/checklist. Previously only the
  // right-edge chevron was pressable, leaving 90% of the visible card
  // dead; users hitting the leftmost checkbox by accident and then
  // tapping the "Complete" bulk-action pill made it look like a card
  // tap "completed" the job. Nested Pressables (checkbox + rearrange
  // arrows) still capture their own touch zone via RN's responder
  // system, so they do NOT bubble up to the row tap. During
  // rearrangeMode the row-level tap is disabled so the up/down arrows
  // remain the only interactive elements.
  return (
    <Pressable
      style={[gStyles.card, { borderLeftWidth: 4, borderLeftColor: statusBorder }]}
      onPress={rearrangeMode ? undefined : onOpen}
      testID={`grid-job-${job.id}`}
      hitSlop={4}
    >
      {rearrangeMode ? (
        <View style={gStyles.reorderCol}>
          <Pressable onPress={() => onShift(job.id, -1)} disabled={first}
                     style={[gStyles.reorderBtn, first && { opacity: 0.3 }]}
                     testID={`grid-reorder-up-${job.id}`}>
            <Ionicons name="chevron-up" size={14} color={colors.brand} />
          </Pressable>
          <Text style={gStyles.reorderIdx}>{idx + 1}</Text>
          <Pressable onPress={() => onShift(job.id, 1)} disabled={last}
                     style={[gStyles.reorderBtn, last && { opacity: 0.3 }]}
                     testID={`grid-reorder-down-${job.id}`}>
            <Ionicons name="chevron-down" size={14} color={colors.brand} />
          </Pressable>
        </View>
      ) : (
        <Pressable
          onPress={onCheck}
          style={[gStyles.checkbox, checked && gStyles.checkboxOn]}
          hitSlop={8}
          testID={`grid-check-${job.id}`}
        >
          {checked ? <Ionicons name="checkmark" size={14} color="#fff" /> : null}
        </Pressable>
      )}
      <View style={{ flex: 1 }}>
        <Text style={[gStyles.svcTag, { color: svc.tag }]} numberOfLines={1}>
          {isRecurring(job) ? "🔁 " : ""}
          {(job.service_type || "General").toUpperCase()}
        </Text>
        <Text style={gStyles.cust} numberOfLines={1}>{job.customer_name || "Unknown"}</Text>
        {job.property_label ? (
          <View
            style={{
              alignSelf: "flex-start",
              marginTop: 3,
              paddingHorizontal: 8,
              paddingVertical: 2,
              borderRadius: 999,
              backgroundColor: "#E0F2FE",
              borderWidth: 1,
              borderColor: "#7DD3FC",
            }}
            testID={`job-property-chip-${job.id}`}
          >
            <Text style={{ fontSize: 10, fontWeight: "700", color: "#075985" }}>
              🏠 {job.property_label}
            </Text>
          </View>
        ) : null}
        {job.customer_is_vip ? (
          <View style={gStyles.vipBadge} testID={`job-vip-badge-${job.id}`}>
            <Ionicons name="star" size={9} color="#92400E" />
            <Text style={gStyles.vipText}>VIP</Text>
          </View>
        ) : null}
        {hourlyData.length > 0 && (
          <RainFlag
            jobId={job.id}
            scheduledDate={job.scheduled_date}
            scheduledTime={job.scheduled_time}
            hourlyData={hourlyData}
          />
        )}
        {job.customer_gate_code || job.gate_code ? (
          <View style={gStyles.gateChip} testID={`job-gate-code-${job.id}`}>
            <Ionicons name="key" size={10} color="#92400E" />
            <Text style={gStyles.gateText}>{job.customer_gate_code || job.gate_code}</Text>
          </View>
        ) : null}
        {job.customer_notes || job.account_notes ? (
          <Text style={gStyles.notePreview}
                numberOfLines={2}
                testID={`job-notes-preview-${job.id}`}>
            Notes: {String(job.customer_notes || job.account_notes).slice(0, 60)}
            {String(job.customer_notes || job.account_notes).length > 60 ? "…" : ""}
          </Text>
        ) : null}
        {job.address ? (
          <Text style={gStyles.addr} numberOfLines={1}>{job.address}</Text>
        ) : null}
        <View style={gStyles.metaRow}>
          <Ionicons name="reader-outline" size={12} color={colors.muted} />
          <Text style={gStyles.metaText}>{jobHours(job)}</Text>
          {/* Phase 30X · time-of-day removed. Schedule is per-day. */}
        </View>
      </View>
      <View style={[gStyles.statusPill, { backgroundColor: pill.bg }]}>
        <Text style={[gStyles.statusText, { color: pill.fg }]}>{pill.label}</Text>
      </View>
      <View testID={`grid-open-${job.id}`}>
        <Ionicons name="chevron-forward" size={20} color={colors.muted} />
      </View>
    </Pressable>
  );
}

/* ═══ Calendar view ══════════════════════════════════════════════════ */
function CalendarView({
  weekDays, weekTitle, jobsByDay, showBH, onToggleBH, onPrev, onNext, onOpenJob,
  weatherWidget,
}: any) {
  return (
    <ScrollView style={{ flex: 1 }} contentContainerStyle={{ flexGrow: 1 }}>
      <View style={cStyles.head}>
        <Pressable onPress={onPrev} style={cStyles.navBtn} testID="calendar-prev-week">
          <Ionicons name="chevron-back" size={18} color={colors.onSurface} />
        </Pressable>
        <Text style={cStyles.headTitle} testID="calendar-week-title">{weekTitle}</Text>
        <Pressable onPress={onNext} style={cStyles.navBtn} testID="calendar-next-week">
          <Ionicons name="chevron-forward" size={18} color={colors.onSurface} />
        </Pressable>
        <Pressable
          onPress={onToggleBH}
          style={[cStyles.bhPill, showBH && cStyles.bhPillOn]}
          testID="calendar-toggle-bh"
        >
          <Ionicons name={showBH ? "eye-outline" : "eye-off-outline"}
                    size={12} color={showBH ? "#fff" : colors.onSurfaceSecondary} />
          <Text style={[cStyles.bhPillText, showBH && { color: "#fff" }]}>BH</Text>
        </Pressable>
      </View>

      <ScrollView horizontal showsHorizontalScrollIndicator={false} nestedScrollEnabled>
        <View style={{ flexDirection: "row" }}>
          {weekDays.map((d: Date) => {
            const key = iso(d);
            const dayJ: Job[] = (jobsByDay[key] || []).slice();
            const isToday = key === iso(new Date());
            return (
              <View key={key} style={cStyles.col} testID={`calendar-col-${key}`}>
                <View style={[cStyles.colHead, isToday && cStyles.colHeadToday]}>
                  <Text style={[cStyles.colDow, isToday && { color: "#fff" }]}>
                    {d.toLocaleDateString(undefined, { weekday: "short" }).toUpperCase()}
                  </Text>
                  <Text style={[cStyles.colDay, isToday && { color: "#fff" }]}>{d.getDate()}</Text>
                </View>
                {dayJ.length === 0 ? (
                  <Text style={cStyles.colEmpty}>—</Text>
                ) : dayJ.map((j) => {
                  const svc = SERVICE_COLOR(j.service_type);
                  return (
                    <Pressable
                      key={j.id}
                      onPress={() => onOpenJob(j.id)}
                      style={[cStyles.eventCard, { backgroundColor: svc.bg, borderLeftColor: svc.tag }]}
                      testID={`calendar-event-${j.id}`}
                    >
                      <Text style={[cStyles.eventTitle, { color: svc.fg }]} numberOfLines={2}>
                        {isRecurring(j) ? "🔁 " : ""}
                        {j.service_type || j.title || "Job"}
                      </Text>
                      <Text style={[cStyles.eventCust, { color: svc.fg }]} numberOfLines={1}>
                        {j.customer_is_vip ? "★ " : ""}{j.customer_name || "—"}
                      </Text>
                      {showBH ? (
                        <Text style={[cStyles.eventBH, { color: svc.fg }]}>{jobHours(j)}</Text>
                      ) : null}
                    </Pressable>
                  );
                })}
              </View>
            );
          })}
        </View>
      </ScrollView>

      {weatherWidget ? (
        <View style={{ paddingHorizontal: spacing.md, paddingTop: spacing.lg, paddingBottom: spacing["3xl"] }} testID="calendar-weather-bottom">
          {weatherWidget}
        </View>
      ) : null}
    </ScrollView>
  );
}

/* ═══ Styles ═════════════════════════════════════════════════════════ */
const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  modeSwitch: {
    flexDirection: "row",
    gap: spacing.xs,
    padding: spacing.md,
    paddingBottom: spacing.xs,
  },
  modeBtn: {
    flex: 1, height: 38,
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: spacing.xs,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
    borderWidth: 1, borderColor: colors.border,
  },
  modeBtnActive: { backgroundColor: colors.brand, borderColor: colors.brand },
  modeBtnText: { fontFamily: font.bold, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
  errBar: {
    flexDirection: "row", alignItems: "center", gap: spacing.xs,
    margin: spacing.md, marginTop: 0,
    padding: spacing.sm, borderRadius: radius.md,
    backgroundColor: "#FEE2E2",
  },
  errText: { flex: 1, fontFamily: font.medium, fontSize: fontSize.sm, color: "#991B1B" },
});

const gStyles = StyleSheet.create({
  vipBadge: {
    flexDirection: "row", alignItems: "center", alignSelf: "flex-start",
    gap: 2, backgroundColor: "#FEF3C7", borderColor: "#F59E0B", borderWidth: 1,
    paddingHorizontal: 6, paddingVertical: 1, borderRadius: radius.pill,
    marginTop: 2,
  },
  vipText: {
    fontFamily: font.bold, fontSize: 9, color: "#92400E",
    letterSpacing: 0.8, textTransform: "uppercase",
  },
  gateChip: {
    flexDirection: "row", alignItems: "center", alignSelf: "flex-start", gap: 3,
    backgroundColor: "#FEF3C7", borderColor: "#FDE68A", borderWidth: 1,
    paddingHorizontal: 6, paddingVertical: 1, borderRadius: 6, marginTop: 2,
  },
  gateText: {
    fontFamily: font.bold, fontSize: 10, color: "#92400E",
  },
  notePreview: {
    fontFamily: font.regular, fontSize: 10, color: colors.onSurfaceSecondary,
    marginTop: 2,
  },
  dayHead: {
    flexDirection: "row", alignItems: "center", gap: spacing.xs,
    marginBottom: spacing.sm,
  },
  navBtn: {
    width: 34, height: 34, borderRadius: radius.md,
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    alignItems: "center", justifyContent: "center",
  },
  todayPill: {
    paddingHorizontal: spacing.md, height: 34, borderRadius: radius.pill,
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    alignItems: "center", justifyContent: "center",
  },
  todayPillActive: { backgroundColor: colors.brand, borderColor: colors.brand },
  todayText: { fontFamily: font.bold, fontSize: fontSize.xs, color: colors.onSurface },
  dayLabel: {
    flex: 1, textAlign: "right",
    fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface,
  },
  pillRow: {
    flexDirection: "row", gap: spacing.xs, flexWrap: "wrap",
    marginBottom: spacing.sm,
  },
  pill: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: spacing.md, height: 34,
    borderRadius: radius.pill,
  },
  pillGreen:  { backgroundColor: "#059669" },
  pillBlue:   { backgroundColor: "#2563EB" },
  pillRed:    { backgroundColor: "#DC2626" },
  pillPurple: { backgroundColor: "#7C3AED" },
  pillText: { fontFamily: font.bold, fontSize: fontSize.xs, color: "#fff" },
  moveBox: {
    padding: spacing.md, borderRadius: radius.md,
    backgroundColor: colors.surface,
    borderWidth: 1, borderColor: colors.border,
    gap: spacing.xs, marginBottom: spacing.sm,
  },
  moveLabel: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface },
  moveInput: {
    height: 42, borderRadius: radius.md,
    borderWidth: 1.5, borderColor: colors.border,
    paddingHorizontal: spacing.md,
    fontFamily: font.regular, fontSize: fontSize.base,
    color: colors.onSurface,
    backgroundColor: colors.surfaceSecondary,
    ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}),
  },
  moveBtn: { flex: 1, height: 38, borderRadius: radius.md, alignItems: "center", justifyContent: "center" },
  moveBtnCancel: { backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border },
  moveBtnCancelText: { fontFamily: font.bold, fontSize: fontSize.sm, color: colors.onSurface },
  moveBtnGo: { backgroundColor: colors.brand },
  moveBtnGoText: { fontFamily: font.bold, fontSize: fontSize.sm, color: "#fff" },
  card: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    padding: spacing.md, marginBottom: spacing.xs,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
    borderWidth: 1, borderColor: colors.border,
  },
  checkbox: {
    width: 22, height: 22, borderRadius: 11,
    borderWidth: 1.5, borderColor: colors.muted,
    alignItems: "center", justifyContent: "center",
  },
  checkboxOn: { backgroundColor: colors.brand, borderColor: colors.brand },
  reorderCol: { alignItems: "center", justifyContent: "center", gap: 2, width: 32 },
  reorderBtn: { padding: 2, borderRadius: 4 },
  reorderIdx: { fontFamily: font.bold, fontSize: 10, color: colors.brand },
  svcTag: {
    fontFamily: font.bold, fontSize: 10, letterSpacing: 0.5,
  },
  cust: { fontFamily: font.bold, fontSize: fontSize.base, color: colors.onSurface, marginTop: 2 },
  addr: { fontFamily: font.regular, fontSize: fontSize.xs, color: colors.muted, marginTop: 1 },
  metaRow: { flexDirection: "row", alignItems: "center", gap: 4, marginTop: 4 },
  metaText: { fontFamily: font.medium, fontSize: fontSize.xs, color: colors.muted },
  statusPill: { paddingHorizontal: 8, paddingVertical: 4, borderRadius: radius.pill },
  statusText: { fontFamily: font.bold, fontSize: 10, letterSpacing: 0.4 },
  empty: {
    alignItems: "center", justifyContent: "center",
    padding: spacing["3xl"], gap: spacing.sm,
    backgroundColor: colors.surface,
    borderRadius: radius.md, borderWidth: 1, borderStyle: "dashed", borderColor: colors.border,
  },
  emptyTitle: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  newBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: spacing.md, height: 36, borderRadius: radius.md,
    backgroundColor: colors.brand,
  },
  newBtnText: { fontFamily: font.bold, fontSize: fontSize.sm, color: "#fff" },
});

const cStyles = StyleSheet.create({
  head: {
    flexDirection: "row", alignItems: "center", gap: spacing.xs,
    paddingHorizontal: spacing.md, paddingBottom: spacing.xs,
  },
  navBtn: {
    width: 32, height: 32, borderRadius: radius.md,
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    alignItems: "center", justifyContent: "center",
  },
  headTitle: { flex: 1, textAlign: "center", fontFamily: font.bold, fontSize: fontSize.base, color: colors.onSurface },
  bhPill: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: spacing.md, height: 30, borderRadius: radius.pill,
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
  },
  bhPillOn: { backgroundColor: colors.brand, borderColor: colors.brand },
  bhPillText: { fontFamily: font.bold, fontSize: 10, color: colors.onSurfaceSecondary, letterSpacing: 0.5 },
  col: { width: 148, marginHorizontal: 4 },
  colHead: {
    paddingVertical: spacing.xs, borderRadius: radius.md,
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    alignItems: "center", marginBottom: spacing.xs,
  },
  colHeadToday: { backgroundColor: colors.brand, borderColor: colors.brand },
  colDow: { fontFamily: font.bold, fontSize: 10, color: colors.muted, letterSpacing: 0.8 },
  colDay: { fontFamily: font.bold, fontSize: fontSize.base, color: colors.onSurface, marginTop: 2 },
  colEmpty: { textAlign: "center", fontFamily: font.regular, fontSize: fontSize.xs, color: colors.muted, marginTop: spacing.sm },
  eventCard: {
    padding: spacing.sm, marginBottom: spacing.xs,
    borderRadius: radius.md,
    borderLeftWidth: 3,
  },
  eventTitle: { fontFamily: font.bold, fontSize: fontSize.xs, lineHeight: 14 },
  eventCust: { fontFamily: font.regular, fontSize: 10, marginTop: 2 },
  eventBH: { fontFamily: font.semibold, fontSize: 10, marginTop: 2, opacity: 0.85 },
});
