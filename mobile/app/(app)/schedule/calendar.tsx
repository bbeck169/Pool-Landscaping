/**
 * Phase 30 · Calendar Schedule (Expo mobile).
 *
 * Replaces the admin/tech Jobs list + old Section-based Schedule with a
 * unified date-driven calendar. Uses `react-native-calendars` (already
 * added to package.json in Phase 30). Views:
 *   • Month  — full grid with dot markers per job
 *   • Week   — 7-day agenda list starting on the focused date
 *   • Day    — single-day agenda
 *   • Custom — preset chips (7d / 30d / 90d) and free-form date range
 *
 * Customer role is redirected to `/(app)/jobs` (the untouched customer
 * services screen) since the calendar is an admin/dispatch/tech surface.
 */
import React, { useCallback, useMemo, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, FlatList } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { Calendar } from "react-native-calendars";
import { useFocusEffect, useRouter, Redirect } from "expo-router";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header, JobCard } from "@/src/components/widgets";

type Job = {
  id: string;
  scheduled_date?: string | null;
  scheduled_time?: string | null;
  service_type?: string;
  status?: string;
  customer_name?: string;
  technician_id?: string | null;
  address?: string;
};

const STATUS_COLORS: Record<string, string> = {
  scheduled:  "#0EA5E9",
  active:     "#059669",
  completed:  "#6B7280",
  pending:    "#F59E0B",
  requested:  "#8B5CF6",
  reopened:   "#DC2626",
  cancelled:  "#9CA3AF",
  on_hold:    "#F97316",
};

type ViewMode = "month" | "week" | "day" | "custom";

const iso = (d: Date) => d.toISOString().slice(0, 10);
const addDays = (d: Date, n: number) => { const c = new Date(d); c.setDate(c.getDate() + n); return c; };

