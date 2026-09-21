import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, Platform, Alert } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import { Loading, EmptyState } from "@/src/components/ui";
import { exportCsv, toCsvRow } from "@/src/utils/exportCsv";
import { formatCustomerName } from "@/src/utils/formatCustomerName";
import { ClickableAddress } from "@/src/components/interactive";
import AppTextInput from "@/src/components/ui/AppTextInput";

function fmtDuration(s: number) {
  if (!s) return "0m";
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${sec}s`;
  return `${sec}s`;
}

export default function JobTimersReport() {
  const [techs, setTechs] = useState<any[]>([]);
  const [techId, setTechId] = useState<string>("");
  const [q, setQ] = useState("");
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);

  const fetchReport = useCallback(async (tid: string, query: string) => {
    setLoading(true);
    try {
      const params = ["_=1"];
      if (tid) params.push(`technician_id=${tid}`);
      if (query.trim()) params.push(`q=${encodeURIComponent(query.trim())}`);
      const res = await api.get(`/reports/job-timers?${params.join("&")}`);
      setData(res);
    } catch (e: any) {
      Alert.alert("Couldn't load", e.message || "Try again.");
      setData({ rows: [], count: 0, total_seconds: 0 });
    } finally {
      setLoading(false);
    }
  }, []);

  useFocusEffect(useCallback(() => {
    (async () => {
      try { setTechs(await api.get("/technicians")); } catch {}
      fetchReport(techId, q);
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []));

  const selectTech = (id: string) => { setTechId(id); fetchReport(id, q); };
  const runSearch = () => fetchReport(techId, q);

  const doExport = async () => {
    const rows = data?.rows || [];
    if (rows.length === 0) { Alert.alert("Nothing to export", "No timer records match your filters."); return; }
    setExporting(true);
    try {
      const header = toCsvRow(["Date", "Customer", "Technician", "Service", "Address", "Started", "Stopped", "Duration", "Status"]);
      const lines = rows.map((r: any) => toCsvRow([
        r.date, r.customer_name, r.technician_name, r.service_type, r.address,
        r.started_at || "", r.stopped_at || (r.running ? "RUNNING" : ""), fmtDuration(r.duration_seconds), r.status,
      ]));
      const csv = [header, ...lines].join("\n");
      await exportCsv(`job-timers-${Date.now()}.csv`, csv);
    } catch (e: any) {
      Alert.alert("Export failed", e.message || "Could not export the report.");
    } finally {
      setExporting(false);
    }
  };

  const rows = data?.rows || [];

  return (
    <View style={styles.root}>
      <Header title="Job Timers" back subtitle="Automated on-site time" />

      <View style={styles.searchWrap}>
        <Ionicons name="search" size={16} color={colors.muted} />
        <AppTextInput
          style={styles.searchInput}
          value={q}
          onChangeText={setQ}
          onSubmitEditing={runSearch}
          placeholder="Search by customer, tech or address"
          placeholderTextColor={colors.muted}
          returnKeyType="search"
          testID="timers-search"
        />
        {q ? <Pressable onPress={() => { setQ(""); fetchReport(techId, ""); }} hitSlop={8}><Ionicons name="close-circle" size={18} color={colors.muted} /></Pressable> : null}
      </View>

      <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.techScroll} contentContainerStyle={styles.techRow}>
        <Pressable style={[styles.techChip, !techId && styles.techChipActive]} onPress={() => selectTech("")} testID="timers-tech-all">
          <Text style={[styles.techChipText, !techId && { color: "#fff" }]}>All techs</Text>
        </Pressable>
        {techs.map((t) => (
          <Pressable key={t.id} style={[styles.techChip, techId === t.id && styles.techChipActive]} onPress={() => selectTech(t.id)} testID={`timers-tech-${t.id}`}>
            <Text style={[styles.techChipText, techId === t.id && { color: "#fff" }]}>{t.name}</Text>
          </Pressable>
        ))}
      </ScrollView>

      <View style={styles.summaryRow}>
        <View style={styles.summaryCard}>
          <Text style={styles.summaryValue}>{data?.count ?? 0}</Text>
          <Text style={styles.summaryLabel}>Visits timed</Text>
        </View>
        <View style={styles.summaryCard}>
          <Text style={styles.summaryValue}>{fmtDuration(data?.total_seconds || 0)}</Text>
          <Text style={styles.summaryLabel}>Total on-site</Text>
        </View>
        <Pressable style={[styles.exportBtn, exporting && { opacity: 0.6 }]} onPress={doExport} disabled={exporting} testID="timers-export">
          <Ionicons name="share-outline" size={18} color="#fff" />
          <Text style={styles.exportText}>{exporting ? "…" : "Export"}</Text>
        </Pressable>
      </View>

      {loading ? (
        <Loading testID="timers-loading" />
      ) : (
        <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingTop: spacing.sm, paddingBottom: spacing["3xl"] }}>
          {rows.length === 0 ? (
            <EmptyState icon="timer-outline" title="No timer records" subtitle="Timers auto-start when a tech arrives on-site and stop when the job is completed." testID="timers-empty" />
          ) : (
            rows.map((r: any) => (
              <View key={r.job_id} style={styles.card} testID={`timers-row-${r.job_id}`}>
                <View style={[styles.durBadge, r.running && styles.durBadgeRunning]}>
                  <Text style={styles.durText}>{fmtDuration(r.duration_seconds)}</Text>
                  {r.running ? <Text style={styles.runningText}>running</Text> : null}
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.cardTitle} numberOfLines={1}>{formatCustomerName(r)}</Text>
                  <Text style={styles.cardMeta} numberOfLines={1}>{r.date} · {r.service_type}{r.technician_name ? ` · ${r.technician_name}` : ""}</Text>
                  {r.address ? <ClickableAddress address={r.address} style={styles.cardAddr} testID={`timers-addr-${r.job_id}`} /> : null}
                </View>
              </View>
            ))
          )}
        </ScrollView>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  searchWrap: { flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: colors.surface, borderWidth: 1.5, borderColor: colors.border, borderRadius: radius.md, paddingHorizontal: spacing.md, height: 46, marginHorizontal: spacing.lg, marginTop: spacing.md },
  searchInput: { flex: 1, fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}) },
  techRow: { paddingHorizontal: spacing.lg, paddingVertical: spacing.md, gap: spacing.sm },
  techScroll: { flexGrow: 0, maxHeight: 62 },
  techChip: { paddingHorizontal: spacing.md, height: 34, borderRadius: radius.pill, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, marginRight: spacing.sm },
  techChipActive: { backgroundColor: colors.brand, borderColor: colors.brand },
  techChipText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
  summaryRow: { flexDirection: "row", alignItems: "stretch", gap: spacing.sm, paddingHorizontal: spacing.lg, marginBottom: spacing.xs },
  summaryCard: { flex: 1, backgroundColor: colors.surface, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, padding: spacing.md, alignItems: "center" },
  summaryValue: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  summaryLabel: { fontFamily: font.regular, fontSize: 11, color: colors.muted, marginTop: 2 },
  exportBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, backgroundColor: colors.brand, borderRadius: radius.md, paddingHorizontal: spacing.md },
  exportText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: "#fff" },
  card: { flexDirection: "row", alignItems: "center", gap: spacing.md, backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.sm },
  durBadge: { minWidth: 64, paddingHorizontal: spacing.sm, paddingVertical: spacing.xs, borderRadius: radius.md, backgroundColor: colors.surfaceSecondary, alignItems: "center" },
  durBadgeRunning: { backgroundColor: "#DCFCE7" },
  durText: { fontFamily: font.bold, fontSize: fontSize.base, color: colors.onSurface },
  runningText: { fontFamily: font.semibold, fontSize: 10, color: "#16A34A", marginTop: 1 },
  cardTitle: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  cardMeta: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 1 },
  cardAddr: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurfaceSecondary, marginTop: 1 },
});
