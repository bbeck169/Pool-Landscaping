// Phase 16 · Feb-2026 — Bulk charge runs list (Admin/Super Admin only).
//
// Read-only. Triggering a bulk charge from mobile is deliberately out of
// scope this phase (desktop-only per Phase 14b policy). Tap a row to
// drill into per-invoice results.
import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, RefreshControl,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { router, useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Card, EmptyState, Loading } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";
import { RoleGate } from "@/src/components/RoleGate";

type Run = {
  run_id: string;
  dry_run: boolean;
  invoice_count: number;
  started_at?: string;
  summary?: {
    charged?: number;
    skipped?: number;
    failed?: number;
    total_amount_charged_cents?: number;
  };
};

function _dollars(c: number): string {
  return `$${((c || 0) / 100).toFixed(2)}`;
}

export default function BulkChargeRunsList() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const j: any = await api.get("/invoices/bulk-charge-runs?limit=100");
      setRuns(j?.runs || []);
    } catch {
      setRuns([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  return (
    <RoleGate level="strict_admin">
      <View style={styles.container}>
        <Header title="Bulk charge runs" />
        <ScrollView
          contentContainerStyle={styles.body}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={async () => {
              setRefreshing(true); await load(); setRefreshing(false);
            }} />
          }
        >
          <Text style={styles.hint} testID="bulk-runs-desktop-note">
            Read-only. Trigger new bulk charges from the desktop invoices page.
          </Text>
          {loading ? (
            <Loading />
          ) : runs.length === 0 ? (
            <EmptyState
              icon="cash-outline"
              title="No bulk charge runs yet"
              subtitle="Initiate one from the desktop invoices page."
              testID="bulk-runs-empty"
            />
          ) : (
            runs.map((r) => (
              <Pressable
                key={r.run_id}
                testID={`bulk-run-row-${r.run_id}`}
                accessibilityLabel={`Open run ${r.run_id}`}
                onPress={() => router.push({
                  pathname: "/finance/bulk-charge-runs/[runId]",
                  params: { runId: r.run_id },
                })}
                style={({ pressed }) => [styles.runCard, pressed && { opacity: 0.8 }]}
              >
                <View style={styles.runHeader}>
                  <Text style={styles.runDate}>
                    {r.started_at ? new Date(r.started_at).toLocaleString() : "—"}
                  </Text>
                  <View style={[
                    styles.kindChip,
                    r.dry_run ? styles.kindDry : styles.kindReal,
                  ]}>
                    <Text style={[
                      styles.kindText,
                      r.dry_run ? styles.kindTextDry : styles.kindTextReal,
                    ]}>{r.dry_run ? "DRY RUN" : "REAL"}</Text>
                  </View>
                </View>
                <View style={styles.metricRow}>
                  <Metric label="Selected" value={String(r.invoice_count)} />
                  <Metric label="Charged" value={String(r.summary?.charged ?? 0)} />
                  <Metric label="Skipped" value={String(r.summary?.skipped ?? 0)} tone="muted" />
                  <Metric label="Failed" value={String(r.summary?.failed ?? 0)} tone={((r.summary?.failed ?? 0) > 0) ? "error" : "muted"} />
                </View>
                <View style={styles.amountRow}>
                  <Text style={styles.amountLabel}>Amount</Text>
                  <Text style={styles.amountValue}>
                    {_dollars(r.summary?.total_amount_charged_cents || 0)}
                  </Text>
                </View>
              </Pressable>
            ))
          )}
        </ScrollView>
      </View>
    </RoleGate>
  );
}

function Metric({ label, value, tone }: {
  label: string; value: string; tone?: "muted" | "error";
}) {
  const color = tone === "error" ? colors.error : tone === "muted" ? colors.muted : colors.onSurface;
  return (
    <View style={styles.metric}>
      <Text style={[styles.metricLabel, { color: colors.muted }]}>{label}</Text>
      <Text style={[styles.metricValue, { color }]}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.surface },
  body: { padding: spacing.lg, gap: spacing.md, paddingBottom: spacing["3xl"] },
  hint: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginBottom: 4 },
  runCard: {
    padding: spacing.md, borderRadius: radius.md, borderWidth: 1,
    borderColor: colors.border, backgroundColor: colors.surface, gap: spacing.sm,
  },
  runHeader: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  runDate: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurface },
  kindChip: { paddingHorizontal: 8, paddingVertical: 2, borderRadius: radius.sm },
  kindDry: { backgroundColor: colors.surfaceSecondary },
  kindReal: { backgroundColor: "#DCFCE7" },
  kindText: { fontFamily: font.bold, fontSize: 10 },
  kindTextDry: { color: colors.muted },
  kindTextReal: { color: colors.success },
  metricRow: { flexDirection: "row", gap: spacing.sm },
  metric: { flex: 1 },
  metricLabel: { fontFamily: font.medium, fontSize: 10, textTransform: "uppercase", letterSpacing: 0.4 },
  metricValue: { fontFamily: font.bold, fontSize: fontSize.lg, marginTop: 2 },
  amountRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "baseline", marginTop: spacing.xs },
  amountLabel: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted },
  amountValue: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
});
