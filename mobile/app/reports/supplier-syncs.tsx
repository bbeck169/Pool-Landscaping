/**
 * Phase 54g · Feb-2026 (upgraded in Phase 54g-B) — Mobile supplier sync
 * analytics screen.
 *
 * Full-fidelity read-only analytics view for admins/managers on
 * mobile. Mirrors the web ``/reports/supplier-syncs`` dashboard:
 *   • per-supplier card list with display name + slug
 *   • health-signal pill (healthy / warning / critical)
 *   • last-success / last-error timestamps + last error message
 *   • mini SVG sparkline of runs bucketed by day (success + error)
 *   • failure-count badge + retry-queue (consecutive-errors) summary
 *   • range chip strip (7 / 30 / 60 / 90 days)
 *   • pull-to-refresh
 *
 * Endpoint: ``GET /api/suppliers/analytics?days=N``. No POST/PATCH —
 * credential edits stay in ``/settings/suppliers``. Role guard mirrors
 * the web page (``AdminOrManagerForSuppliers`` → admin, super_admin,
 * manager) via ``<RoleGate level="admin_plus" />``.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, RefreshControl, Pressable,
} from "react-native";
import Svg, { Rect, G } from "react-native-svg";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import { Loading } from "@/src/components/ui";
import { RoleGate } from "@/src/components/RoleGate";

const SIGNAL_PALETTE: Record<string, { bg: string; fg: string; label: string }> = {
  healthy:  { bg: "#DCFCE7", fg: "#166534", label: "Healthy" },
  warning:  { bg: "#FEF3C7", fg: "#92400E", label: "Warning" },
  critical: { bg: "#FEE2E2", fg: "#991B1B", label: "Critical" },
};

const RANGES = [7, 30, 60, 90];

type TrendBucket = {
  date: string;
  runs: number;
  success: number;
  error: number;
  items_added: number;
  items_updated: number;
};

type SupplierRow = {
  slug: string;
  display_name: string;
  total_runs: number;
  success_count: number;
  error_count: number;
  success_rate: number;
  consecutive_errors: number;
  last_success_at?: string | null;
  last_error_at?: string | null;
  last_error_message?: string | null;
  trend_daily: TrendBucket[];
  health_signal: string;
  health_rationale: string;
};

function fmtDT(iso?: string | null) {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleDateString(); } catch { return iso; }
}

/**
 * Mini SVG sparkline: one column per day-bucket, height ∝ runs, red
 * segment on top proportional to errors / total runs.
 */
function Sparkline({ data, testID }: { data: TrendBucket[]; testID?: string }) {
  const w = 140, h = 34, pad = 2;
  if (!data || data.length === 0) {
    return (
      <Svg width={w} height={h} testID={testID}>
        <Rect x={0} y={0} width={w} height={h} fill="transparent" />
      </Svg>
    );
  }
  const maxRuns = Math.max(...data.map((d) => d.runs || 0), 1);
  const bw = Math.max(1, (w - pad * 2) / data.length - 1);
  return (
    <Svg width={w} height={h} testID={testID}>
      {data.map((d, i) => {
        const x = pad + i * (bw + 1);
        const totalH = (h - pad * 2) * ((d.runs || 0) / maxRuns);
        const errH = totalH * ((d.error || 0) / Math.max(d.runs || 1, 1));
        const sucH = totalH - errH;
        return (
          <G key={d.date}>
            <Rect x={x} y={h - pad - sucH} width={bw} height={sucH} fill="#16A34A" />
            <Rect x={x} y={h - pad - totalH} width={bw} height={errH} fill="#DC2626" />
          </G>
        );
      })}
    </Svg>
  );
}

