import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, RefreshControl, Pressable, Alert, Platform } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize, money } from "@/src/theme";
import { Loading, EmptyState } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";
import { exportCsv, toCsvRow } from "@/src/utils/exportCsv";
import { exportReportPdf } from "@/src/utils/exportReportPdf";
import AppTextInput from "@/src/components/ui/AppTextInput";

const PALETTE = ["#0284C7", "#16A34A", "#7C3AED", "#D97706", "#DB2777", "#0891B2", "#65A30D", "#DC2626"];

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
function presetRange(p: string): { from: string | null; to: string | null } {
  const now = new Date();
  if (p === "week") {
    const mon = new Date(now); mon.setDate(now.getDate() - ((now.getDay() + 6) % 7));
    const sun = new Date(mon); sun.setDate(mon.getDate() + 6);
    return { from: iso(mon), to: iso(sun) };
  }
  if (p === "month") return { from: iso(new Date(now.getFullYear(), now.getMonth(), 1)), to: iso(new Date(now.getFullYear(), now.getMonth() + 1, 0)) };
  if (p === "lastmonth") return { from: iso(new Date(now.getFullYear(), now.getMonth() - 1, 1)), to: iso(new Date(now.getFullYear(), now.getMonth(), 0)) };
  return { from: null, to: null }; // all
}
const PRESETS: { key: string; label: string }[] = [
  { key: "all", label: "All time" },
  { key: "month", label: "This month" },
  { key: "lastmonth", label: "Last month" },
  { key: "week", label: "This week" },
  { key: "custom", label: "Custom" },
];

