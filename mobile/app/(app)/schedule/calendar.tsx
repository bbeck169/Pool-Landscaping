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
  ActivityIndicator, Alert, Modal,
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
import { showConfirm } from "@/src/components/ConfirmModal";
// Phase 23 · 2026-08-02 — Service / Repair progress ring tiles above the grid.
import JobTrackerTiles from "./JobTrackerTiles";
import ScheduleJobEditSheet from "@/src/components/schedule/ScheduleJobEditSheet";
// Phase 27 · Feb-2026 — Global avatar swap for the per-job card in
// the schedule grid. Compact 20dp footprint keeps row height
// invariant vs the pre-Phase-27 layout.
// Feb-2026 · Schedule polish — the per-card <TechAvatar> was
// removed from the mobile JobRow; keeping the import out avoids
// an unused-symbol lint. The component still ships and is used
// by other surfaces (portal, dispatch, service detail).
import { getStatusBorderColor } from "@/src/utils/scheduleStatus";
import OnMyWayButton from "@/src/components/schedule/OnMyWayButton";
import CouldNotServiceButton from "@/src/components/schedule/CouldNotServiceButton";
import ScheduleMap from "@/src/components/schedule/ScheduleMap";
import DraggableFlatList, { RenderItemParams, ScaleDecorator } from "react-native-draggable-flatlist";
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
  route_index?: number | null;
  location_lat?: number | null;
  location_lng?: number | null;
  is_recurring?: boolean;
  recurring?: boolean;
  recurrence?: string | null;
  title?: string;
  notes?: string | null;
  notes_truncated?: boolean;
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
  // Feb-2026 · Phase 1 — "Could Not Service" outcome. Amber tone
  // deliberately deeper than ``scheduled``/``pending`` so the pill is
  // visually distinct from a plain "Open" job on the same card.
  could_not_service: { bg: "#FDE68A", fg: "#78350F", label: "Could Not Service" },
  skipped:    { bg: "#E5E7EB", fg: "#374151", label: "Skipped" },
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
  const isAdmin = role === "admin" || role === "super_admin" || role === "manager";
  const isTech = role === "technician";
  const canWriteJobs = isAdmin || isTech;

  if (role === "customer") return <Redirect href="/(app)/jobs" />;

  const [mode, setMode] = useState<Mode>("grid");
  const [modeLoaded, setModeLoaded] = useState(false);
  const [focus, setFocus] = useState(new Date());                // Grid: single day; Calendar: anchors the week
  const [jobs, setJobs] = useState<Job[]>([]);
  // Feb-2026 · Schedule inline-edit sheet state. In-place mutate on
  // save / delete so cards refresh without a full ``load()`` cycle.
  const [editingJob, setEditingJob] = useState<Job | null>(null);
  const patchJobInPlace = useCallback((patched: Partial<Job> & { id: string }) => {
    setJobs((prev) => prev.map((r) => (r.id === patched.id ? { ...r, ...patched } : r)));
  }, []);
  const removeJobInPlace = useCallback((jid: string) => {
    setJobs((prev) => prev.filter((r) => r.id !== jid));
  }, []);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [showBH, setShowBH] = useState(true);
  const [rearrangeMode, setRearrangeMode] = useState(false);
  const [gridSubMode, setGridSubMode] = useState<"list" | "map">("list");
  const [moveOpen, setMoveOpen] = useState(false);
  const [moveDate, setMoveDate] = useState("");
  const [reassignOpen, setReassignOpen] = useState(false);
  const [techs, setTechs] = useState<{ id: string; name: string }[]>([]);
  const [reassignTechId, setReassignTechId] = useState("");
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
    list.sort((a, b) => (a.route_index ?? a.route_order ?? 999) - (b.route_index ?? b.route_order ?? 999));
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
  // Feb-2026 · Mobile Schedule "Select all in view" parity with web.
  // Admin+ gated at the button level; ``jobs`` is the currently
  // visible list post-filter, matching the web ``dayJobs`` derivation.
  const selectAllInView = () => {
    setChecked(new Set(jobs.map((j) => j.id)));
  };
  const clearSelection = () => setChecked(new Set());

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
    showConfirm({
      title: `Delete ${checked.size} job${checked.size === 1 ? "" : "s"}?`,
      message: "Soft-deleted jobs can be recovered by a super admin.",
      confirmLabel: "Delete",
      confirmStyle: "destructive",
      onConfirm: async () => {
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
    });
  };

  const openReassign = async () => {
    if (!checked.size) return;
    try {
      const res = await api.get("/users?role=tech");
      const list = (res.users || res || []).filter((u: any) => u.id && u.name);
      setTechs(list);
    } catch { setTechs([]); }
    setReassignTechId("");
    setReassignOpen(true);
  };

  const bulkReassign = async () => {
    if (!checked.size || !reassignTechId) {
      Alert.alert("Select a tech", "Choose a technician to reassign the jobs.");
      return;
    }
    setBusy(true);
    try {
      await api.post("/jobs/bulk-reassign", { job_ids: [...checked], tech_id: reassignTechId });
      const techName = techs.find((t) => t.id === reassignTechId)?.name || "tech";
      Alert.alert("Reassigned", `${checked.size} job${checked.size === 1 ? "" : "s"} assigned to ${techName}.`);
      setChecked(new Set());
      setReassignOpen(false);
      await load();
    } catch (e: any) {
      Alert.alert("Reassign failed", e.message || "Unknown error");
    } finally { setBusy(false); }
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
        right={isTech ? (
          // Phase 22 · 2026-08-02 · Sub-item B — the ambient shell
          // hamburger renders at the extreme top-right and was
          // visually overlapping the bell. Push the bell 44dp left
          // (hamburger tap target + 8dp gap) so both are fully
          // tappable and non-colliding.
          <View style={{ marginRight: 52 }} testID="schedule-header-bell">
            <NotificationBell />
          </View>
        ) : undefined}
      />
      {/* Phase 24 · 2026-08-03 — Root scroll wrapper. Prior layout was
          a flex column with per-view ScrollViews inside GridView /
          CalendarView, leaving the JobTrackerTiles + WeekStrip +
          mode-switch band non-scrollable and clipping content on
          shorter devices. Wrapping the body (everything below the
          Header, above the Modal) in a single vertical ScrollView
          makes the whole schedule page scroll top-to-bottom without
          disturbing the WeekStrip's independent horizontal scroll or
          the reassign-Modal (which is rendered above via RN's Modal
          portal, so it's outside this ScrollView anyway). GridView
          and CalendarView switched their outer <ScrollView> to plain
          <View>s to avoid nested-vertical-scroll conflicts. */}
      <ScrollView
        contentContainerStyle={{ paddingBottom: 40 }}
        showsVerticalScrollIndicator
        testID="schedule-root-scroll"
      >
      <View style={{ paddingHorizontal: spacing.lg, paddingTop: spacing.md }}>
        {user?.role !== "admin" && user?.role !== "super_admin" && <LandscapingClockWidget />}
      </View>

      {/* Phase 23 · 2026-08-02 — Service / Repair progress-ring
          tiles at the top of the schedule (above the WeekStrip).
          Client-side classification off ``service_type`` — no
          backend change. */}
      <JobTrackerTiles jobs={dayJobs} loading={busy} />

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
          onOpenReassign={openReassign}
          moveOpen={moveOpen} setMoveOpen={setMoveOpen}
          moveDate={moveDate} setMoveDate={setMoveDate}
          onConfirmMove={bulkMove}
          busy={busy}
          onOpenJob={(id: string) => router.push(`/job/${id}/checklist` as any)}
          onNewJob={() => router.push(`/job/new?date=${focusISO}` as any)}
          isAdmin={isAdmin}
          hourlyData={hourlyData}
          weatherWidget={(isTech || isAdmin) ? <WeatherWidget onHourlyLoaded={setHourlyData} /> : null}
          onOpenEdit={isAdmin ? ((jobRow: Job) => setEditingJob(jobRow)) : undefined}
          onSelectAllInView={isAdmin ? selectAllInView : undefined}
          onClearSelection={isAdmin ? clearSelection : undefined}
          role={role}
          gridSubMode={gridSubMode}
          setGridSubMode={setGridSubMode}
          dayJobs={dayJobs}
          setReorderList={setReorderList}
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

      </ScrollView>

      {/* Feb-2026 · Schedule inline-edit sheet. In-place mutate on
          save; drops the card on delete. Admin-gated at the button
          level; backend PUT + DELETE also role-gate. */}
      <ScheduleJobEditSheet
        open={!!editingJob}
        job={editingJob}
        onClose={() => setEditingJob(null)}
        onSaved={(patched) => {
          patchJobInPlace(patched);
          setEditingJob(null);
        }}
        onDeleted={(jid) => {
          removeJobInPlace(jid);
          setEditingJob(null);
        }}
      />

      {/* Reassign Tech Modal */}
      <Modal visible={reassignOpen} transparent animationType="fade" onRequestClose={() => setReassignOpen(false)}>
        <View style={{ flex: 1, backgroundColor: "rgba(0,0,0,0.5)", alignItems: "center", justifyContent: "center", paddingHorizontal: 24 }}>
          <View style={{ width: "100%", maxWidth: 380, backgroundColor: colors.surface, borderRadius: 16, padding: 20 }} testID="reassign-modal">
            <Text style={{ fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface, marginBottom: 8 }}>
              Reassign {checked.size} job{checked.size !== 1 ? "s" : ""}
            </Text>
            <Text style={{ fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted, marginBottom: spacing.lg }}>
              Select a technician:
            </Text>
            <ScrollView style={{ maxHeight: 300 }}>
              {techs.map((t) => (
                <Pressable
                  key={t.id}
                  onPress={() => setReassignTechId(t.id)}
                  style={{
                    flexDirection: "row", alignItems: "center", gap: 10,
                    paddingVertical: 10, paddingHorizontal: 12, borderRadius: radius.md,
                    backgroundColor: reassignTechId === t.id ? colors.brandTertiary : "transparent",
                    marginBottom: 4,
                  }}
                  testID={`reassign-tech-${t.id}`}
                >
                  <View style={{
                    width: 20, height: 20, borderRadius: 10,
                    borderWidth: 2, borderColor: reassignTechId === t.id ? colors.brand : colors.border,
                    backgroundColor: reassignTechId === t.id ? colors.brand : "transparent",
                    alignItems: "center", justifyContent: "center",
                  }}>
                    {reassignTechId === t.id ? <Ionicons name="checkmark" size={12} color="#fff" /> : null}
                  </View>
                  <Text style={{ fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface }}>{t.name}</Text>
                </Pressable>
              ))}
              {techs.length === 0 ? (
                <Text style={{ fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted, textAlign: "center", paddingVertical: 20 }}>
                  No technicians available
                </Text>
              ) : null}
            </ScrollView>
            <View style={{ flexDirection: "row", gap: 12, justifyContent: "flex-end", marginTop: spacing.lg }}>
              <Pressable
                onPress={() => setReassignOpen(false)}
                style={{ paddingHorizontal: 16, paddingVertical: 10, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border }}
                testID="reassign-cancel"
              >
                <Text style={{ fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface }}>Cancel</Text>
              </Pressable>
              <Pressable
                onPress={bulkReassign}
                disabled={!reassignTechId || busy}
                style={{
                  paddingHorizontal: 16, paddingVertical: 10, borderRadius: radius.md,
                  backgroundColor: reassignTechId ? colors.brand : colors.border,
                  opacity: (!reassignTechId || busy) ? 0.5 : 1,
                }}
                testID="reassign-confirm"
              >
                <Text style={{ fontFamily: font.bold, fontSize: fontSize.base, color: "#fff" }}>Assign</Text>
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>
    </View>
  );
}