export default function CalendarMobile() {
  const router = useRouter();
  const { user } = useAuth();
  const role = (user?.role as string) || "";

  // Customers keep their untouched services screen at /(app)/jobs.
  if (role === "customer") {
    return <Redirect href="/(app)/jobs" />;
  }

  const [mode, setMode] = useState<ViewMode>("month");
  const [selected, setSelected] = useState<string>(iso(new Date()));
  const [rangeFrom, setRangeFrom] = useState<string>(iso(new Date()));
  const [rangeTo, setRangeTo] = useState<string>(iso(addDays(new Date(), 6)));
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    setLoading(true); setErr("");
    try {
      // Fetch a ±90 day window; backend accepts optional start/end (Phase 30).
      const focus = new Date(selected + "T00:00:00");
      const start = iso(addDays(focus, -60));
      const end   = iso(addDays(focus,  90));
      const data = await api.get(`/jobs?start=${start}&end=${end}`);
      setJobs(Array.isArray(data) ? data : (data.items || data.data || []));
    } catch (e: any) {
      setErr(e.message || "Failed to load schedule");
    } finally { setLoading(false); }
  }, [selected]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  // Marked dates for the month calendar: coloured dots per status.
  const marked = useMemo(() => {
    const out: Record<string, any> = {};
    for (const j of jobs) {
      const d = j.scheduled_date;
      if (!d) continue;
      const colour = STATUS_COLORS[(j.status || "scheduled").toLowerCase()] || colors.brand;
      if (!out[d]) out[d] = { dots: [] };
      // De-dupe dots on the same day/status so a heavy day doesn't render 20 dots.
      if (!out[d].dots.some((x: any) => x.color === colour)) {
        out[d].dots.push({ color: colour });
      }
    }
    if (out[selected]) out[selected] = { ...out[selected], selected: true, selectedColor: colors.brand };
    else out[selected] = { selected: true, selectedColor: colors.brand };
    return out;
  }, [jobs, selected]);

  const visible = useMemo(() => {
    if (mode === "day") {
      return jobs.filter((j) => j.scheduled_date === selected);
    }
    if (mode === "week") {
      const start = new Date(selected + "T00:00:00");
      const end = addDays(start, 6);
      return jobs.filter((j) => {
        if (!j.scheduled_date) return false;
        return j.scheduled_date >= iso(start) && j.scheduled_date <= iso(end);
      });
    }
    if (mode === "custom") {
      return jobs.filter((j) => {
        if (!j.scheduled_date) return false;
        return j.scheduled_date >= rangeFrom && j.scheduled_date <= rangeTo;
      });
    }
    return jobs; // month view uses the calendar itself; list under it is unfiltered
  }, [jobs, mode, selected, rangeFrom, rangeTo]);

  const groupedByDate = useMemo(() => {
    const map: Record<string, Job[]> = {};
    for (const j of visible) {
      const d = j.scheduled_date || "Unscheduled";
      (map[d] = map[d] || []).push(j);
    }
    return Object.entries(map).sort((a, b) => a[0].localeCompare(b[0]));
  }, [visible]);

  const isAdmin = role === "admin" || role === "super_admin";
  const openJob = (id: string) => router.push(`/job/${id}` as any);
  const createJob = (date?: string) => router.push(`/job/new${date ? `?date=${date}` : ""}` as any);

  return (
    <View style={styles.root}>
      <Header
        title="Schedule"
        subtitle={loading ? "Loading…" : `${visible.length} jobs · ${mode}`}
        right={isAdmin ? (
          <Pressable onPress={() => createJob(selected)} testID="calendar-new-job">
            <Ionicons name="add-circle" size={26} color={colors.brand} />
          </Pressable>
        ) : undefined}
      />

      {/* View mode picker */}
      <View style={styles.modeRow} testID="calendar-mode-row">
        {(["month", "week", "day", "custom"] as const).map((m) => {
          const active = mode === m;
          return (
            <Pressable
              key={m}
              onPress={() => setMode(m)}
              style={[styles.mode, active && styles.modeActive]}
              testID={`calendar-mode-${m}`}
            >
              <Text style={[styles.modeText, active && { color: "#fff" }]}>
                {m.charAt(0).toUpperCase() + m.slice(1)}
              </Text>
            </Pressable>
          );
        })}
      </View>

      {mode === "custom" ? (
        <View style={styles.customRow} testID="calendar-custom-presets">
          {[
            { label: "7 days",  days: 6 },
            { label: "30 days", days: 29 },
            { label: "90 days", days: 89 },
          ].map((p) => (
            <Pressable
              key={p.label}
              onPress={() => { setRangeFrom(iso(new Date())); setRangeTo(iso(addDays(new Date(), p.days))); }}
              style={styles.chip}
              testID={`calendar-preset-${p.label.replace(/\s+/g, "-")}`}
            >
              <Text style={styles.chipText}>{p.label}</Text>
            </Pressable>
          ))}
          <Text style={styles.customLabel}>
            {rangeFrom} → {rangeTo}
          </Text>
        </View>
      ) : null}

      {err ? (
        <View style={styles.err} testID="calendar-error">
          <Ionicons name="warning-outline" size={14} color="#991B1B" />
          <Text style={styles.errText}>{err}</Text>
        </View>
      ) : null}

      {loading && jobs.length === 0 ? (
        <View style={styles.center}><ActivityIndicator color={colors.brand} /></View>
      ) : mode === "month" ? (
        <ScrollView contentContainerStyle={{ padding: spacing.md }}>
          <Calendar
            current={selected}
            onDayPress={(d) => setSelected(d.dateString)}
            markingType="multi-dot"
            markedDates={marked}
            theme={{
              todayTextColor: colors.brand,
              selectedDayBackgroundColor: colors.brand,
              arrowColor: colors.brand,
            }}
            testID="calendar-month"
          />
          <Text style={styles.sectionTitle}>
            Jobs on {selected} · {jobs.filter((j) => j.scheduled_date === selected).length}
          </Text>
          {jobs.filter((j) => j.scheduled_date === selected).map((j) => (
            <Pressable key={j.id} onPress={() => openJob(j.id)} testID={`calendar-job-${j.id}`}>
              <JobCard job={j} />
            </Pressable>
          ))}
          {jobs.filter((j) => j.scheduled_date === selected).length === 0 ? (
            <Pressable
              style={styles.emptyDay}
              onPress={() => createJob(selected)}
              testID="calendar-empty-day"
            >
              <Ionicons name="add-circle-outline" size={22} color={colors.brand} />
              <Text style={styles.emptyDayText}>Nothing on {selected}. Tap to create a job.</Text>
            </Pressable>
          ) : null}
        </ScrollView>
      ) : (
        <FlatList
          data={groupedByDate}
          keyExtractor={(item) => item[0]}
          contentContainerStyle={{ padding: spacing.md, paddingBottom: spacing["3xl"] }}
          renderItem={({ item }) => (
            <View>
              <Text style={styles.dateHeader}>{item[0]}</Text>
              {item[1].map((j) => (
                <Pressable key={j.id} onPress={() => openJob(j.id)} testID={`calendar-job-${j.id}`}>
                  <JobCard job={j} />
                </Pressable>
              ))}
            </View>
          )}
          ListEmptyComponent={() => (
            <View style={styles.emptyBig} testID="calendar-empty">
              <Ionicons name="calendar-outline" size={30} color={colors.muted} />
              <Text style={styles.emptyBigText}>Nothing scheduled in this range.</Text>
            </View>
          )}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  center: { padding: spacing.xl, alignItems: "center" },
  modeRow: {
    flexDirection: "row",
    gap: spacing.xs,
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.sm,
  },
  mode: {
    flex: 1,
    height: 36,
    borderRadius: radius.md,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
  },
  modeActive: { backgroundColor: colors.brand, borderColor: colors.brand },
  modeText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
  customRow: {
    flexDirection: "row",
    gap: spacing.xs,
    padding: spacing.md,
    alignItems: "center",
    flexWrap: "wrap",
  },
  chip: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
    borderRadius: radius.pill,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
  },
  chipText: { fontFamily: font.semibold, fontSize: fontSize.xs, color: colors.brand },
  customLabel: { fontFamily: font.medium, fontSize: fontSize.xs, color: colors.muted, marginLeft: "auto" },
  err: {
    flexDirection: "row", alignItems: "center", gap: spacing.xs,
    padding: spacing.sm, margin: spacing.md,
    backgroundColor: "#FEE2E2", borderRadius: radius.md,
  },
  errText: { fontFamily: font.medium, fontSize: fontSize.sm, color: "#991B1B", flex: 1 },
  sectionTitle: {
    fontFamily: font.semibold,
    fontSize: 11,
    letterSpacing: 1,
    color: colors.muted,
    textTransform: "uppercase",
    marginTop: spacing.md,
    marginBottom: spacing.sm,
  },
  dateHeader: {
    fontFamily: font.bold,
    fontSize: fontSize.base,
    color: colors.brand,
    marginTop: spacing.md,
    marginBottom: spacing.xs,
  },
  emptyDay: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    padding: spacing.md,
    marginTop: spacing.sm,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    borderStyle: "dashed",
  },
  emptyDayText: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted, flex: 1 },
  emptyBig: {
    padding: spacing.xl,
    alignItems: "center",
    gap: spacing.sm,
  },
  emptyBigText: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted },
});
