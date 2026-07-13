import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, FlatList, RefreshControl, Pressable, ScrollView } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Loading, EmptyState } from "@/src/components/ui";
import { Header, IconButton } from "@/src/components/widgets";
import { exportCsv, toCsvRow } from "@/src/utils/exportCsv";

const fmtTime = (iso?: string | null) => {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }); } catch { return "—"; }
};
const fmtDate = (d?: string) => {
  if (!d) return "";
  try { return new Date(d + "T00:00:00").toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" }); } catch { return d; }
};
const gps = (lat?: number | null, lng?: number | null) => (lat != null && lng != null ? `${lat.toFixed(5)}, ${lng.toFixed(5)}` : "no GPS");

export default function Timesheets() {
  const [rows, setRows] = useState<any[]>([]);
  const [totalHours, setTotalHours] = useState(0);
  const [techs, setTechs] = useState<any[]>([]);
  const [techId, setTechId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async (tid: string | null) => {
    try {
      const [rep, ts] = await Promise.all([
        api.get(`/attendance/report${tid ? `?technician_id=${tid}` : ""}`),
        techs.length ? Promise.resolve(techs) : api.get("/technicians"),
      ]);
      setRows(rep.rows || []);
      setTotalHours(rep.total_hours || 0);
      if (!techs.length) setTechs(ts);
    } catch {
      setRows([]);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [techs]);

  useFocusEffect(useCallback(() => { load(techId); }, [load, techId]));

  const pickTech = (id: string | null) => { setTechId(id); setLoading(true); load(id); };

  const doExport = () => {
    const header = toCsvRow(["Date", "Technician", "Clock In", "Clock In GPS", "Clock Out", "Clock Out GPS", "Hours"]);
    const body = rows.map((r) => toCsvRow([
      r.date, r.technician_name, fmtTime(r.clock_in_at), gps(r.clock_in_lat, r.clock_in_lng),
      fmtTime(r.clock_out_at), gps(r.clock_out_lat, r.clock_out_lng), r.hours ?? 0,
    ]));
    exportCsv(`timesheets_${new Date().toISOString().slice(0, 10)}.csv`, [header, ...body].join("\n"));
  };

  if (loading) return <Loading testID="timesheets-loading" />;

  return (
    <View style={styles.root}>
      <Header title="Timesheets" back subtitle="Daily clock in/out + GPS" right={<IconButton icon="download-outline" onPress={doExport} testID="timesheets-export" />} />

      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chipRow}>
        <Chip label="All techs" active={!techId} onPress={() => pickTech(null)} testID="timesheets-tech-all" />
        {techs.map((t) => (
          <Chip key={t.id} label={t.name} active={techId === t.id} onPress={() => pickTech(t.id)} testID={`timesheets-tech-${t.id}`} />
        ))}
      </ScrollView>

      <View style={styles.summary}>
        <Text style={styles.sumVal}>{totalHours} h</Text>
        <Text style={styles.sumLabel}>{rows.length} day{rows.length === 1 ? "" : "s"} logged</Text>
      </View>

      {rows.length === 0 ? (
        <EmptyState icon="time-outline" title="No timesheets yet" subtitle="Entries appear when technicians clock in and out." testID="timesheets-empty" />
      ) : (
        <FlatList
          testID="timesheets-list"
          data={rows}
          keyExtractor={(r) => r.id}
          contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(techId); }} />}
          renderItem={({ item }) => (
            <View style={styles.card} testID={`timesheet-${item.id}`}>
              <View style={styles.cardHead}>
                <Text style={styles.cardDate}>{fmtDate(item.date)}</Text>
                <Text style={styles.cardHours}>{item.hours ?? 0} h</Text>
              </View>
              <Text style={styles.cardTech}>{item.technician_name}</Text>
              <View style={styles.punchRow}>
                <Ionicons name="log-in-outline" size={14} color="#16A34A" />
                <Text style={styles.punchText}>In {fmtTime(item.clock_in_at)} · {gps(item.clock_in_lat, item.clock_in_lng)}</Text>
              </View>
              <View style={styles.punchRow}>
                <Ionicons name="log-out-outline" size={14} color="#0EA5E9" />
                <Text style={styles.punchText}>Out {fmtTime(item.clock_out_at)} · {gps(item.clock_out_lat, item.clock_out_lng)}</Text>
              </View>
            </View>
          )}
        />
      )}
    </View>
  );
}

function Chip({ label, active, onPress, testID }: any) {
  return (
    <Pressable style={[styles.chip, active && styles.chipActive]} onPress={onPress} testID={testID}>
      <Text style={[styles.chipText, active && { color: "#fff" }]} numberOfLines={1}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  chipRow: { paddingHorizontal: spacing.lg, paddingVertical: spacing.md, gap: spacing.sm },
  chip: { paddingHorizontal: spacing.md, height: 36, borderRadius: radius.pill, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, marginRight: spacing.sm },
  chipActive: { backgroundColor: colors.brand, borderColor: colors.brand },
  chipText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
  summary: { backgroundColor: colors.surface, marginHorizontal: spacing.lg, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, padding: spacing.md, alignItems: "center" },
  sumVal: { fontFamily: font.bold, fontSize: fontSize["2xl"], color: colors.brand },
  sumLabel: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted },
  card: { backgroundColor: colors.surface, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, padding: spacing.md, marginBottom: spacing.sm, gap: 4 },
  cardHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  cardDate: { fontFamily: font.bold, fontSize: fontSize.base, color: colors.onSurface },
  cardHours: { fontFamily: font.bold, fontSize: fontSize.base, color: colors.brand },
  cardTech: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
  punchRow: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: 2 },
  punchText: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
});
