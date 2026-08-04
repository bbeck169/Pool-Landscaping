// Phase 36 · Feb-2026 — Mobile CFO Payroll (P1.2 CFO Deep-Dives).
//
// Web parity: `frontend/src/pages/admin/CFOReports.jsx` — payroll slice.
// Backend: GET /api/cfo/payroll?period={mtd|qtd|ytd}.
// This is the READ-ONLY payroll summary (labor totals by category);
// distinct from `mobile/app/(app)/payroll/batch.tsx` which is the
// batch-run action page.
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

type Period = "mtd" | "qtd" | "ytd";

const PERIODS: Array<{ key: Period; label: string }> = [
  { key: "mtd", label: "MTD" },
  { key: "qtd", label: "QTD" },
  { key: "ytd", label: "YTD" },
];

export default function CfoPayroll() {
  const [period, setPeriod] = useState<Period>("mtd");
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [err, setErr] = useState<string>("");

  const load = useCallback(async () => {
    setLoading(true); setErr("");
    try {
      const r: any = await api.get(`/cfo/payroll?period=${period}`);
      setData(r);
    } catch (e: any) {
      setErr(e?.message || "Failed to load payroll.");
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [period]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const breakdown = Array.isArray(data?.by_category)
    ? data.by_category
    : Array.isArray(data?.rows) ? data.rows : [];

  return (
    <RoleGate level="strict_admin">
      <View style={styles.container} testID="cfo-payroll-page">
        <Header title="Payroll (CFO)" />
        <ScrollView
          contentContainerStyle={styles.body}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={async () => {
              setRefreshing(true); await load(); setRefreshing(false);
            }} />
          }
        >
          <View style={styles.pills} testID="cfo-payroll-periods">
            {PERIODS.map((p) => (
              <Pressable
                key={p.key}
                onPress={() => setPeriod(p.key)}
                style={[styles.pill, period === p.key && styles.pillOn]}
                testID={`cfo-payroll-period-${p.key}`}
              >
                <Text style={[styles.pillText, period === p.key && styles.pillTextOn]}>
                  {p.label}
                </Text>
              </Pressable>
            ))}
          </View>

          {loading ? (
            <Loading />
          ) : err ? (
            <EmptyState
              icon="warning-outline"
              title="Couldn't load payroll"
              subtitle={err}
              testID="cfo-payroll-error"
            />
          ) : (
            <>
              <Card style={styles.summary}>
                <View style={styles.summaryRow}>
                  <View style={styles.summaryCell}>
                    <Text style={styles.summaryLabel}>Total wages</Text>
                    <Text style={styles.summaryValue}>
                      {money((data?.total_wages_cents || 0) / 100)}
                    </Text>
                  </View>
                  <View style={styles.summaryCell}>
                    <Text style={styles.summaryLabel}>Total hours</Text>
                    <Text style={styles.summaryValue}>
                      {typeof data?.total_hours === "number"
                        ? data.total_hours.toFixed(1)
                        : "—"}
                    </Text>
                  </View>
                  <View style={styles.summaryCell}>
                    <Text style={styles.summaryLabel}>Avg rate</Text>
                    <Text style={styles.summaryValue}>
                      {typeof data?.avg_hourly_rate_cents === "number"
                        ? money(data.avg_hourly_rate_cents / 100)
                        : "—"}
                    </Text>
                  </View>
                </View>
              </Card>

              <Text style={styles.sectionTitle}>By category</Text>
              {breakdown.length === 0 ? (
                <EmptyState
                  icon="people-outline"
                  title="No payroll data yet"
                  subtitle="Once time-entries + wages are recorded, breakdown appears here."
                  testID="cfo-payroll-empty"
                />
              ) : (
                breakdown.map((b: any, idx: number) => (
                  <View
                    key={b.category || b.label || idx}
                    style={styles.row}
                    testID={`cfo-payroll-row-${idx}`}
                  >
                    <Text style={styles.rowLabel}>{b.category || b.label}</Text>
                    <Text style={styles.rowValue}>
                      {money(((b.wages_cents ?? b.total_cents) || 0) / 100)}
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
  sectionTitle: { fontFamily: font.semibold, fontSize: fontSize.md, color: colors.onSurface, marginBottom: spacing.xs },
  row: {
    flexDirection: "row", justifyContent: "space-between", alignItems: "center",
    padding: spacing.md, borderRadius: radius.md, borderWidth: 1,
    borderColor: colors.border, backgroundColor: colors.surface,
  },
  rowLabel: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurface, flex: 1 },
  rowValue: { fontFamily: font.bold, fontSize: fontSize.md, color: colors.onSurface },
});