export default function BusinessReports() {
  const [d, setD] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [preset, setPreset] = useState("all");
  const [customFrom, setCustomFrom] = useState("");
  const [customTo, setCustomTo] = useState("");

  const rangeOf = useCallback(() => {
    if (preset === "custom") return { from: customFrom || null, to: customTo || null };
    return presetRange(preset);
  }, [preset, customFrom, customTo]);

  const load = useCallback(async () => {
    try {
      const { from, to } = rangeOf();
      const qs = from && to ? `?date_from=${from}&date_to=${to}` : "";
      setD(await api.get(`/reports/business-summary${qs}`));
    }
    catch { setD(null); }
    finally { setLoading(false); setRefreshing(false); }
  }, [rangeOf]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const doPdf = async () => {
    if (!d) return;
    setBusy(true);
    try { await exportReportPdf(d); } catch (e: any) { Alert.alert("Export failed", e.message || "Could not create PDF."); }
    finally { setBusy(false); }
  };

  const doCsv = () => {
    if (!d) return;
    const lines: string[] = [];
    const k = d.kpis || {};
    lines.push("BUSINESS REPORT," + new Date(d.generated_at).toLocaleString());
    lines.push("");
    lines.push("KEY METRICS,Value");
    lines.push(toCsvRow(["Revenue collected", k.revenue]));
    lines.push(toCsvRow(["Outstanding", k.outstanding]));
    lines.push(toCsvRow(["Avg ticket", k.avg_ticket]));
    lines.push(toCsvRow(["Completion rate %", k.completion_rate]));
    lines.push(toCsvRow(["Total jobs", k.total_jobs]));
    lines.push(toCsvRow(["Customers", k.total_customers]));
    lines.push(toCsvRow(["Open leads", k.open_leads]));
    lines.push(toCsvRow(["Labor hours (week)", k.labor_hours_week]));
    const section = (title: string, header: string[], rows: any[][]) => {
      lines.push(""); lines.push(title); lines.push(toCsvRow(header));
      rows.forEach((r) => lines.push(toCsvRow(r)));
    };
    section("REVENUE TREND", ["Month", "Revenue"], (d.revenue_series || []).map((r: any) => [r.label, r.value]));
    section("INCOME BY CATEGORY", ["Category", "Collected"], (d.income_by_category || []).map((r: any) => [r.category, r.amount]));
    section("REVENUE BY SERVICE", ["Service", "Revenue"], (d.revenue_by_service || []).map((r: any) => [r.label, r.value]));
    section("TOP CUSTOMERS", ["Customer", "Revenue"], (d.top_customers || []).map((r: any) => [r.label, r.value]));
    section("POOL SERVICE (this week)", ["Technician", "Completed", "Skipped"], (d.pool_service?.rows || []).map((r: any) => [r.technician_name, r.completed, r.skipped]));
    section("LABOR HOURS (this week)", ["Technician", "Hours"], (d.labor_hours || []).map((r: any) => [r.label, r.value]));
    exportCsv(`business_report_${new Date().toISOString().slice(0, 10)}.csv`, lines.join("\n"));
  };

  if (loading) return <View style={styles.root}><Header title="Business Reports" back subtitle="All metrics in one place" /><Loading testID="biz-loading" /></View>;
  if (!d) return <View style={styles.root}><Header title="Business Reports" back /><EmptyState icon="bar-chart-outline" title="No data" subtitle="Pull down to retry." testID="biz-empty" /></View>;

  const k = d.kpis || {};
  const income = (d.income_by_category || []).map((r: any) => ({ label: r.category, value: r.amount }));

  return (
    <View style={styles.root}>
      <Header title="Business Reports" back subtitle="All metrics in one place" />

      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.filterRow}>
        {PRESETS.map((p) => (
          <Pressable key={p.key} style={[styles.fChip, preset === p.key && styles.fChipActive]} onPress={() => { setLoading(true); setPreset(p.key); }} testID={`biz-preset-${p.key}`}>
            <Text style={[styles.fChipText, preset === p.key && { color: "#fff" }]}>{p.label}</Text>
          </Pressable>
        ))}
      </ScrollView>
      {preset === "custom" ? (
        <View style={styles.customRow}>
          <AppTextInput style={styles.customInput} value={customFrom} onChangeText={setCustomFrom} placeholder="From YYYY-MM-DD" placeholderTextColor={colors.muted} testID="biz-custom-from" />
          <AppTextInput style={styles.customInput} value={customTo} onChangeText={setCustomTo} placeholder="To YYYY-MM-DD" placeholderTextColor={colors.muted} testID="biz-custom-to" />
          <Pressable style={styles.applyBtn} onPress={() => { setLoading(true); load(); }} testID="biz-custom-apply"><Text style={styles.applyText}>Apply</Text></Pressable>
        </View>
      ) : null}

      <View style={styles.exportRow}>
        <Pressable style={[styles.exportBtn, styles.pdfBtn, busy && { opacity: 0.6 }]} onPress={doPdf} disabled={busy} testID="biz-export-pdf">
          <Ionicons name="document-text-outline" size={16} color="#fff" />
          <Text style={styles.exportText}>{busy ? "…" : "Export PDF"}</Text>
        </Pressable>
        <Pressable style={[styles.exportBtn, styles.csvBtn]} onPress={doCsv} testID="biz-export-csv">
          <Ionicons name="grid-outline" size={16} color="#fff" />
          <Text style={styles.exportText}>Export CSV</Text>
        </Pressable>
      </View>

      <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingTop: spacing.sm, paddingBottom: spacing["3xl"] }} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}>
        <View style={styles.grid}>
          <Kpi label="Revenue" value={money(k.revenue)} tint="#0284C7" />
          <Kpi label="Outstanding" value={money(k.outstanding)} tint="#D97706" />
          <Kpi label="Avg Ticket" value={money(k.avg_ticket)} tint="#7C3AED" />
          <Kpi label="Completion" value={`${k.completion_rate}%`} tint="#16A34A" />
          <Kpi label="Jobs" value={k.total_jobs} tint="#0891B2" />
          <Kpi label="Customers" value={k.total_customers} tint="#0284C7" />
          <Kpi label="Open Leads" value={k.open_leads} tint="#DB2777" />
          <Kpi label="Labor hrs/wk" value={k.labor_hours_week} tint="#65A30D" />
        </View>

        <BarBlock title="Revenue Trend (6 mo)" rows={d.revenue_series} asMoney />
        <BarBlock title="Income by Category" rows={income} asMoney />
        <BarBlock title="Revenue by Service" rows={d.revenue_by_service} asMoney />
        <BarBlock title="Top Customers" rows={d.top_customers} asMoney />
        <BarBlock title="Labor Hours (this week)" rows={d.labor_hours} asMoney={false} suffix=" h" />

        <Text style={styles.blockTitle}>Pool Service · this week</Text>
        <View style={styles.card}>
          {(d.pool_service?.rows || []).length === 0 ? <Text style={styles.muted}>No visits.</Text> :
            d.pool_service.rows.map((r: any) => (
              <View key={r.technician_id} style={styles.psRow}>
                <Text style={styles.psName}>{r.technician_name}</Text>
                <Text style={styles.psVal}>{r.completed} done{r.skipped ? ` · ${r.skipped} skip` : ""}</Text>
              </View>
            ))}
        </View>
      </ScrollView>
    </View>
  );
}

