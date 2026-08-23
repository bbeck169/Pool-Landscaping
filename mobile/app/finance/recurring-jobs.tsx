// Phase 35 · Feb-2026 — Mobile Recurring Jobs (P1.1 Finance Parity).
// Phase 41.2 · refactored onto the shared `<AdminListPage>` primitive.
// Feb-2026 · Task B mobile · added create/edit sheet + Ends radio
//   (Never | On date) + monthly nth-weekday pattern + Stop action.
//
// Web parity: `frontend/src/pages/admin/RecurringJobs.jsx`.
// Backend: canonical `/api/recurring-jobs` CRUD, POST /generate,
//   POST /stop, all fields (recurrence_never_ends, monthly_pattern,
//   monthly_nth_week, monthly_weekday).
// Admin / super-admin / manager only.
import React, { useCallback, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, Switch, TextInput, Pressable, Platform,
  Modal, ScrollView,
} from "react-native";
import { useFocusEffect } from "expo-router";
import DateTimePicker from "@react-native-community/datetimepicker";
import dayjs from "dayjs";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize, money } from "@/src/theme";
import { PrimaryButton, Sheet } from "@/src/components/ui";
import { showConfirm } from "@/src/components/ConfirmModal";
import { AdminListPage } from "@/src/components/layout/AdminListPage";

type RecurringJob = {
  id: string;
  customer_id?: string;
  customer_name?: string;
  service_type?: string;
  frequency: "weekly" | "biweekly" | "monthly" | "quarterly" | "semi_annual" | "custom";
  day_of_week?: number;
  day_of_month?: number;
  interval_days?: number;
  start_date?: string;
  end_date?: string | null;
  price_cents?: number;
  active: boolean;
  notes?: string;
  recurrence_never_ends?: boolean;
  monthly_pattern?: "day_of_month" | "nth_weekday";
  monthly_nth_week?: "first" | "second" | "third" | "fourth" | "last";
  monthly_weekday?: number;
};

const DOW_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];  // 0=Mon…6=Sun (matches backend)
const NTH_WEEK_OPTS: NonNullable<RecurringJob["monthly_nth_week"]>[] =
  ["first", "second", "third", "fourth", "last"];
const NTH_WEEK_LABELS: Record<string, string> = {
  first: "1st", second: "2nd", third: "3rd", fourth: "4th", last: "Last",
};
const FREQ_OPTS: RecurringJob["frequency"][] = ["weekly", "biweekly", "monthly", "quarterly", "semi_annual"];

function todayIso(): string {
  return dayjs().format("YYYY-MM-DD");
}

function cadenceLabel(r: RecurringJob): string {
  if (r.frequency === "weekly" || r.frequency === "biweekly") {
    return `${r.frequency} (${DOW_LABELS[r.day_of_week ?? 0] || "?"})`;
  }
  if (r.frequency === "monthly") {
    if (r.monthly_pattern === "nth_weekday" && r.monthly_nth_week && r.monthly_weekday != null) {
      return `monthly (${NTH_WEEK_LABELS[r.monthly_nth_week]} ${DOW_LABELS[r.monthly_weekday]})`;
    }
    return `monthly (day ${r.day_of_month ?? "?"})`;
  }
  if (r.frequency === "custom") return `custom (${r.interval_days ?? "?"}d)`;
  return r.frequency;
}

