// Phase 36 · Feb-2026 — Mobile CFO Forecast (P1.2 CFO Deep-Dives).
//
// Web parity: `frontend/src/pages/cfo/CFODashboard.jsx` — forecast slice.
// Backend: GET /api/cfo/forecast?horizon={days}. This is the CFO
// cash-flow forecast — distinct from `/api/reports/forecast`
// (revenue forecast, shipped in Phase 40 at `mobile/app/reports/forecast.tsx`).
// Admin / super-admin only.
import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, RefreshControl, Pressable,
} from "react-native";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize, money } from "@/src/theme";
import { Card, Loading, EmptyState } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";
import { RoleGate } from "@/src/components/RoleGate";

const HORIZONS: { days: number; label: string }[] = [
  { days: 30,  label: "30d"  },
  { days: 60,  label: "60d"  },
  { days: 90,  label: "90d"  },
  { days: 180, label: "180d" },
];

export default function CfoForecast() {
  const [horizon, setHorizon] = useState(90);
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [err, setErr] = useState<string>("");

  const load = useCallback(async () => {
    setLoading(true); setErr("");
    try {
      const r: any = await api.get(`/cfo/forecast?horizon=${horizon}`);
      setData(r);
    } catch (e: any) {
      setErr(e?.message || "Failed to load forecast.");
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [horizon]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const buckets = Array.isArray(data?.projected_by_month)
    ? data.projected_by_month
    : Array.isArray(data?.buckets) ? data.buckets : [];

  return (
    <RoleGate level="strict_admin">
      <View style={styles.container} testID="cfo-forecast-page">
        <Header title="Cash Forecast" />
        <ScrollView
          contentContainerStyle={styles.body}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={async () => {
              setRefreshing(true); await load(); setRefreshing(false);
            }} />
          }
        >
          {/* Horizon selector */}
          <View style={styles.pills} testID="cfo-forecast-horizons">
            {HORIZONS.map((h) => (
              <Pressable
                key={h.days}
                onPress={() => setHorizon(h.days)}
                style={[styles.pill, horizon === h.days && styles.pillOn]}
                testID={`cfo-forecast-horizon-${h.days}`}
              >
                <Text style={[styles.pillText, horizon === h.days && styles.pillTextOn]}>
                  {h.label}
                </Text>
              </Pressable>
            ))}
          </View>

          {loading ? (
            <Loading />
          ) : err ? (
            <EmptyState
              icon="warning-outline"
              title="Couldn't load forecast"
              subtitle={err}
              testID="cfo-forecast-error"
            />
          ) : (
            <>
              <Card style={styles.summary}>
                <View style={styles.summaryRow}>
                  <View style={styles.summaryCell}>
                    <Text style={styles.summaryLabel}>Projected in</Text>
                    <Text style={styles.summaryValue}>
                      {money((data?.projected_inflow_cents || 0) / 100)}
                    </Text>
                  </View>
                  <View style={styles.summaryCell}>
                    <Text style={styles.summaryLabel}>Projected out</Text>
                    <Text style={styles.summaryValue}>
                      {money((data?.projected_outflow_cents || 0) / 100)}
                    </Text>
                  </View>
                  <View style={styles.summaryCell}>
                    <Text style={styles.summaryLabel}>Net</Text>
                    <Text style={[
                      styles.summaryValue,
                      (data?.projected_net_cents || 0) < 0 && { color: colors.error },
                    ]}>
                      {money((data?.projected_net_cents || 0) / 100)}
                    </Text>
                  </View>
                </View>
              </Card>
              {buckets.length === 0 ? (
                <EmptyState
                  icon="calendar-outline"
                  title="No projections yet"
                  subtitle="Forecast needs more historical data — try a longer horizon."
                  testID="cfo-forecast-empty"
                />
              ) : (
                buckets.map((b: any, idx: number) => (
                  <View
                    key={b.period || b.label || idx}
                    style={styles.bucketRow}
                    testID={`cfo-forecast-bucket-${idx}`}
                  >
                    <Text style={styles.bucketLabel}>
                      {b.period || b.label || `Bucket ${idx + 1}`}
                    </Text>
                    <Text style={styles.bucketValue}>
                      {money(((b.net_cents ?? b.total_cents) || 0) / 100)}
                    </Text>
                  </View>
                ))
              )}
            </>
          )}
        </ScrollView>
      </View>
    </RoleGate>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.surface },
  body: { padding: spacing.lg, gap: spacing.sm, paddingBottom: spacing["3xl"] },
  pills: { flexDirection: "row", gap: spacing.xs, marginBottom: spacing.sm },
  pill: {
    paddingHorizontal: 12, paddingVertical: 6, borderRadius: radius.pill,
    borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface,
  },
  pillOn: { backgroundColor: colors.brandTertiary, borderColor: colors.brand },
  pillText: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted },
  pillTextOn: { color: colors.brand },
  summary: { gap: spacing.sm },
  summaryRow: { flexDirection: "row", justifyContent: "space-between" },
  summaryCell: { flex: 1 },
  summaryLabel: { fontFamily: font.medium, fontSize: 10, textTransform: "uppercase", color: colors.muted, letterSpacing: 0.5 },
  summaryValue: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface, marginTop: 2 },
  bucketRow: {
    flexDirection: "row", justifyContent: "space-between", alignItems: "center",
    padding: spacing.md, borderRadius: radius.md, borderWidth: 1,
    borderColor: colors.border, backgroundColor: colors.surface,
  },
  bucketLabel: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurface },
  bucketValue: { fontFamily: font.bold, fontSize: fontSize.md, color: colors.onSurface },
});
