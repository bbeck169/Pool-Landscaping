// MR3 · Feb-2026 — Mobile widget-analytics screen (read-only parity).
//
// Reuses the same `/api/widget/analytics/summary` endpoint the web
// admin hits. Shows:
//   • 3 KPI cards — Impressions, Clicks, CTR
//   • A range toggle for 7d / 30d / 90d
//   • Top 10 check-ins list (no chart on mobile per spec)
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, RefreshControl, Pressable,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Loading, EmptyState } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";

type Range = "7d" | "30d" | "90d";

type TopRow = {
  checkin_id: string;
  title?: string;
  impressions: number;
  clicks: number;
  ctr: number;
};

type Summary = {
  range: Range;
  impressions: number;
  clicks: number;
  ctr: number;
  top_checkins: TopRow[];
};

const RANGES: { key: Range; label: string }[] = [
  { key: "7d",  label: "7d"  },
  { key: "30d", label: "30d" },
  { key: "90d", label: "90d" },
];

function pct(f: number | null | undefined): string {
  if (f == null || Number.isNaN(f)) return "0.0%";
  return `${(f * 100).toFixed(1)}%`;
}

export default function WidgetAnalytics() {
  const [range, setRange] = useState<Range>("7d");
  const [summary, setSummary] = useState<Summary | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async (r: Range) => {
    try {
      const s = await api.get(`/widget/analytics/summary?range=${r}`);
      setSummary(s as Summary);
    } catch {
      setSummary(null);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => {
    setLoading(true);
    load(range);
  }, [load, range]));

  useEffect(() => {
    setLoading(true);
    load(range);
  }, [range, load]);

  const impressions = summary?.impressions ?? 0;
  const clicks      = summary?.clicks ?? 0;
  const ctr         = summary?.ctr ?? 0;
  const top         = summary?.top_checkins || [];

  const isEmpty = !loading && impressions === 0 && clicks === 0;

  return (
    <View style={styles.root} testID="mobile-widget-analytics">
      <Header title="Widget Analytics" back subtitle="Public check-in widget" />
      <ScrollView
        contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}
        refreshControl={
          <RefreshControl refreshing={refreshing}
                           onRefresh={() => { setRefreshing(true); load(range); }} />
        }
      >
        {/* Range toggle */}
        <View style={styles.toggleRow} testID="mobile-widget-analytics-range-toggle">
          {RANGES.map((r) => (
            <Pressable
              key={r.key}
              testID={`mobile-widget-analytics-range-${r.key}`}
              onPress={() => setRange(r.key)}
              style={[styles.toggleBtn, range === r.key && styles.toggleBtnActive]}
            >
              <Text style={[styles.toggleTxt, range === r.key && styles.toggleTxtActive]}>
                {r.label}
              </Text>
            </Pressable>
          ))}
        </View>

        {loading ? (
          <Loading testID="mobile-widget-analytics-loading" />
        ) : (
          <>
            {/* KPI cards */}
            <View style={styles.kpiRow}>
              <View style={styles.kpiCard} testID="mobile-widget-kpi-impressions">
                <View style={styles.kpiIconWrap}>
                  <Ionicons name="eye-outline" size={16} color={colors.brand} />
                </View>
                <Text style={styles.kpiLabel}>Impressions</Text>
                <Text style={styles.kpiValue}>{impressions.toLocaleString()}</Text>
              </View>
              <View style={styles.kpiCard} testID="mobile-widget-kpi-clicks">
                <View style={styles.kpiIconWrap}>
                  <Ionicons name="hand-left-outline" size={16} color={colors.brandSecondary} />
                </View>
                <Text style={styles.kpiLabel}>Clicks</Text>
                <Text style={styles.kpiValue}>{clicks.toLocaleString()}</Text>
              </View>
              <View style={styles.kpiCard} testID="mobile-widget-kpi-ctr">
                <View style={styles.kpiIconWrap}>
                  <Ionicons name="stats-chart-outline" size={16} color={colors.info} />
                </View>
                <Text style={styles.kpiLabel}>CTR</Text>
                <Text style={styles.kpiValue}>{pct(ctr)}</Text>
              </View>
            </View>

            {/* Empty state */}
            {isEmpty && (
              <EmptyState
                icon="analytics-outline"
                title="No widget activity yet"
                subtitle="Once your widget is embedded and viewed by a visitor, impressions and clicks will appear here."
                testID="mobile-widget-analytics-empty"
              />
            )}

            {/* Top 10 */}
            {!isEmpty && (
              <View style={styles.topBlock} testID="mobile-widget-analytics-top">
                <Text style={styles.topHeading}>Top 10 check-ins</Text>
                {top.length === 0 ? (
                  <Text style={styles.emptyLine} testID="mobile-widget-analytics-top-empty">
                    No clicks yet in this window.
                  </Text>
                ) : (
                  top.map((r, i) => (
                    <View key={r.checkin_id}
                           style={styles.topRow}
                           testID={`mobile-widget-analytics-top-row-${i}`}>
                      <View style={{ flex: 1, minWidth: 0 }}>
                        <Text style={styles.topTitle} numberOfLines={1}>
                          {r.title || r.checkin_id}
                        </Text>
                        <Text style={styles.topSub}>
                          {r.impressions.toLocaleString()} impressions · CTR {pct(r.ctr)}
                        </Text>
                      </View>
                      <View style={styles.clicksBadge}>
                        <Text style={styles.clicksTxt}>{r.clicks.toLocaleString()}</Text>
                        <Text style={styles.clicksLbl}>clicks</Text>
                      </View>
                    </View>
                  ))
                )}
              </View>
            )}
          </>
        )}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  toggleRow: {
    flexDirection: "row",
    alignSelf: "flex-start",
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: 4,
    marginBottom: spacing.lg,
  },
  toggleBtn: {
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.lg,
    borderRadius: radius.md,
  },
  toggleBtnActive: { backgroundColor: colors.brand },
  toggleTxt:       { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.muted },
  toggleTxtActive: { color: colors.onBrandPrimary },

  kpiRow: { flexDirection: "row", gap: spacing.md, marginBottom: spacing.lg },
  kpiCard: {
    flex: 1,
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
  },
  kpiIconWrap: { marginBottom: spacing.xs },
  kpiLabel: {
    fontFamily: font.medium, fontSize: fontSize.xs, color: colors.muted,
    textTransform: "uppercase", letterSpacing: 0.5,
  },
  kpiValue: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface, marginTop: 2 },

  topBlock: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
  },
  topHeading: {
    fontFamily: font.semibold, fontSize: fontSize.base,
    color: colors.onSurface, marginBottom: spacing.md,
  },
  topRow: {
    flexDirection: "row", alignItems: "center", gap: spacing.md,
    paddingVertical: spacing.sm, borderTopWidth: 1, borderTopColor: colors.divider,
  },
  topTitle: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  topSub:   { fontFamily: font.regular, fontSize: fontSize.xs, color: colors.muted, marginTop: 2 },
  clicksBadge: {
    backgroundColor: colors.brandTertiary, borderRadius: radius.md,
    paddingHorizontal: spacing.md, paddingVertical: spacing.xs, alignItems: "center",
  },
  clicksTxt: { fontFamily: font.bold, fontSize: fontSize.base, color: colors.onBrandTertiary },
  clicksLbl: { fontFamily: font.regular, fontSize: fontSize.xs, color: colors.onBrandTertiary },

  emptyLine: {
    fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted,
    textAlign: "center", paddingVertical: spacing.lg,
  },
});