/** Chip row — pick one of `options`. */
function ChipRow<T extends string | number>({
  options, value, onChange, labelFor, testIDPrefix,
}: {
  options: T[];
  value: T | undefined;
  onChange: (v: T) => void;
  labelFor?: (v: T) => string;
  testIDPrefix: string;
}) {
  return (
    <View style={s.chipRow}>
      {options.map((opt) => {
        const active = value === opt;
        return (
          <Pressable
            key={String(opt)}
            onPress={() => onChange(opt)}
            style={[s.chip, active && s.chipActive]}
            testID={`${testIDPrefix}-${String(opt)}`}
          >
            <Text style={[s.chipText, active && s.chipTextActive]}>
              {labelFor ? labelFor(opt) : String(opt)}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

/** Native date input — bottom-sheet on iOS, dialog on Android. */
function DateField({
  label, value, onChange, testID, disabled,
}: {
  label: string;
  value: string | null | undefined;
  onChange: (iso: string) => void;
  testID: string;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const shown = value || todayIso();

  const handle = (_e: unknown, picked?: Date) => {
    if (Platform.OS === "android") setOpen(false);
    if (picked) onChange(dayjs(picked).format("YYYY-MM-DD"));
  };

  return (
    <View style={{ opacity: disabled ? 0.5 : 1 }}>
      <Text style={s.fieldLabel}>{label}</Text>
      <Pressable
        onPress={() => !disabled && setOpen(true)}
        style={s.dateField}
        testID={testID}
        disabled={disabled}
      >
        <Text style={s.dateFieldText}>{value || "(none)"}</Text>
      </Pressable>
      {open && Platform.OS === "ios" ? (
        <Modal transparent animationType="slide" onRequestClose={() => setOpen(false)}>
          <Pressable style={s.pickerBackdrop} onPress={() => setOpen(false)} />
          <View style={s.pickerCard}>
            <DateTimePicker
              value={new Date(shown)}
              mode="date"
              display="spinner"
              onChange={handle}
            />
            <Pressable style={s.pickerDoneBtn} onPress={() => setOpen(false)}
                        testID={`${testID}-done`}>
              <Text style={s.pickerDoneText}>Done</Text>
            </Pressable>
          </View>
        </Modal>
      ) : open ? (
        <DateTimePicker
          value={new Date(shown)}
          mode="date"
          display="default"
          onChange={handle}
        />
      ) : null}
    </View>
  );
}

export default function RecurringJobsMobile() {
  const [rows, setRows] = useState<RecurringJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [editing, setEditing] = useState<Partial<RecurringJob> | null>(null);
  const [saveErr, setSaveErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r: any = await api.get("/recurring-jobs");
      setRows(Array.isArray(r) ? r : r?.items || []);
    } catch {
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const openCreate = useCallback(() => {
    setSaveErr(null);
    // Ends=Never is the product default.
    setEditing({
      frequency: "weekly",
      day_of_week: 0,
      start_date: todayIso(),
      price_cents: 12000,
      active: true,
      recurrence_never_ends: true,
      end_date: null,
      monthly_pattern: "day_of_month",
    });
  }, []);

  const openEdit = useCallback((row: RecurringJob) => {
    setSaveErr(null);
    // Legacy rows: if neither flag nor end_date, normalize to Never
    // (mirrors the web RecurringJobs.jsx openEdit).
    const neverEnds = row.recurrence_never_ends === true
      || (row.recurrence_never_ends == null && !row.end_date);
    setEditing({ ...row, recurrence_never_ends: neverEnds });
  }, []);

  const closeSheet = useCallback(() => { setEditing(null); setSaveErr(null); }, []);

  const save = useCallback(async () => {
    if (!editing) return;
    setSaveErr(null);
    const payload: any = { ...editing };
    // Same exclusivity rule as web — Never wins, end_date is nulled.
    if (payload.recurrence_never_ends) payload.end_date = null;
    try {
      if (editing.id) {
        await api.patch(`/recurring-jobs/${editing.id}`, payload);
      } else {
        await api.post("/recurring-jobs", payload);
      }
      setEditing(null);
      await load();
    } catch (e: any) {
      setSaveErr(e?.message || "Save failed");
    }
  }, [editing, load]);

  const toggleActive = useCallback(async (row: RecurringJob) => {
    setBusyId(row.id);
    try {
      await api.patch(`/recurring-jobs/${row.id}`, { active: !row.active });
      await load();
    } catch { /* ignore */ } finally { setBusyId(null); }
  }, [load]);

  const generateNow = useCallback((row: RecurringJob) => {
    showConfirm({
      title: `Generate jobs for "${row.customer_name || row.customer_id}"?`,
      message:
        "Creates the next ~2 weeks of scheduled jobs from this template. Safe to re-run.",
      confirmLabel: "Generate",
      onConfirm: async () => {
        setBusyId(row.id);
        try {
          const through = dayjs().add(14, "day").format("YYYY-MM-DD");
          await api.post(`/recurring-jobs/${row.id}/generate?through=${through}`, {});
          await load();
        } catch { /* ignore */ } finally { setBusyId(null); }
      },
    });
  }, [load]);

  const stopRecurrence = useCallback((row: RecurringJob) => {
    showConfirm({
      title: "Stop generating future occurrences?",
      message:
        "Unstarted future visits will be removed. Started/completed visits and today's route stay untouched.",
      confirmLabel: "Stop",
      onConfirm: async () => {
        setBusyId(row.id);
        try {
          await api.post(`/recurring-jobs/${row.id}/stop`, {});
          await load();
        } catch { /* ignore */ } finally { setBusyId(null); }
      },
    });
  }, [load]);

  const sheetTitle = useMemo(
    () => editing?.id ? "Edit recurring job" : "New recurring job",
    [editing?.id],
  );

  const isMonthly = editing?.frequency === "monthly";
  const isNthWeekday = isMonthly && editing?.monthly_pattern === "nth_weekday";
  const isWeeklyish = editing?.frequency === "weekly" || editing?.frequency === "biweekly";

  return (
    <AdminListPage
      title="Recurring Jobs"
      testID="recurring-jobs-page"
      loading={loading}
      isEmpty={rows.length === 0}
      refreshing={refreshing}
      onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }}
      emptyIcon="repeat-outline"
      emptyTitle="No recurring jobs yet"
      emptySubtitle="Tap + New below to add one, or create on the desktop admin page."
      emptyTestID="recurring-empty"
      headerExtra={
        <View style={{ gap: spacing.sm }}>
          <Text style={s.hint} testID="recurring-hint">
            Auto-generates a rolling 2-week horizon of jobs (nightly at 02:00 UTC).
          </Text>
          <PrimaryButton
            title="+ New recurring job"
            onPress={openCreate}
            testID="recurring-new-btn"
          />
        </View>
      }
    >
      {rows.map((r) => (
        <View key={r.id} style={s.row} testID={`recurring-row-${r.id}`}>
          <View style={s.rowHead}>
            <Pressable onPress={() => openEdit(r)} style={{ flex: 1 }}
                        testID={`recurring-edit-${r.id}`}>
              <Text style={s.customer}>{r.customer_name || r.customer_id || "—"}</Text>
            </Pressable>
            <Switch
              value={r.active}
              onValueChange={() => toggleActive(r)}
              disabled={busyId === r.id}
              testID={`recurring-toggle-${r.id}`}
            />
          </View>
          <View style={s.metaRow}>
            <Text style={s.meta}>{cadenceLabel(r)}</Text>
            <Text style={s.meta}>{money((r.price_cents || 0) / 100)}</Text>
          </View>
          {r.recurrence_never_ends ? (
            <Text style={s.meta} testID={`recurring-never-badge-${r.id}`}>
              Ends: Never (runs until manually stopped)
            </Text>
          ) : r.end_date ? (
            <Text style={s.meta}>Ends: {r.end_date}</Text>
          ) : null}
          {r.notes ? (
            <Text style={s.notes} numberOfLines={2}>{r.notes}</Text>
          ) : null}
          <View style={s.rowActions}>
            <PrimaryButton
              title={busyId === r.id ? "Working…" : "Generate now"}
              onPress={() => generateNow(r)}
              disabled={busyId === r.id || !r.active}
              testID={`recurring-generate-${r.id}`}
            />
            {r.active ? (
              <PrimaryButton
                title="Stop"
                variant="outline"
                onPress={() => stopRecurrence(r)}
                disabled={busyId === r.id}
                testID={`recurring-stop-${r.id}`}
              />
            ) : null}
          </View>
        </View>
      ))}

      <Sheet
        visible={!!editing}
        onClose={closeSheet}
        title={sheetTitle}
        testID="recurring-sheet"
      >
        {editing ? (
          <View style={{ gap: spacing.md }}>
            <View>
              <Text style={s.fieldLabel}>Customer ID</Text>
              <TextInput
                value={editing.customer_id || ""}
                onChangeText={(t) => setEditing((x) => ({ ...(x || {}), customer_id: t }))}
                style={s.input}
                placeholder="83a42be6-…"
                autoCapitalize="none"
                testID="recurring-customer-id"
              />
            </View>
            <View>
              <Text style={s.fieldLabel}>Service type</Text>
              <TextInput
                value={editing.service_type || ""}
                onChangeText={(t) => setEditing((x) => ({ ...(x || {}), service_type: t }))}
                style={s.input}
                placeholder="e.g. Pool Cleaning"
                testID="recurring-service-type"
              />
            </View>

            <View>
              <Text style={s.fieldLabel}>Frequency</Text>
              <ChipRow
                options={FREQ_OPTS}
                value={editing.frequency}
                onChange={(v) => setEditing((x) => ({ ...(x || {}), frequency: v }))}
                testIDPrefix="recurring-freq"
              />
            </View>

            {isWeeklyish ? (
              <View>
                <Text style={s.fieldLabel}>Day of week</Text>
                <ChipRow
                  options={[0, 1, 2, 3, 4, 5, 6]}
                  value={editing.day_of_week}
                  onChange={(v) => setEditing((x) => ({ ...(x || {}), day_of_week: v }))}
                  labelFor={(v) => DOW_LABELS[v as number]}
                  testIDPrefix="recurring-dow"
                />
              </View>
            ) : null}

            {isMonthly ? (
              <>
                <View>
                  <Text style={s.fieldLabel}>Monthly pattern</Text>
                  <ChipRow
                    options={["day_of_month", "nth_weekday"] as const}
                    value={editing.monthly_pattern || "day_of_month"}
                    onChange={(v) => setEditing((x) => ({ ...(x || {}), monthly_pattern: v as any }))}
                    labelFor={(v) => v === "day_of_month" ? "Same day of month" : "Nth weekday"}
                    testIDPrefix="recurring-monthly-pattern"
                  />
                </View>
                {isNthWeekday ? (
                  <>
                    <View>
                      <Text style={s.fieldLabel}>Week of month</Text>
                      <ChipRow
                        options={NTH_WEEK_OPTS}
                        value={editing.monthly_nth_week}
                        onChange={(v) => setEditing((x) => ({ ...(x || {}), monthly_nth_week: v }))}
                        labelFor={(v) => NTH_WEEK_LABELS[v]}
                        testIDPrefix="recurring-nth-week"
                      />
                    </View>
                    <View>
                      <Text style={s.fieldLabel}>Weekday</Text>
                      <ChipRow
                        options={[0, 1, 2, 3, 4, 5, 6]}
                        value={editing.monthly_weekday}
                        onChange={(v) => setEditing((x) => ({ ...(x || {}), monthly_weekday: v }))}
                        labelFor={(v) => DOW_LABELS[v as number]}
                        testIDPrefix="recurring-monthly-weekday"
                      />
                    </View>
                  </>
                ) : (
                  <View>
                    <Text style={s.fieldLabel}>Day of month (1–31)</Text>
                    <TextInput
                      value={String(editing.day_of_month ?? "")}
                      onChangeText={(t) => setEditing((x) => ({
                        ...(x || {}),
                        day_of_month: Number(t.replace(/[^0-9]/g, "")) || undefined,
                      }))}
                      keyboardType="numeric"
                      style={s.input}
                      testID="recurring-day-of-month"
                    />
                  </View>
                )}
              </>
            ) : null}

            <DateField
              label="Start date"
              value={editing.start_date}
              onChange={(iso) => setEditing((x) => ({ ...(x || {}), start_date: iso }))}
              testID="recurring-start-date"
            />

            {/* Ends radio · Never (default) | On date */}
            <View style={s.endsBox} testID="recurring-ends-box">
              <Text style={s.fieldLabel}>Ends</Text>
              <Pressable
                onPress={() => setEditing((x) => ({ ...(x || {}), recurrence_never_ends: true, end_date: null }))}
                style={s.radioRow}
                testID="recurring-ends-never"
              >
                <View style={[s.radioDot, editing.recurrence_never_ends && s.radioDotActive]} />
                <View style={{ flex: 1 }}>
                  <Text style={s.radioLabel}>Never</Text>
                  <Text style={s.meta}>Runs until manually stopped.</Text>
                </View>
              </Pressable>
              <Pressable
                onPress={() => setEditing((x) => ({ ...(x || {}), recurrence_never_ends: false }))}
                style={s.radioRow}
                testID="recurring-ends-on-date"
              >
                <View style={[s.radioDot, !editing.recurrence_never_ends && s.radioDotActive]} />
                <View style={{ flex: 1 }}>
                  <Text style={s.radioLabel}>On date</Text>
                  <DateField
                    label=""
                    value={editing.end_date}
                    onChange={(iso) => setEditing((x) => ({ ...(x || {}), end_date: iso, recurrence_never_ends: false }))}
                    testID="recurring-end-date"
                    disabled={!!editing.recurrence_never_ends}
                  />
                </View>
              </Pressable>
            </View>

            <View>
              <Text style={s.fieldLabel}>Price (dollars)</Text>
              <TextInput
                value={String(((editing.price_cents ?? 0) / 100).toFixed(2))}
                onChangeText={(t) => {
                  const num = parseFloat(t.replace(/[^0-9.]/g, "")) || 0;
                  setEditing((x) => ({ ...(x || {}), price_cents: Math.round(num * 100) }));
                }}
                keyboardType="decimal-pad"
                style={s.input}
                testID="recurring-price"
              />
            </View>

            <View>
              <Text style={s.fieldLabel}>Notes</Text>
              <TextInput
                value={editing.notes || ""}
                onChangeText={(t) => setEditing((x) => ({ ...(x || {}), notes: t }))}
                style={[s.input, { minHeight: 60 }]}
                multiline
                testID="recurring-notes"
              />
            </View>

            {saveErr ? <Text style={s.errorText} testID="recurring-error">{saveErr}</Text> : null}

            <PrimaryButton
              title={editing.id ? "Save changes" : "Create recurring job"}
              onPress={save}
              disabled={!editing.customer_id || !editing.service_type}
              testID="recurring-save-btn"
            />
          </View>
        ) : null}
      </Sheet>
    </AdminListPage>
  );
}

const s = StyleSheet.create({
  hint: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  row: {
    padding: spacing.md, borderRadius: radius.md, borderWidth: 1,
    borderColor: colors.border, backgroundColor: colors.surface, gap: spacing.sm,
  },
  rowHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  customer: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  metaRow: { flexDirection: "row", justifyContent: "space-between" },
  meta: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  notes: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
  rowActions: { flexDirection: "row", gap: spacing.sm },
  fieldLabel: {
    fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.muted,
    marginBottom: spacing.xs,
  },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.sm,
    padding: spacing.sm, fontSize: fontSize.base, color: colors.onSurface,
    backgroundColor: colors.surface,
  },
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.xs },
  chip: {
    paddingVertical: spacing.xs, paddingHorizontal: spacing.sm,
    borderRadius: radius.sm, borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  chipActive: { backgroundColor: colors.brand, borderColor: colors.brand },
  chipText: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurface },
  chipTextActive: { color: "#fff", fontFamily: font.semibold },
  dateField: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.sm,
    padding: spacing.sm, backgroundColor: colors.surface,
  },
  dateFieldText: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface },
  endsBox: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    padding: spacing.sm, gap: spacing.sm,
  },
  radioRow: { flexDirection: "row", gap: spacing.sm, alignItems: "flex-start" },
  radioDot: {
    width: 18, height: 18, borderRadius: 9, borderWidth: 2,
    borderColor: colors.border, marginTop: 2,
  },
  radioDotActive: { borderColor: colors.brand, backgroundColor: colors.brand },
  radioLabel: {
    fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface,
    marginBottom: spacing.xs,
  },
  pickerBackdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.4)" },
  pickerCard: {
    position: "absolute", left: 0, right: 0, bottom: 0,
    backgroundColor: colors.surface, padding: spacing.md,
    borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg,
  },
  pickerDoneBtn: {
    alignSelf: "flex-end", paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
  },
  pickerDoneText: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.brand },
  errorText: {
    fontFamily: font.regular, fontSize: fontSize.sm, color: "#B91C1C",
  },
});