function AnalyticsBody() {
  const [days, setDays] = useState(30);
  const [data, setData] = useState<{ suppliers: SupplierRow[] } | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback((d: number) => {
    api.get(`/suppliers/analytics?days=${d}`)
      .then((body) => setData(body))
      .catch(() => setData({ suppliers: [] }))
      .finally(() => setRefreshing(false));
  }, []);

  useEffect(() => { load(days); }, [load, days]);

  // Aggregate retry-queue summary — critical + warning + total consec errors.
  const summary = useMemo(() => {
    const rows = data?.suppliers || [];
    return rows.reduce(
      (acc, r) => ({
        critical: acc.critical + (r.health_signal === "critical" ? 1 : 0),
        warning:  acc.warning  + (r.health_signal === "warning" ? 1 : 0),
        retries:  acc.retries  + (r.consecutive_errors || 0),
        errors:   acc.errors   + (r.error_count || 0),
      }),
      { critical: 0, warning: 0, retries: 0, errors: 0 },
    );
  }, [data]);

  return (
    <View style={styles.root} testID="mobile-supplier-analytics-screen">
      <Header title="Sync analytics" back subtitle={`Last ${days} days`} />
      <View style={styles.chipStrip}>
        {RANGES.map((n) => (
          <Pressable key={n} onPress={() => setDays(n)}
                     style={[styles.chip, days === n && styles.chipActive]}
                     testID={`mobile-analytics-range-${n}`}>
            <Text style={[styles.chipText, days === n && styles.chipTextActive]}>
              {n}d
            </Text>
          </Pressable>
        ))}
      </View>
      {!data ? (
        <Loading testID="mobile-analytics-loading" />
      ) : (
        <ScrollView
          contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}
          refreshControl={<RefreshControl refreshing={refreshing}
                              onRefresh={() => { setRefreshing(true); load(days); }} />}
          testID="mobile-analytics-scroll"
        >
          <View style={styles.summaryRow} testID="mobile-analytics-summary">
            <View style={styles.summaryCell}>
              <Text style={styles.summaryLabel}>Critical</Text>
              <Text style={[styles.summaryValue, { color: "#991B1B" }]}
                    testID="mobile-analytics-summary-critical">
                {summary.critical}
              </Text>
            </View>
            <View style={styles.summaryCell}>
              <Text style={styles.summaryLabel}>Warning</Text>
              <Text style={[styles.summaryValue, { color: "#92400E" }]}
                    testID="mobile-analytics-summary-warning">
                {summary.warning}
              </Text>
            </View>
            <View style={styles.summaryCell}>
              <Text style={styles.summaryLabel}>Retry queue</Text>
              <Text style={styles.summaryValue}
                    testID="mobile-analytics-summary-retries">
                {summary.retries}
              </Text>
            </View>
            <View style={styles.summaryCell}>
              <Text style={styles.summaryLabel}>Failures</Text>
              <Text style={styles.summaryValue}
                    testID="mobile-analytics-summary-errors">
                {summary.errors}
              </Text>
            </View>
          </View>

          {(data.suppliers || []).length === 0 ? (
            <View style={styles.emptyCard} testID="mobile-analytics-empty">
              <Text style={styles.emptyText}>No supplier sync activity yet.</Text>
            </View>
          ) : null}

          {(data.suppliers || []).map((s) => {
            const p = SIGNAL_PALETTE[s.health_signal] || SIGNAL_PALETTE.healthy;
            return (
              <View key={s.slug} style={styles.card}
                    testID={`mobile-analytics-card-${s.slug}`}>
                <View style={styles.cardHeader}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.cardTitle}>{s.display_name}</Text>
                    <Text style={styles.cardSlug}>{s.slug}</Text>
                  </View>
                  <View style={[styles.pill, { backgroundColor: p.bg }]}>
                    <Text style={[styles.pillText, { color: p.fg }]}
                          testID={`mobile-analytics-signal-${s.slug}`}>
                      {p.label}
                    </Text>
                  </View>
                </View>
                <Text style={styles.rationale}>{s.health_rationale}</Text>

                <View style={styles.sparklineWrap}>
                  <Sparkline data={s.trend_daily}
                             testID={`mobile-analytics-sparkline-${s.slug}`} />
                </View>

                <View style={styles.badgeRow}>
                  {s.error_count > 0 ? (
                    <View style={[styles.badge, { backgroundColor: "#FEE2E2" }]}
                          testID={`mobile-analytics-failure-badge-${s.slug}`}>
                      <Text style={[styles.badgeText, { color: "#991B1B" }]}>
                        {s.error_count} failure{s.error_count === 1 ? "" : "s"}
                      </Text>
                    </View>
                  ) : null}
                  {s.consecutive_errors > 0 ? (
                    <View style={[styles.badge, { backgroundColor: "#FEF3C7" }]}
                          testID={`mobile-analytics-retry-badge-${s.slug}`}>
                      <Text style={[styles.badgeText, { color: "#92400E" }]}>
                        {s.consecutive_errors} in retry queue
                      </Text>
                    </View>
                  ) : null}
                </View>

                <View style={styles.metaRow}>
                  <Text style={styles.metaLabel}>Success rate</Text>
                  <Text style={styles.metaValue}>
                    {Math.round((s.success_rate || 0) * 100)}%
                    {" "}({s.success_count}/{s.total_runs})
                  </Text>
                </View>
                <View style={styles.metaRow}>
                  <Text style={styles.metaLabel}>Last success</Text>
                  <Text style={styles.metaValue}>{fmtDT(s.last_success_at)}</Text>
                </View>
                <View style={styles.metaRow}>
                  <Text style={styles.metaLabel}>Last error</Text>
                  <Text style={styles.metaValue}>{fmtDT(s.last_error_at)}</Text>
                </View>
                {s.last_error_message ? (
                  <Text style={styles.errorMsg}
                        testID={`mobile-analytics-error-${s.slug}`}
                        numberOfLines={2}>
                    {s.last_error_message}
                  </Text>
                ) : null}
              </View>
            );
          })}
        </ScrollView>
      )}
    </View>
  );
}

