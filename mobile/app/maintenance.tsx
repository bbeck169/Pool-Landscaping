import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, FlatList, RefreshControl, Pressable, Platform, Alert, ScrollView } from "react-native";
import { Image } from "expo-image";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Loading, EmptyState, Sheet, PrimaryButton } from "@/src/components/ui";
import { Header, FilterRow } from "@/src/components/widgets";
import { formatCustomerName } from "@/src/utils/formatCustomerName";
import { ClickableAddress } from "@/src/components/interactive";
import AppTextInput from "@/src/components/ui/AppTextInput";

const FILTERS = [
  { key: "all", label: "All" },
  { key: "overdue", label: "Overdue" },
  { key: "due_soon", label: "Due Soon" },
  { key: "scheduled", label: "Scheduled" },
];

const STATUS_META: Record<string, { label: string; bg: string; fg: string }> = {
  overdue: { label: "Overdue", bg: "#FEE2E2", fg: "#DC2626" },
  due_soon: { label: "Due soon", bg: "#FEF9C3", fg: "#A16207" },
  ok: { label: "On track", bg: "#DCFCE7", fg: "#16A34A" },
  never: { label: "Never done", bg: "#F1F5F9", fg: "#64748B" },
};

const fmt = (d?: string | null) => {
  if (!d) return "—";
  try {
    return new Date(d + "T00:00:00").toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
  } catch {
    return d;
  }
};

const preset = (days: number) => {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
};

