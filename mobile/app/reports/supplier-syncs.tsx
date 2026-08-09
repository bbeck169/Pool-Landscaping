/**
 * Phase 54g · Feb-2026 — Mobile supplier sync analytics (view-only).
 *
 * Lightweight scrollable list of 5 cards. No sparkline (native SVG
 * would require a chart dep — deferred). Numbers + health signal
 * only. Range picker mirrors web.
 */
import React, { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, RefreshControl, Pressable } from "react-native";
import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import { Loading } from "@/src/components/ui";

const SIGNAL_PALETTE: Record<string, { bg: string; fg: string; label: string }> = {
  healthy:  { bg: "#DCFCE7", fg: "#166534", label: "Healthy" },
  warning:  { bg: "#FEF3C7", fg: "#92400E", label: "Warning" },
  critical: { bg: "#FEE2E2", fg: "#991B1B", label: "Critical" },
};

const RANGES = [7, 30, 60, 90];

function fmtDT(iso?: string | null) {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleDateString(); } catch { return iso; }
}

export default function SupplierSyncAnalyticsMobile() {
  const [days, setDays] = useState(30);
  const [data, setData] = useState<any>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback((d: number) => {
    api.get(`/suppliers/analytics?days=${d}`)
      .then((body) => setData(body))
      .catch(() => setData({ suppliers: [] }))
      .finally(() => setRefreshing(false));
  }, []);

  useEffect(() => { load(days); }, [load, days]);

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
          {(data.suppliers || []).map((s: any) => {
            const p = SIGNAL_PALETTE[s.health_signal] || SIGNAL_PALETTE.healthy;
            return (
              <View key={s.slug} style={styles.card}
                    testID={`mobile-analytics-card-${s.slug}`}>
                <View style={styles.cardHeader}>
                  <Text style={styles.cardTitle}>{s.display_name}</Text>
                  <View style={[styles.pill, { backgroundColor: p.bg }]}>
                    <Text style={[styles.pillText, { color: p.fg }]}
                          testID={`mobile-analytics-signal-${s.slug}`}>
                      {p.label}
                    </Text>
                  </View>
                </View>
                <Text style={styles.rationale}>{s.health_rationale}</Text>
                <View style={styles.metaRow}>
                  <Text style={styles.metaLabel}>Success rate</Text>
                  <Text style={styles.metaValue}>
                    {Math.round((s.success_rate || 0) * 100)}%
                    ({s.success_count}/{s.total_runs})
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

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  chipStrip: { flexDirection: "row", gap: 6,
               paddingHorizontal: spacing.lg, paddingTop: spacing.sm },
  chip: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: 999,
          borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
  chipActive: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  chipText: { fontFamily: font.regular, fontSize: 12, color: colors.onSurface },
  chipTextActive: { color: colors.onBrandPrimary, fontFamily: font.bold },
  card: { backgroundColor: colors.surface, borderRadius: radius.md,
          padding: spacing.md, borderWidth: 1, borderColor: colors.border,
          marginBottom: spacing.md },
  cardHeader: { flexDirection: "row", justifyContent: "space-between",
                alignItems: "center" },
  cardTitle: { fontFamily: font.bold, fontSize: fontSize.md, color: colors.onSurface, flex: 1 },
  rationale: { fontFamily: font.regular, fontSize: fontSize.xs,
               color: colors.muted, marginTop: 4 },
  metaRow: { flexDirection: "row", justifyContent: "space-between",
             marginTop: 6 },
  metaLabel: { fontFamily: font.regular, fontSize: fontSize.xs, color: colors.muted },
  metaValue: { fontFamily: font.bold, fontSize: fontSize.xs, color: colors.onSurface },
  errorMsg: { fontFamily: font.regular, fontSize: 10,
              color: "#991B1B", marginTop: 6 },
  pill: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 999 },
  pillText: { fontFamily: font.bold, fontSize: 10 },
});