/* ═══ Grid view ══════════════════════════════════════════════════════ */
function GridView(props: any) {
  const {
    focus, setFocus, jobs, loading, checked, onToggle, canWrite,
    rearrangeMode, onToggleRearrange, onSaveReorder, onShift,
    onBulkComplete, onBulkDelete, onOpenMove, onOpenReassign, moveOpen, setMoveOpen, moveDate, setMoveDate,
    onConfirmMove, busy, onOpenJob, onNewJob, isAdmin, hourlyData,
    weatherWidget, onOpenEdit, onSelectAllInView, onClearSelection, role,
    gridSubMode, setGridSubMode, dayJobs, setReorderList,
  } = props;
  const focusISO = iso(focus);
  const isToday = focusISO === iso(new Date());

  /** Next-job: first non-terminal job in route order. */
  const _TERMINAL = new Set(["completed", "canceled", "cancelled", "skipped", "could_not_service"]);
  const nextJob = jobs.find((j: Job) => !_TERMINAL.has((j.status || "").toLowerCase()));

  return (
    <View style={{ padding: spacing.md, paddingBottom: spacing["3xl"] }}>
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

      {/* Bulk-action pills. Buttons stay visible but disable when nothing is checked.
          Phase 22 · 2026-08-02 · Sub-item A — techs only get Complete;
          Move/Delete/Assign/Rearrange are gated to isAdmin per user brief. */}
      {canWrite ? (
        <View style={gStyles.pillRow} testID="grid-bulk-pills">
          {/* Feb-2026 · Select-all / Clear pills — admin+ only.
              Renders BEFORE the action pills so the affordance is
              reachable even when no cards are checked yet. */}
          {isAdmin && onSelectAllInView ? (
            <Pressable
              onPress={onSelectAllInView}
              disabled={!jobs.length}
              style={[gStyles.pill, gStyles.pillPurple, !jobs.length && { opacity: 0.4 }]}
              testID="grid-bulk-select-all"
            >
              <Ionicons name="checkbox-outline" size={13} color="#fff" />
              <Text style={gStyles.pillText}>Select all ({jobs.length})</Text>
            </Pressable>
          ) : null}
          {isAdmin && onClearSelection && checked.size > 0 ? (
            <Pressable
              onPress={onClearSelection}
              style={[gStyles.pill, gStyles.pillGrey]}
              testID="grid-bulk-clear-selection"
            >
              <Ionicons name="close-outline" size={13} color="#fff" />
              <Text style={gStyles.pillText}>Clear</Text>
            </Pressable>
          ) : null}
          <Pressable
            onPress={onBulkComplete}
            disabled={busy || checked.size === 0}
            style={[gStyles.pill, gStyles.pillGreen, (busy || checked.size === 0) && { opacity: 0.4 }]}
            testID="grid-bulk-complete"
          >
            <Ionicons name="checkmark-circle" size={13} color="#fff" />
            <Text style={gStyles.pillText}>Complete ({checked.size})</Text>
          </Pressable>
          {isAdmin ? (
          <Pressable
            onPress={onOpenMove}
            disabled={busy || checked.size === 0}
            style={[gStyles.pill, gStyles.pillBlue, (busy || checked.size === 0) && { opacity: 0.4 }]}
            testID="grid-bulk-move"
          >
            <Ionicons name="calendar-outline" size={13} color="#fff" />
            <Text style={gStyles.pillText}>Move ({checked.size})</Text>
          </Pressable>
          ) : null}
          {isAdmin ? (
          <Pressable
            onPress={onBulkDelete}
            disabled={busy || checked.size === 0}
            style={[gStyles.pill, gStyles.pillRed, (busy || checked.size === 0) && { opacity: 0.4 }]}
            testID="grid-bulk-delete"
          >
            <Ionicons name="trash-outline" size={13} color="#fff" />
            <Text style={gStyles.pillText}>Delete ({checked.size})</Text>
          </Pressable>
          ) : null}
          {isAdmin ? (
          <Pressable
            onPress={onOpenReassign}
            disabled={busy || checked.size === 0}
            style={[gStyles.pill, gStyles.pillOrange, (busy || checked.size === 0) && { opacity: 0.4 }]}
            testID="grid-bulk-reassign"
          >
            <Ionicons name="people-outline" size={13} color="#fff" />
            <Text style={gStyles.pillText}>Assign ({checked.size})</Text>
          </Pressable>
          ) : null}
          {isAdmin ? (
          <Pressable
            onPress={rearrangeMode ? onSaveReorder : onToggleRearrange}
            style={[gStyles.pill, rearrangeMode ? gStyles.pillGreen : gStyles.pillPurple]}
            testID="grid-bulk-rearrange"
          >
            <Ionicons name={rearrangeMode ? "save-outline" : "reorder-three-outline"} size={13} color="#fff" />
            <Text style={gStyles.pillText}>{rearrangeMode ? "Save order" : "Rearrange"}</Text>
          </Pressable>
          ) : null}
        </View>
      ) : null}

      {/* On My Way — next job primary CTA */}
      {nextJob ? (
        <OnMyWayButton
          jobId={nextJob.id}
          customerName={nextJob.customer_name}
          variant="primary"
          role={role}
          testID="on-my-way-next-btn"
        />
      ) : null}

      {/* List | Map toggle */}
      <View style={gStyles.subModeRow} testID="grid-sub-mode-toggle">
        {(["list", "map"] as const).map((sm) => {
          const active = gridSubMode === sm;
          return (
            <Pressable
              key={sm}
              onPress={() => setGridSubMode(sm)}
              style={[gStyles.subModeBtn, active && gStyles.subModeBtnActive]}
              testID={`grid-sub-mode-${sm}`}
            >
              <Ionicons
                name={sm === "list" ? "list-outline" : "map-outline"}
                size={12}
                color={active ? "#fff" : colors.onSurfaceSecondary}
              />
              <Text style={[gStyles.subModeText, active && { color: "#fff" }]}>
                {sm === "list" ? "List" : "Map"}
              </Text>
            </Pressable>
          );
        })}
      </View>

      {gridSubMode === "map" ? (
        <ScheduleMap jobs={dayJobs || jobs} testID="schedule-day-map" />
      ) : (
        <>
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
      ) : rearrangeMode && Platform.OS !== "web" ? (
        <DraggableFlatList
          data={jobs}
          keyExtractor={(item: Job) => item.id}
          scrollEnabled={false}
          onDragEnd={({ data }: { data: Job[] }) => {
            setReorderList(data);
            // Auto-save reorder on drop (admin only)
            if (isAdmin) {
              api.post("/jobs/reorder", { job_ids: data.map((j: Job) => j.id) })
                .then(() => {})
                .catch((e: any) => {
                  // Snap back to original order
                  setReorderList(dayJobs || jobs);
                  Alert.alert("Reorder failed", e?.message || "Could not save new order.");
                });
            }
          }}
          renderItem={({ item, getIndex, drag, isActive }: RenderItemParams<Job>) => {
            const idx = getIndex() ?? 0;
            return (
              <ScaleDecorator>
                <JobRow
                  key={item.id}
                  job={item}
                  idx={idx}
                  checked={checked.has(item.id)}
                  onCheck={() => onToggle(item.id)}
                  onOpen={() => onOpenJob(item.id)}
                  rearrangeMode={rearrangeMode}
                  onShift={onShift}
                  first={idx === 0}
                  last={idx === jobs.length - 1}
                  hourlyData={hourlyData}
                  isAdminForCard={isAdmin}
                  onEdit={isAdmin ? onOpenEdit : undefined}
                  role={role}
                  onDrag={drag}
                  isDragging={isActive}
                />
              </ScaleDecorator>
            );
          }}
          testID="grid-dnd-list"
        />
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
          isAdminForCard={isAdmin}
          onEdit={isAdmin ? onOpenEdit : undefined}
          role={role}
        />
      ))}
        </>
      )}
      {weatherWidget ? (
        <View style={{ paddingHorizontal: spacing.xs, paddingTop: spacing.lg }} testID="schedule-weather-bottom">
          {weatherWidget}
        </View>
      ) : null}
    </View>
  );
}