export default function Maintenance() {
  const router = useRouter();
  const [data, setData] = useState<any>({ summary: null, rows: [] });
  const [filter, setFilter] = useState("all");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  // Schedule sheet
  const [sched, setSched] = useState<any>(null); // {customer_id, customer_name, type, label, interval}
  const [techs, setTechs] = useState<any[]>([]);
  const [schedDate, setSchedDate] = useState("");
  const [schedTech, setSchedTech] = useState<string | null>(null);
  const [schedInterval, setSchedInterval] = useState("");
  const [scheduling, setScheduling] = useState(false);

  // History sheet
  const [hist, setHist] = useState<any>(null); // {customer_name, label}
  const [histRecords, setHistRecords] = useState<any[] | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await api.get("/maintenance/overview"));
    } catch {
      setData({ summary: null, rows: [] });
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const openSchedule = async (row: any, mtype: string) => {
    const t = row[mtype];
    setSched({ customer_id: row.customer_id, customer_name: row.customer_name, type: mtype, label: t.label, interval: t.interval_days });
    setSchedDate(preset(3));
    setSchedTech(null);
    setSchedInterval(String(t.interval_days));
    if (!techs.length) {
      try { setTechs(await api.get("/technicians")); } catch {}
    }
  };

  const doSchedule = async () => {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(schedDate)) {
      Alert.alert("Pick a date", "Enter the service date as YYYY-MM-DD.");
      return;
    }
    setScheduling(true);
    try {
      await api.post("/maintenance/schedule", {
        customer_id: sched.customer_id,
        type: sched.type,
        scheduled_date: schedDate,
        technician_id: schedTech,
        interval_days: parseInt(schedInterval) || undefined,
      });
      setSched(null);
      await load();
      Alert.alert("Scheduled ✅", `${sched.label} scheduled for ${fmt(schedDate)}.`);
    } catch (e: any) {
      Alert.alert("Failed", e.message || "Please try again.");
    } finally {
      setScheduling(false);
    }
  };

  const openHistory = async (row: any, mtype: string) => {
    setHist({ customer_name: row.customer_name, label: row[mtype].label });
    setHistRecords(null);
    try {
      setHistRecords(await api.get(`/maintenance/records?customer_id=${row.customer_id}&type=${mtype}`));
    } catch {
      setHistRecords([]);
    }
  };

  const rows = (data.rows || []).filter((r: any) => {
    if (filter === "all") return true;
    if (filter === "scheduled") return r.filter.upcoming_job || r.salt_cell.upcoming_job;
    return r.filter.status === filter || r.salt_cell.status === filter;
  });

  const s = data.summary;

  return (
    <View style={styles.root}>
      <Header title="Maintenance" back subtitle="Filter & salt cell cleanings" />

      {s ? (
        <View style={styles.summaryRow}>
          <SummaryCard label="Overdue" count={s.overdue} color="#DC2626" active={filter === "overdue"} onPress={() => setFilter("overdue")} testID="maint-sum-overdue" />
          <SummaryCard label="Due Soon" count={s.due_soon} color="#A16207" active={filter === "due_soon"} onPress={() => setFilter("due_soon")} testID="maint-sum-duesoon" />
          <SummaryCard label="Scheduled" count={s.scheduled} color="#0284C7" active={filter === "scheduled"} onPress={() => setFilter("scheduled")} testID="maint-sum-scheduled" />
        </View>
      ) : null}

      <FilterRow options={FILTERS} value={filter} onChange={setFilter} testID="maint-filter" />

      {loading ? (
        <Loading testID="maintenance-loading" />
      ) : rows.length === 0 ? (
        <EmptyState icon="water-outline" title="Nothing here" subtitle="No pools match this filter." testID="maintenance-empty" />
      ) : (
        <FlatList
          testID="maintenance-list"
          data={rows}
          keyExtractor={(r) => r.customer_id}
          contentContainerStyle={{ padding: spacing.lg, paddingTop: spacing.sm, paddingBottom: spacing["3xl"] }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
          renderItem={({ item }) => (
            <View style={styles.card} testID={`maint-${item.customer_id}`}>
              <Text style={styles.custName} numberOfLines={1}>{formatCustomerName(item)}</Text>
              {item.address ? <ClickableAddress address={item.address} style={styles.custAddr} testID={`maint-addr-${item.customer_id}`} /> : null}
              <TypeRow row={item} mtype="filter" onSchedule={openSchedule} onHistory={openHistory} onOpenJob={(id) => router.push(`/job/${id}`)} />
              <TypeRow row={item} mtype="salt_cell" onSchedule={openSchedule} onHistory={openHistory} onOpenJob={(id) => router.push(`/job/${id}`)} />
            </View>
          )}
        />
      )}

      {/* Schedule sheet */}
      <Sheet visible={!!sched} onClose={() => setSched(null)} title={sched ? `Schedule ${sched.label}` : ""} testID="maint-schedule-sheet">
        {sched ? (
          <ScrollView keyboardShouldPersistTaps="handled" style={{ maxHeight: 460 }}>
            <Text style={styles.schedSub}>{formatCustomerName(sched)}</Text>

            <Text style={styles.fieldLabel}>Service date</Text>
            <View style={styles.presetRow}>
              {[["Today", 0], ["+3 days", 3], ["+1 week", 7], ["+2 weeks", 14]].map(([lbl, d]) => (
                <Pressable key={lbl as string} style={[styles.preset, schedDate === preset(d as number) && styles.presetOn]} onPress={() => setSchedDate(preset(d as number))} testID={`maint-preset-${d}`}>
                  <Text style={[styles.presetText, schedDate === preset(d as number) && styles.presetTextOn]}>{lbl}</Text>
                </Pressable>
              ))}
            </View>
            <AppTextInput style={styles.input} value={schedDate} onChangeText={setSchedDate} placeholder="YYYY-MM-DD" placeholderTextColor={colors.muted} testID="maint-date-input" />

            <Text style={styles.fieldLabel}>Assign technician</Text>
            <View style={styles.presetRow}>
              <Pressable style={[styles.preset, !schedTech && styles.presetOn]} onPress={() => setSchedTech(null)} testID="maint-tech-none">
                <Text style={[styles.presetText, !schedTech && styles.presetTextOn]}>Unassigned</Text>
              </Pressable>
              {techs.map((t) => (
                <Pressable key={t.id} style={[styles.preset, schedTech === t.id && styles.presetOn]} onPress={() => setSchedTech(t.id)} testID={`maint-tech-${t.id}`}>
                  <Text style={[styles.presetText, schedTech === t.id && styles.presetTextOn]}>{t.name}</Text>
                </Pressable>
              ))}
            </View>

            <Text style={styles.fieldLabel}>Repeat every (days)</Text>
            <AppTextInput style={styles.input} value={schedInterval} onChangeText={setSchedInterval} keyboardType="number-pad" placeholder="90" placeholderTextColor={colors.muted} testID="maint-interval-input" />
            <Text style={styles.hint}>Sets how often the {sched.label.toLowerCase()} for this pool becomes due.</Text>

            <View style={{ height: spacing.md }} />
            <PrimaryButton title="Schedule Service" icon="calendar" loading={scheduling} onPress={doSchedule} testID="maint-schedule-confirm" />
          </ScrollView>
        ) : null}
      </Sheet>

      {/* History sheet */}
      <Sheet visible={!!hist} onClose={() => setHist(null)} title={hist ? `${hist.label} history` : ""} testID="maint-history-sheet">
        {hist ? (
          <ScrollView style={{ maxHeight: 480 }}>
            <Text style={styles.schedSub}>{formatCustomerName(hist)}</Text>
            {histRecords === null ? (
              <Text style={styles.hint}>Loading…</Text>
            ) : histRecords.length === 0 ? (
              <Text style={styles.hint}>No cleanings recorded yet.</Text>
            ) : (
              histRecords.map((r) => (
                <View key={r.id} style={styles.histCard} testID={`maint-history-${r.id}`}>
                  <View style={styles.histTop}>
                    <Text style={styles.histDate}>{fmt(r.date)}</Text>
                    <Text style={styles.histTech}>{r.technician_name || "Unassigned"}</Text>
                  </View>
                  <Text style={styles.histReading}>
                    {r.psi != null ? `${r.psi} PSI  ` : ""}
                    {r.salt_ppm != null ? `${r.salt_ppm} ppm  ` : ""}
                    {r.filter_condition || r.cell_condition || ""}
                  </Text>
                  {r.notes ? <Text style={styles.histNotes}>{r.notes}</Text> : null}
                  {r.photos?.length ? (
                    <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: spacing.sm, marginTop: spacing.sm }}>
                      {r.photos.map((p: any) => (
                        <View key={p.id} style={styles.histThumb}>
                          <Image source={{ uri: p.data }} style={{ width: "100%", height: "100%" }} contentFit="cover" />
                          <View style={styles.histThumbLabel}><Text style={styles.histThumbLabelText}>{p.label}</Text></View>
                        </View>
                      ))}
                    </ScrollView>
                  ) : null}
                </View>
              ))
            )}
          </ScrollView>
        ) : null}
      </Sheet>
    </View>
  );
}

