import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, TextInput, Platform, Alert } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import { Loading, EmptyState } from "@/src/components/ui";
import { exportCsv, toCsvRow } from "@/src/utils/exportCsv";

function fmtDuration(s: number) {
  if (!s) return "0m";
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${sec}s`;
  return `${sec}s`;
}

export default function AvgJobTimeReport() {
  const [q, setQ] = useState("");
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);

  const fetchReport = useCallback(async (query: string) => {
    setLoading(true);
    try {
      const params = query.trim() ? `?q=${encodeURIComponent(query.trim())}` : "";
      setData(await api.get(`/reports/avg-job-time${params}`));
    } catch (e: any) {
      Alert.alert("Couldn't load", e.message || "Try again.");
      setData({ rows: [], count: 0, overall_avg_seconds: 0, total_visits: 0 });
    } finally {
      setLoading(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { fetchReport(""); }, [fetchReport]));

  const doExport = async () => {
    const rows = data?.rows || [];
    if (rows.length === 0) { Alert.alert("Nothing to export", "No timer data yet."); return; }
    setExporting(true);
    try {
      const header = toCsvRow(["Customer", "Address", "Visits", "Avg on-site", "Total on-site", "Last visit"]);
      const lines = rows.map((r: any) => toCsvRow([r.customer_name, r.address, r.visits, fmtDuration(r.avg_seconds), fmtDuration(r.total_seconds), r.last_visit]));
      await exportCsv(`avg-job-time-${Date.now()}.csv`, [header, ...lines].join("\n"));
    } catch (e: any) {
      Alert.alert("Export failed", e.message || "Could not export.");
    } finally {
      setExporting(false);
    }
  };

  const rows = data?.rows || [];

  return (
    <View style={styles.root}>
      <Header title="Avg Job Time" back subtitle="Average on-site time per customer" />

      <View style={styles.searchWrap}>
        <Ionicons name="search" size={16} color={colors.muted} />
        <TextInput
          style={styles.searchInput}
          value={q}
          onChangeText={setQ}
          onSubmitEditing={() => fetchReport(q)}
          placeholder="Search customer by name or address"
          placeholderTextColor={colors.muted}
          returnKeyType="search"
          testID="avg-search"
        />
        {q ? <Pressable onPress={() => { setQ(""); fetchReport(""); }} hitSlop={8}><Ionicons name="close-circle" size={18} color={colors.muted} /></Pressable> : null}
      </View>

      <View style={styles.summaryRow}>
        <View style={styles.summaryCard}>
          <Text style={styles.summaryValue}>{fmtDuration(data?.overall_avg_seconds || 0)}</Text>
          <Text style={styles.summaryLabel}>Overall avg</Text>
        </View>
        <View style={styles.summaryCard}>
          <Text style={styles.summaryValue}>{data?.total_visits ?? 0}</Text>
          <Text style={styles.summaryLabel}>Visits timed</Text>
        </View>
        <Pressable style={[styles.exportBtn, exporting && { opacity: 0.6 }]} onPress={doExport} disabled={exporting} testID="avg-export">
          <Ionicons name="share-outline" size={18} color="#fff" />
          <Text style={styles.exportText}>{exporting ? "…" : "Export"}</Text>
        </Pressable>
      </View>

      {loading ? (
        <Loading testID="avg-loading" />
      ) : (
        <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingTop: spacing.sm, paddingBottom: spacing["3xl"] }}>
          {rows.length === 0 ? (
            <EmptyState icon="stats-chart-outline" title="No timer data yet" subtitle="Averages appear once technicians complete jobs with the automated timer." testID="avg-empty" />
          ) : (
            rows.map((r: any, idx: number) => (
              <View key={r.customer_id} style={styles.card} testID={`avg-row-${r.customer_id}`}>
                <View style={styles.rankBadge}><Text style={styles.rankText}>{idx + 1}</Text></View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.cardTitle} numberOfLines={1}>{r.customer_name || "Customer"}</Text>
                  <Text style={styles.cardMeta} numberOfLines={1}>{r.visits} visit{r.visits === 1 ? "" : "s"} · {fmtDuration(r.total_seconds)} total{r.last_visit ? ` · last ${r.last_visit}` : ""}</Text>
                </View>
                <View style={styles.avgWrap}>
                  <Text style={styles.avgValue}>{fmtDuration(r.avg_seconds)}</Text>
                  <Text style={styles.avgLabel}>avg</Text>
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
  summaryRow: { flexDirection: "row", alignItems: "stretch", gap: spacing.sm, paddingHorizontal: spacing.lg, marginTop: spacing.md, marginBottom: spacing.xs },
  summaryCard: { flex: 1, backgroundColor: colors.surface, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, padding: spacing.md, alignItems: "center" },
  summaryValue: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  summaryLabel: { fontFamily: font.regular, fontSize: 11, color: colors.muted, marginTop: 2 },
  exportBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, backgroundColor: colors.brand, borderRadius: radius.md, paddingHorizontal: spacing.md },
  exportText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: "#fff" },
  card: { flexDirection: "row", alignItems: "center", gap: spacing.md, backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.sm },
  rankBadge: { width: 28, height: 28, borderRadius: 14, backgroundColor: colors.surfaceSecondary, alignItems: "center", justifyContent: "center" },
  rankText: { fontFamily: font.bold, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
  cardTitle: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  cardMeta: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 1 },
  avgWrap: { alignItems: "flex-end" },
  avgValue: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.brand },
  avgLabel: { fontFamily: font.regular, fontSize: 10, color: colors.muted },
});