function JobRow({ job, idx, checked, onCheck, onOpen, rearrangeMode, onShift, first, last, hourlyData, isAdminForCard, onEdit, role, onDrag, isDragging }: any) {
  const pill = STATUS_PILL[(job.status || "scheduled").toLowerCase()] || STATUS_PILL.scheduled;
  const svc = SERVICE_COLOR(job.service_type);
  // Feb-2026 · Schedule-UI · colored left border.
  const statusBorder = getStatusBorderColor(job.status);
  const _TERMINAL_STATUS = new Set(["completed", "canceled", "cancelled", "skipped", "could_not_service"]);
  const showOnMyWay = !_TERMINAL_STATUS.has((job.status || "").toLowerCase());
  const showDragHandle = rearrangeMode && isAdminForCard && onDrag;
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
      style={[gStyles.card, { borderLeftWidth: 4, borderLeftColor: statusBorder }, isDragging && { opacity: 0.7, shadowOpacity: 0.3 }]}
      onPress={rearrangeMode ? undefined : onOpen}
      onLongPress={showDragHandle ? onDrag : undefined}
      testID={`grid-job-${job.id}`}
      hitSlop={4}
    >
      {showDragHandle ? (
        <Pressable
          onPressIn={onDrag}
          style={gStyles.dragHandle}
          testID={`grid-drag-handle-${job.id}`}
        >
          <Ionicons name="reorder-three" size={18} color={colors.muted} />
        </Pressable>
      ) : null}
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
        {/* Phase 27 · Feb-2026 — inline tech avatar chip next to
            customer line. 20dp footprint stays under the existing
            line-height so row height is unchanged. Feb-2026 · the
            per-card tech avatar that rendered the tech's initials
            (e.g. "MR") before the customer name was removed —
            the schedule day view is already tech-scoped in the
            header, so the per-card avatar was redundant clutter. */}
        <View style={{ flexDirection: "row", alignItems: "center", gap: 6, marginTop: 2 }}>
          <Text style={gStyles.cust} numberOfLines={1}>{job.customer_name || "Unknown"}</Text>
        </View>
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
        {/* Feb-2026 · schedule polish — gate-code amber badge +
            optional access-instructions bullet. */}
        {(job.customer_gate_code || job.gate_code || job.access_notes) ? (
          <View style={gStyles.gateChip} testID={`job-gate-code-${job.id}`}>
            <Ionicons name="key-outline" size={11} color="#78350F" />
            {(job.customer_gate_code || job.gate_code) ? (
              <Text style={gStyles.gateText}>
                Gate: {job.customer_gate_code || job.gate_code}
              </Text>
            ) : (
              <Text style={gStyles.gateText}>Access</Text>
            )}
            {job.access_notes ? (
              <Text
                style={gStyles.gateAccessText}
                numberOfLines={1}
                testID={`job-access-notes-${job.id}`}
              >
                {` · ${job.access_notes}`}
              </Text>
            ) : null}
          </View>
        ) : null}
        {/* Feb-2026 · schedule polish — combined notes call-out.
            Job-level ``notes`` render first; ``customer_notes`` /
            ``account_notes`` follow with a "Customer note:"
            prefix.  Tap the call-out to see the full text via
            an Alert.  Empty on all three ⇒ nothing rendered. */}
        {(() => {
          const jobNote = job.notes && String(job.notes).trim() ? String(job.notes) : "";
          const custNote = (job.customer_notes || job.account_notes)
            ? String(job.customer_notes || job.account_notes).trim() : "";
          if (!jobNote && !custNote) return null;
          const full = [
            jobNote ? jobNote + (job.notes_truncated ? "…" : "") : "",
            custNote ? `Customer note: ${custNote}` : "",
          ].filter(Boolean).join("\n\n");
          return (
            <Pressable
              onPress={(e) => { e?.stopPropagation?.(); Alert.alert("Notes", full); }}
              style={gStyles.notesCallout}
              testID={`job-notes-callout-${job.id}`}
            >
              <Ionicons name="document-text-outline" size={12} color="#2563EB"
                        style={{ marginTop: 1 }} />
              <View style={{ flex: 1, minWidth: 0 }}>
                {jobNote ? (
                  <Text
                    style={gStyles.notesCalloutJobText}
                    numberOfLines={2}
                    ellipsizeMode="tail"
                    testID={`job-${job.id}-notes`}
                  >
                    {jobNote}{job.notes_truncated ? "…" : ""}
                  </Text>
                ) : null}
                {custNote ? (
                  <Text
                    style={gStyles.notesCalloutCustText}
                    numberOfLines={2}
                    ellipsizeMode="tail"
                    testID={`job-notes-preview-${job.id}`}
                  >
                    <Text style={{ fontWeight: "700" }}>Customer note: </Text>
                    {custNote}
                  </Text>
                ) : null}
              </View>
            </Pressable>
          );
        })()}
        {job.address ? (
          <Text style={gStyles.addr} numberOfLines={1}>{job.address}</Text>
        ) : null}
        <View style={gStyles.metaRow}>
          <Ionicons name="reader-outline" size={12} color={colors.muted} />
          <Text style={gStyles.metaText}>{jobHours(job)}</Text>
          {/* Phase 30X · time-of-day removed. Schedule is per-day. */}
        </View>
        {showOnMyWay ? (
          <OnMyWayButton
            jobId={job.id}
            customerName={job.customer_name}
            variant="compact"
            role={role}
          />
        ) : null}
        {showOnMyWay ? (
          <CouldNotServiceButton
            jobId={job.id}
            jobStatus={job.status}
            role={role}
            variant="compact"
          />
        ) : null}
      </View>
      <View style={[gStyles.statusPill, { backgroundColor: pill.bg }]}>
        <Text style={[gStyles.statusText, { color: pill.fg }]}>{pill.label}</Text>
      </View>
      <View testID={`grid-open-${job.id}`}>
        <Ionicons name="chevron-forward" size={20} color={colors.muted} />
      </View>
      {/* Feb-2026 · Schedule inline edit affordance — admin+ only.
          Backend PUT /api/jobs/{id} enforces the same role gate. */}
      {isAdminForCard && onEdit ? (
        <Pressable
          onPress={() => onEdit(job)}
          hitSlop={8}
          testID={`grid-edit-${job.id}`}
          accessibilityLabel="Edit job"
          style={gStyles.editBtn}
        >
          <Ionicons name="pencil-outline" size={16} color={colors.muted} />
        </Pressable>
      ) : null}
    </Pressable>
  );
}