function Kpi({ label, value, tint }: { label: string; value: any; tint: string }) {
  return (
    <View style={styles.kpi}>
      <Text style={[styles.kpiVal, { color: tint }]} numberOfLines={1}>{value}</Text>
      <Text style={styles.kpiLabel}>{label}</Text>
    </View>
  );
}

function BarBlock({ title, rows, asMoney, suffix = "" }: { title: string; rows: any[]; asMoney: boolean; suffix?: string }) {
  if (!rows || rows.length === 0) return null;
  const max = Math.max(...rows.map((r) => r.value), 1);
  return (
    <>
      <Text style={styles.blockTitle}>{title}</Text>
      <View style={styles.card}>
        {rows.map((r, i) => (
          <View key={`${r.label}-${i}`} style={styles.barRow}>
            <Text style={styles.barLabel} numberOfLines={1}>{r.label}</Text>
            <View style={styles.track}><View style={[styles.fill, { width: `${Math.max(3, (r.value / max) * 100)}%`, backgroundColor: PALETTE[i % PALETTE.length] }]} /></View>
            <Text style={styles.barVal}>{asMoney ? money(r.value) : `${r.value}${suffix}`}</Text>
          </View>
        ))}
      </View>
    </>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  filterRow: { paddingHorizontal: spacing.lg, paddingTop: spacing.md, gap: spacing.sm },
  fChip: { paddingHorizontal: spacing.md, height: 34, borderRadius: radius.pill, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, marginRight: spacing.sm },
  fChipActive: { backgroundColor: colors.brand, borderColor: colors.brand },
  fChipText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
  customRow: { flexDirection: "row", gap: spacing.sm, paddingHorizontal: spacing.lg, paddingTop: spacing.sm },
  customInput: { flex: 1, backgroundColor: colors.surface, borderWidth: 1.5, borderColor: colors.border, borderRadius: radius.md, paddingHorizontal: spacing.sm, height: 42, fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurface, ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}) },
  applyBtn: { paddingHorizontal: spacing.md, height: 42, borderRadius: radius.md, backgroundColor: colors.brand, alignItems: "center", justifyContent: "center" },
  applyText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: "#fff" },
  exportRow: { flexDirection: "row", gap: spacing.sm, paddingHorizontal: spacing.lg, paddingTop: spacing.md },
  exportBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, height: 44, borderRadius: radius.md },
  pdfBtn: { backgroundColor: "#DC2626" },
  csvBtn: { backgroundColor: "#16A34A" },
  exportText: { fontFamily: font.semibold, fontSize: fontSize.base, color: "#fff" },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  kpi: { flexBasis: "47%", flexGrow: 1, backgroundColor: colors.surface, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, padding: spacing.md },
  kpiVal: { fontFamily: font.bold, fontSize: fontSize.xl },
  kpiLabel: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
  blockTitle: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface, marginTop: spacing.lg, marginBottom: spacing.sm },
  card: { backgroundColor: colors.surface, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, padding: spacing.md },
  barRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm, marginBottom: spacing.sm },
  barLabel: { width: 88, fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
  track: { flex: 1, height: 10, borderRadius: 5, backgroundColor: colors.surfaceSecondary, overflow: "hidden" },
  fill: { height: 10, borderRadius: 5 },
  barVal: { width: 76, textAlign: "right", fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface },
  psRow: { flexDirection: "row", justifyContent: "space-between", paddingVertical: spacing.xs },
  psName: { fontFamily: font.medium, fontSize: fontSize.base, color: colors.onSurface },
  psVal: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.brand },
  muted: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted },
});