export default function SupplierSyncAnalyticsMobile() {
  // Mirrors web ``AdminOrManagerForSuppliers`` → admin/super_admin/manager.
  return (
    <RoleGate level="admin_plus" testID="mobile-supplier-analytics-role-gate">
      <AnalyticsBody />
    </RoleGate>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  chipStrip: { flexDirection: "row", gap: 6,
               paddingHorizontal: spacing.lg, paddingTop: spacing.sm },
  chip: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: 999,
          borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
  chipActive: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  chipText: { fontFamily: font.regular, fontSize: 12, color: colors.onSurface },
  chipTextActive: { color: colors.onBrandPrimary, fontFamily: font.bold },

  summaryRow: {
    flexDirection: "row",
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border,
    padding: spacing.md,
    marginBottom: spacing.md,
    justifyContent: "space-between",
  },
  summaryCell: { alignItems: "center", flex: 1 },
  summaryLabel: { fontFamily: font.regular, fontSize: 10, color: colors.muted,
                  letterSpacing: 1, textTransform: "uppercase" },
  summaryValue: { fontFamily: font.bold, fontSize: fontSize.lg,
                  color: colors.onSurface, marginTop: 2 },

  emptyCard: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border,
    padding: spacing.lg,
    alignItems: "center",
    marginBottom: spacing.md,
  },
  emptyText: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted },

  card: { backgroundColor: colors.surface, borderRadius: radius.md,
          padding: spacing.md, borderWidth: 1, borderColor: colors.border,
          marginBottom: spacing.md },
  cardHeader: { flexDirection: "row", justifyContent: "space-between",
                alignItems: "flex-start" },
  cardTitle: { fontFamily: font.bold, fontSize: fontSize.md, color: colors.onSurface },
  cardSlug: { fontFamily: font.regular, fontSize: 10, color: colors.muted, marginTop: 2 },
  rationale: { fontFamily: font.regular, fontSize: fontSize.xs,
               color: colors.muted, marginTop: 4 },

  sparklineWrap: { marginTop: spacing.sm, marginBottom: 2 },

  badgeRow: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: spacing.sm },
  badge: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 999 },
  badgeText: { fontFamily: font.bold, fontSize: 10 },

  metaRow: { flexDirection: "row", justifyContent: "space-between",
             marginTop: 6 },
  metaLabel: { fontFamily: font.regular, fontSize: fontSize.xs, color: colors.muted },
  metaValue: { fontFamily: font.bold, fontSize: fontSize.xs, color: colors.onSurface },
  errorMsg: { fontFamily: font.regular, fontSize: 10,
              color: "#991B1B", marginTop: 6 },
  pill: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 999 },
  pillText: { fontFamily: font.bold, fontSize: 10 },
});