function TypeRow({ row, mtype, onSchedule, onHistory, onOpenJob }: any) {
  const t = row[mtype];
  const meta = STATUS_META[t.status] || STATUS_META.never;
  const up = t.upcoming_job;
  return (
    <View style={styles.typeRow} testID={`maint-type-${mtype}-${row.customer_id}`}>
      <View style={styles.typeHead}>
        <Ionicons name={mtype === "filter" ? "filter" : "flash"} size={16} color={colors.brand} />
        <Text style={styles.typeLabel}>{t.label}</Text>
        <View style={{ flex: 1 }} />
        <View style={[styles.statusChip, { backgroundColor: meta.bg }]}>
          <Text style={[styles.statusText, { color: meta.fg }]}>{meta.label}</Text>
        </View>
      </View>
      <Text style={styles.typeMeta}>
        Last: {fmt(t.last_date)}  ·  Next due: {fmt(t.next_due)}  ·  every {t.interval_days}d
      </Text>
      {up ? (
        <Pressable style={styles.scheduledPill} onPress={() => onOpenJob(up.id)} testID={`maint-upcoming-${mtype}-${row.customer_id}`}>
          <Ionicons name="calendar-outline" size={13} color="#0284C7" />
          <Text style={styles.scheduledText}>Scheduled {fmt(up.scheduled_date)}{up.technician_name ? ` · ${up.technician_name}` : ""}{up.auto_recurring ? " · auto" : ""}</Text>
          <Ionicons name="chevron-forward" size={13} color="#0284C7" />
        </Pressable>
      ) : null}
      <View style={styles.actionRow}>
        <Pressable style={styles.scheduleBtn} onPress={() => onSchedule(row, mtype)} testID={`maint-schedule-${mtype}-${row.customer_id}`}>
          <Ionicons name="add-circle-outline" size={15} color="#fff" />
          <Text style={styles.scheduleText}>Schedule</Text>
        </Pressable>
        <Pressable style={styles.historyBtn} onPress={() => onHistory(row, mtype)} testID={`maint-history-btn-${mtype}-${row.customer_id}`}>
          <Ionicons name="time-outline" size={15} color={colors.brand} />
          <Text style={styles.historyText}>History{t.last_photos ? ` (${t.last_photos}📷)` : ""}</Text>
        </Pressable>
      </View>
    </View>
  );
}