/* ═══ Calendar view ══════════════════════════════════════════════════ */
function CalendarView({
  weekDays, weekTitle, jobsByDay, showBH, onToggleBH, onPrev, onNext, onOpenJob,
  weatherWidget,
}: any) {
  return (
    <View style={{ flexGrow: 1 }}>
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
    </View>
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
    flexDirection: "row", alignItems: "center", alignSelf: "flex-start", gap: 4,
    backgroundColor: "#FEF3C7", borderColor: "#FCD34D", borderWidth: 1,
    paddingHorizontal: 8, paddingVertical: 2, borderRadius: 6, marginTop: 4,
    maxWidth: "100%",
  },
  gateText: {
    fontFamily: font.bold, fontSize: 10, color: "#78350F",
    letterSpacing: 0.5,
  },
  gateAccessText: {
    fontFamily: font.medium, fontSize: 10, color: "#78350F",
    flexShrink: 1,
  },
  notesCallout: {
    flexDirection: "row", alignItems: "flex-start", gap: 6,
    backgroundColor: "#EFF6FF", borderColor: "#BFDBFE", borderWidth: 1,
    borderLeftColor: "#3B82F6", borderLeftWidth: 4,
    paddingHorizontal: 8, paddingVertical: 6, borderRadius: 6,
    marginTop: 4,
  },
  notesCalloutJobText: {
    fontFamily: font.medium, fontSize: 11, color: "#1E3A8A", lineHeight: 15,
  },
  notesCalloutCustText: {
    fontFamily: font.regular, fontSize: 11, color: "#3730A3", lineHeight: 15,
    marginTop: 2,
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
  pillOrange: { backgroundColor: "#D97706" },
  pillPurple: { backgroundColor: "#7C3AED" },
  pillGrey:   { backgroundColor: "#6B7280" },
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
  subModeRow: {
    flexDirection: "row", gap: spacing.xs, marginBottom: spacing.sm,
  },
  subModeBtn: {
    flex: 1, height: 32,
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: 4,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
    borderWidth: 1, borderColor: colors.border,
  },
  subModeBtnActive: { backgroundColor: colors.brand, borderColor: colors.brand },
  subModeText: { fontFamily: font.bold, fontSize: 11, color: colors.onSurfaceSecondary },
  dragHandle: {
    justifyContent: "center", alignItems: "center",
    width: 28, marginRight: 2,
  },
  newBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: spacing.md, height: 36, borderRadius: radius.md,
    backgroundColor: colors.brand,
  },
  newBtnText: { fontFamily: font.bold, fontSize: fontSize.sm, color: "#fff" },
  // Feb-2026 · Schedule inline-edit — Pencil affordance on admin cards.
  editBtn: { padding: spacing.xs, marginLeft: spacing.xs, alignSelf: "center" },
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
