/**
 * Phase 39B · mobile port of web `admin/RoutingCostTile.jsx`.
 * GET /reports/routing-cost-telemetry?window_days={7|30|90} (default 30).
 * Web `<select>` → segmented chips. Parent gate: super_admin / admin / owner.
 */
import React, { useEffect, useState } from "react";
import { View, Text, StyleSheet, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";

const WINDOWS = [7, 30, 90];
const usd = (n: any) => `$${(Number(n) || 0).toFixed(2)}`;

function Row({ label, value, strong, testID }: { label: string; value: any; strong?: boolean; testID: string }) {
  return (
    <View style={[s.row, strong && s.rowStrong]} testID={testID}>
      <Text style={s.rowLabel}>{label}</Text>
      <Text style={[s.rowValue, strong && { fontFamily: font.bold }]}>{value ?? 0}</Text>
    </View>
  );
}

export default function RoutingCostTile() {
  const [windowDays, setWindowDays] = useState(30);
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setErr(null);
    api.get(`/reports/routing-cost-telemetry?window_days=${windowDays}`)
      .then((r: any) => { if (!cancelled) setData(r); })
      .catch((e: any) => { if (!cancelled) setErr(e?.message || "Failed to load"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [windowDays]);

  const empty = !loading && !err && data && (data.total_calls || 0) === 0;

  return (
    <View style={s.tile} testID="routing-cost-tile">
      <View style={s.head}>
        <View style={s.titleRow}>
          <Ionicons name="git-branch-outline" size={16} color={colors.brand} />
          <Text style={s.title}>Routing Cost</Text>
        </View>
        <View style={s.chips} testID="routing-cost-window-select">
          {WINDOWS.map((w) => (
            <Pressable key={w} onPress={() => setWindowDays(w)} style={[s.chip, windowDays === w && s.chipOn]} testID={`routing-cost-window-${w}`} hitSlop={6}>
              <Text style={[s.chipText, windowDays === w && s.chipTextOn]}>{w}d</Text>
            </Pressable>
          ))}
        </View>
      </View>
      {loading ? (
        <Text style={s.muted} testID="routing-cost-loading">Loading…</Text>
      ) : err ? (
        <Text style={s.err} testID="routing-cost-error">{String(err)}</Text>
      ) : empty ? (
        <Text style={s.muted} testID="routing-cost-empty">No routing telemetry recorded yet.</Text>
      ) : (
        <View>
          <Row label="Traffic-aware calls" value={data?.traffic_aware_calls} testID="routing-cost-aware-row" />
          <Row label="Baseline calls" value={data?.traffic_unaware_calls} testID="routing-cost-baseline-row" />
          <Row label="Est. extra cost" value={usd(data?.est_traffic_aware_cost_usd)} strong testID="routing-cost-extra-row" />
        </View>
      )}
    </View>
  );
}

const s = StyleSheet.create({
  tile: { backgroundColor: colors.surface, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.border, padding: spacing.lg, marginBottom: spacing.lg },
  head: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: spacing.md },
  titleRow: { flexDirection: "row", alignItems: "center", gap: 6 },
  title: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  chips: { flexDirection: "row", gap: 4 },
  chip: { minHeight: 30, minWidth: 40, paddingHorizontal: 8, borderRadius: radius.pill, borderWidth: 1, borderColor: colors.border, alignItems: "center", justifyContent: "center" },
  chipOn: { backgroundColor: colors.brand, borderColor: colors.brand },
  chipText: { fontFamily: font.semibold, fontSize: 11, color: colors.onSurfaceSecondary },
  chipTextOn: { color: "#fff" },
  row: { flexDirection: "row", justifyContent: "space-between", paddingVertical: 4 },
  rowStrong: { borderTopWidth: 1, borderTopColor: colors.border, marginTop: 6, paddingTop: 8 },
  rowLabel: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  rowValue: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurface },
  muted: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  err: { fontFamily: font.regular, fontSize: 12, color: colors.error },
});
