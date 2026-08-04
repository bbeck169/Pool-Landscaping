// Phase 36 · Feb-2026 — Mobile CFO Anomalies (P1.2 CFO Deep-Dives).
//
// Web parity: `frontend/src/pages/cfo/CFODashboard.jsx` — anomalies slice.
// Backend: GET /api/cfo/anomalies?window_days=&z=.
// Admin / super-admin only.
import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, RefreshControl, Pressable,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize, money } from "@/src/theme";
import { Loading, EmptyState } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";
import { RoleGate } from "@/src/components/RoleGate";

const WINDOWS = [30, 60, 90, 180];
const Z_LEVELS = [1.5, 2.0, 2.5, 3.0];

export default function CfoAnomalies() {
  const [window, setWindow] = useState(90);
  const [z, setZ] = useState(2.0);
  const [rows, setRows] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [err, setErr] = useState<string>("");

  const load = useCallback(async () => {
    setLoading(true); setErr("");
    try {
      const r: any = await api.get(`/cfo/anomalies?window_days=${window}&z=${z}`);
      setRows(Array.isArray(r) ? r : r?.items || []);
    } catch (e: any) {
      setErr(e?.message || "Failed to load anomalies.");
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, [window, z]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  return (
    <RoleGate level="strict_admin">
      <View style={styles.container} testID="cfo-anomalies-page">
        <Header title="Anomalies" />
        <ScrollView
          contentContainerStyle={styles.body}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={async () => {
              setRefreshing(true); await load(); setRefreshing(false);
            }} />
          }
        >
          <View style={styles.filterBlock}>
            <Text style={styles.filterLabel}>Window (days)</Text>
            <View style={styles.pills} testID="cfo-anomalies-windows">
              {WINDOWS.map((w) => (
                <Pressable
                  key={w}
                  onPress={() => setWindow(w)}
                  style={[styles.pill, window === w && styles.pillOn]}
                  testID={`cfo-anomalies-window-${w}`}
                >
                  <Text style={[styles.pillText, window === w && styles.pillTextOn]}>{w}</Text>
                </Pressable>
              ))}
            </View>
          </View>
          <View style={styles.filterBlock}>
            <Text style={styles.filterLabel}>Sensitivity (z-score)</Text>
            <View style={styles.pills} testID="cfo-anomalies-z-levels">
              {Z_LEVELS.map((zz) => (
                <Pressable
                  key={zz}
                  onPress={() => setZ(zz)}
                  style={[styles.pill, z === zz && styles.pillOn]}
                  testID={`cfo-anomalies-z-${String(zz).replace(".", "-")}`}
                >
                  <Text style={[styles.pillText, z === zz && styles.pillTextOn]}>{zz}σ</Text>
                </Pressable>
              ))}
            </View>
          </View>

          {loading ? (
            <Loading />
          ) : err ? (
            <EmptyState
              icon="warning-outline"
              title="Couldn't load anomalies"
              subtitle={err}
              testID="cfo-anomalies-error"
            />
          ) : rows.length === 0 ? (
            <EmptyState
              icon="pulse-outline"
              title="No anomalies detected"
              subtitle={`Within ${window}d at ${z}σ — increase sensitivity to see more.`}
              testID="cfo-anomalies-empty"
            />
          ) : (
            rows.map((r: any, idx: number) => (
              <View
                key={r.id || `${r.category}-${idx}`}
                style={styles.row}
                testID={`cfo-anomaly-row-${idx}`}
              >
                <View style={styles.rowHead}>
                  <Text style={styles.category}>{r.category || r.label || "—"}</Text>
                  <Text style={[styles.zTag, r.z_score > 0 ? { color: colors.error } : { color: colors.brand }]}>
                    {typeof r.z_score === "number" ? `${r.z_score.toFixed(2)}σ` : "?"}
                  </Text>
                </View>
                <View style={styles.metaRow}>
                  <Text style={styles.meta}>
                    {r.period || r.date || "—"}
                  </Text>
                  <Text style={styles.amount}>
                    {money(((r.amount_cents ?? r.value_cents) || 0) / 100)}
                  </Text>
                </View>
                {r.note ? (
                  <Text style={styles.note} numberOfLines={2}>{r.note}</Text>
                ) : null}
              </View>
            ))
          )}
        </ScrollView>
      </View>
    </RoleGate>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.surface },
  body: { padding: spacing.lg, gap: spacing.sm, paddingBottom: spacing["3xl"] },
  filterBlock: { gap: 4 },
  filterLabel: { fontFamily: font.medium, fontSize: 10, textTransform: "uppercase", color: colors.muted, letterSpacing: 0.5 },
  pills: { flexDirection: "row", gap: spacing.xs, flexWrap: "wrap" },
  pill: {
    paddingHorizontal: 12, paddingVertical: 6, borderRadius: radius.pill,
    borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface,
  },
  pillOn: { backgroundColor: colors.brandTertiary, borderColor: colors.brand },
  pillText: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted },
  pillTextOn: { color: colors.brand },
  row: {
    padding: spacing.md, borderRadius: radius.md, borderWidth: 1,
    borderColor: colors.border, backgroundColor: colors.surface, gap: spacing.xs,
  },
  rowHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  category: { fontFamily: font.semibold, fontSize: fontSize.md, color: colors.onSurface },
  zTag: { fontFamily: font.bold, fontSize: fontSize.sm },
  metaRow: { flexDirection: "row", justifyContent: "space-between" },
  meta: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  amount: { fontFamily: font.bold, fontSize: fontSize.sm, color: colors.onSurface },
  note: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
});
