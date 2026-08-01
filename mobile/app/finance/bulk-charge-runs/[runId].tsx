// Phase 16 · Feb-2026 — Bulk charge run detail (Admin/Super Admin only).
import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView } from "react-native";
import { useFocusEffect, useLocalSearchParams } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Card, EmptyState, Loading } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";
import { RoleGate } from "@/src/components/RoleGate";

type Row = {
  invoice_id: string;
  status: string;
  charge_id?: string;
  skip_reason?: string;
  error_code?: string;
  error_message?: string;
  amount_charged_cents?: number;
  amount_cents?: number;
};

type Run = {
  run_id: string;
  dry_run: boolean;
  invoice_count: number;
  started_at?: string;
  results?: Row[];
  summary?: any;
};

function _dollars(c: number): string {
  return `$${((c || 0) / 100).toFixed(2)}`;
}

function _statusMeta(s: string): { bg: string; fg: string } {
  if (s === "charged") return { bg: "#DCFCE7", fg: colors.success };
  if (s === "failed")  return { bg: "#FEE2E2", fg: colors.error };
  if (s === "would_charge") return { bg: colors.brandTertiary, fg: colors.onBrandTertiary };
  return { bg: colors.surfaceSecondary, fg: colors.muted };
}

export default function BulkChargeRunDetail() {
  const { runId } = useLocalSearchParams<{ runId: string }>();
  const [run, setRun] = useState<Run | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    if (!runId) return;
    setLoading(true);
    try {
      const j: any = await api.get(`/invoices/bulk-charge-runs/${encodeURIComponent(runId)}`);
      setRun(j || null);
    } catch {
      setRun(null);
    } finally {
      setLoading(false);
    }
  }, [runId]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  return (
    <RoleGate level="strict_admin">
      <View style={styles.container}>
        <Header title={`Run ${(runId as string || "").slice(0, 8)}…`} />
        {loading ? (
          <Loading />
        ) : !run ? (
          <EmptyState
            icon="alert-circle-outline"
            title="Run not found"
            subtitle="It may have been purged or the id is wrong."
            testID="bulk-run-detail-missing"
          />
        ) : (
          <ScrollView contentContainerStyle={styles.body}>
            <Card>
              <View style={styles.kpiRow}>
                <Kpi label="Kind" value={run.dry_run ? "Dry run" : "Real"} />
                <Kpi label="Selected" value={String(run.invoice_count)} />
                <Kpi label="Charged" value={String(run.summary?.charged ?? 0)} />
              </View>
              <View style={{ height: spacing.sm }} />
              <Text style={styles.total} testID="bulk-run-detail-total">
                Total charged: {_dollars(run.summary?.total_amount_charged_cents || 0)}
              </Text>
            </Card>

            <Card>
              <Text style={styles.sectionLabel}>Per invoice</Text>
              {(run.results || []).map((r) => {
                const m = _statusMeta(r.status);
                return (
                  <View key={r.invoice_id} style={styles.itemRow}
                        testID={`bulk-run-detail-item-${r.invoice_id}`}>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.invId} numberOfLines={1}>{r.invoice_id}</Text>
                      <View style={styles.badgeRow}>
                        <View style={[styles.statusBadge, { backgroundColor: m.bg }]}>
                          <Text style={[styles.statusText, { color: m.fg }]}>
                            {r.status}{r.skip_reason ? ` · ${r.skip_reason}` : ""}
                          </Text>
                        </View>
                        {r.charge_id ? (
                          <Text style={styles.chargeId} numberOfLines={1}>{r.charge_id}</Text>
                        ) : null}
                      </View>
                      {r.error_code ? (
                        <Text style={styles.errorText} numberOfLines={2}>
                          {r.error_code}{r.error_message ? `: ${r.error_message}` : ""}
                        </Text>
                      ) : null}
                    </View>
                    <Text style={styles.amount}>
                      {r.amount_charged_cents
                        ? _dollars(r.amount_charged_cents)
                        : r.amount_cents ? _dollars(r.amount_cents) : "—"}
                    </Text>
                  </View>
                );
              })}
            </Card>
          </ScrollView>
        )}
      </View>
    </RoleGate>
  );
}

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.kpi}>
      <Text style={styles.kpiLabel}>{label}</Text>
      <Text style={styles.kpiValue}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.surface },
  body: { padding: spacing.lg, gap: spacing.md, paddingBottom: spacing["3xl"] },
  kpiRow: { flexDirection: "row", gap: spacing.sm },
  kpi: { flex: 1 },
  kpiLabel: { fontFamily: font.medium, fontSize: 10, color: colors.muted, textTransform: "uppercase", letterSpacing: 0.4 },
  kpiValue: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface, marginTop: 4 },
  total: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  sectionLabel: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface, marginBottom: spacing.sm },
  itemRow: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    paddingVertical: 8, borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.divider,
  },
  invId: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurface },
  badgeRow: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: 4, flexWrap: "wrap" },
  statusBadge: { paddingHorizontal: 8, paddingVertical: 2, borderRadius: radius.sm },
  statusText: { fontFamily: font.bold, fontSize: 10, textTransform: "uppercase", letterSpacing: 0.3 },
  chargeId: { fontFamily: font.regular, fontSize: 10, color: colors.muted },
  errorText: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.error, marginTop: 4 },
  amount: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface },
});