function SummaryCard({ label, count, color, active, onPress, testID }: any) {
  return (
    <Pressable style={[styles.sumCard, active && { borderColor: color, borderWidth: 2 }]} onPress={onPress} testID={testID}>
      <Text style={[styles.sumCount, { color }]}>{count}</Text>
      <Text style={styles.sumLabel}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  summaryRow: { flexDirection: "row", gap: spacing.sm, paddingHorizontal: spacing.lg, paddingTop: spacing.md },
  sumCard: { flex: 1, backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: colors.border, alignItems: "center", gap: 2 },
  sumCount: { fontFamily: font.bold, fontSize: fontSize["2xl"] },
  sumLabel: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
  card: { backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.lg, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.md },
  custName: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  custAddr: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 1 },
  typeRow: { marginTop: spacing.md, paddingTop: spacing.md, borderTopWidth: 1, borderTopColor: colors.divider },
  typeHead: { flexDirection: "row", alignItems: "center", gap: 6 },
  typeLabel: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  statusChip: { paddingHorizontal: 10, paddingVertical: 3, borderRadius: radius.pill },
  statusText: { fontFamily: font.bold, fontSize: fontSize.sm },
  typeMeta: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurfaceSecondary, marginTop: 4 },
  scheduledPill: { flexDirection: "row", alignItems: "center", gap: 5, marginTop: spacing.sm, alignSelf: "flex-start", backgroundColor: "#E0F2FE", paddingHorizontal: 10, paddingVertical: 5, borderRadius: radius.pill },
  scheduledText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: "#0284C7" },
  actionRow: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.sm },
  scheduleBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 5, height: 40, borderRadius: radius.md, backgroundColor: colors.brand },
  scheduleText: { fontFamily: font.semibold, fontSize: fontSize.base, color: "#fff" },
  historyBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 5, height: 40, borderRadius: radius.md, borderWidth: 1.5, borderColor: colors.brand, backgroundColor: colors.surface },
  historyText: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.brand },
  schedSub: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurfaceSecondary, marginBottom: spacing.md },
  fieldLabel: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurfaceSecondary, marginTop: spacing.md, marginBottom: spacing.xs },
  presetRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  preset: { paddingHorizontal: spacing.md, height: 36, borderRadius: radius.pill, alignItems: "center", justifyContent: "center", backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border },
  presetOn: { backgroundColor: colors.brand, borderColor: colors.brand },
  presetText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
  presetTextOn: { color: "#fff" },
  input: { backgroundColor: colors.surfaceSecondary, borderWidth: 1.5, borderColor: colors.border, borderRadius: radius.md, paddingHorizontal: spacing.md, height: 48, marginTop: spacing.sm, fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}) },
  hint: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 6, lineHeight: 18 },
  histCard: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.sm },
  histTop: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  histDate: { fontFamily: font.bold, fontSize: fontSize.base, color: colors.onSurface },
  histTech: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted },
  histReading: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.brand, marginTop: 3 },
  histNotes: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurfaceSecondary, marginTop: 3 },
  histThumb: { width: 84, height: 84, borderRadius: radius.sm, overflow: "hidden", backgroundColor: colors.surfaceTertiary },
  histThumbLabel: { position: "absolute", bottom: 3, left: 3, backgroundColor: "rgba(0,0,0,0.6)", paddingHorizontal: 5, borderRadius: radius.pill },
  histThumbLabelText: { color: "#fff", fontFamily: font.semibold, fontSize: 9 },
});
