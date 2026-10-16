/**
 * Phase 53e · Feb-2026 — Mobile EBIT dashboard tile.
 *
 * Compact exec summary that sits at the top of the admin +
 * super_admin dashboard. Fetches `/ebit/trend?months=6&revenue_basis=cash`
 * in a single round-trip and renders:
 *
 *   • current-month EBIT big number
 *   • delta vs last month (colored ↑/↓/→ + %)
 *   • 6-bar sparkline (plain <View>s — no chart lib)
 *   • "View report →" link to the profit-report page
 *
 * Role gate: parent Dashboard component only mounts this tile when
 * `user.role in {"super_admin", "admin"}`. Manager sees the full
 * EBIT/profit page but NOT this dashboard tile — matches Phase 53e
 * scope.
 */
import React, { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { mapApiError, errorKindIcon } from "@/src/utils/mapApiError";
import { EBITDA_TOOLTIP, EBITDA_LEGACY_LABEL, resolveEbitda } from "@/src/utils/ebitda";

// Phase 53f · Feb-2026 — drill-down helpers. Convert a "YYYY-MM"
// bucket into a ``{from, to}`` ISO range that the mobile
// ``/profit-report`` screen can consume as a preselected custom
// window.
function monthEndISO(monthStr: string | undefined): { from: string; to: string } | null {
  const [y, m] = String(monthStr || "").split("-").map(Number);
  if (!y || !m) return null;
  const last = new Date(Date.UTC(y, m, 0)).getUTCDate();
  const mm = String(m).padStart(2, "0");
  const dd = String(last).padStart(2, "0");
  return { from: `${y}-${mm}-01`, to: `${y}-${mm}-${dd}` };
}
function monthLabel(monthStr: string | undefined): string {
  const [y, m] = String(monthStr || "").split("-").map(Number);
  if (!y || !m) return monthStr || "";
  return new Date(Date.UTC(y, m - 1, 1))
    .toLocaleString("en-US", { month: "long", year: "numeric", timeZone: "UTC" });
}

type TrendPoint = { month: string; ebit: number; ebitda?: number | null };
type TrendResponse = { months: number; revenue_basis: string; series: TrendPoint[] };

function fmtUSD(n: number): string {
  const v = Number.isFinite(n) ? n : 0;
  const sign = v < 0 ? "-" : "";
  return `${sign}$${Math.abs(v).toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}

function pctDelta(cur: number, prev: number | undefined | null): number | null {
  if (prev == null || prev === 0) return null;
  return ((cur - prev) / Math.abs(prev)) * 100;
}

export default function EbitTile() {
  const router = useRouter();
  const [data, setData] = useState<TrendResponse | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [showInfo, setShowInfo] = useState(false);

  const load = useCallback(() => {
    setError(null);
    setData(null);
    api.get("/ebit/trend?months=6&revenue_basis=cash")
      .then((body: TrendResponse) => setData(body))
      .catch((e: any) => setError(e));
  }, []);

  useEffect(() => { load(); }, [load]);

  const series = data?.series || [];
  const cur = series[series.length - 1];
  const prev = series[series.length - 2];
  // EBITDA-SOFT-ADD — headline + delta use EBITDA; a legacy bucket
  // (null ebitda) on either side falls back to EBIT-vs-EBIT.
  const curR = resolveEbitda(cur);
  const prevR = resolveEbitda(prev);
  const legacy = curR.legacy;
  const curEbit = cur?.ebit || 0;
  const delta = (legacy || prevR.legacy)
    ? pctDelta(curEbit, prev?.ebit)
    : pctDelta(curR.value, prevR.value);
  const trendIconName =
    delta == null ? "remove-outline"
    : delta > 0 ? "trending-up"
    : delta < 0 ? "trending-down"
    : "remove-outline";
  const deltaColor =
    delta == null || delta === 0 ? colors.muted
    : delta > 0 ? "#16A34A" : "#DC2626";
  const deltaBg =
    delta == null || delta === 0 ? colors.surfaceSecondary
    : delta > 0 ? "#DCFCE7" : "#FEE2E2";

  const maxAbs = Math.max(...series.map((p) => Math.abs(p?.ebit || 0)), 1);

  return (
    <View style={styles.card} testID="dashboard-ebit-tile">
      <View style={styles.header}>
        <Pressable
          testID="dashboard-ebitda-info-btn"
          onPress={() => setShowInfo((v) => !v)}
          style={styles.labelPress}
          hitSlop={10}
          accessibilityRole="button"
          accessibilityLabel="What is EBITDA?"
          accessibilityHint={EBITDA_TOOLTIP}
        >
          <Text style={styles.label} testID="dashboard-ebit-tile-label">EBITDA · This month</Text>
          <Ionicons name="information-circle-outline" size={13} color={colors.muted} />
        </Pressable>
        <Pressable
          testID="dashboard-ebit-tile-report-link"
          onPress={() => router.push("/profit-report" as any)}
          style={styles.linkPress}
          accessibilityRole="link"
          accessibilityLabel="Open profit report"
        >
          <Text style={styles.linkText}>View report</Text>
          <Ionicons name="arrow-forward" size={12} color={colors.brandPrimary} />
        </Pressable>
      </View>
      {showInfo ? (
        <Text style={styles.info} testID="dashboard-ebitda-info-text">{EBITDA_TOOLTIP}</Text>
      ) : null}

      {error ? (() => {
        const mapped = mapApiError(error);
        return (
        <View style={styles.row}>
          <View style={styles.errorRow}>
            <Ionicons name={errorKindIcon(mapped.kind) as any} size={16} color={colors.error} />
            <Text style={styles.errorText} testID="dashboard-ebit-tile-error">
              {mapped.title}
            </Text>
          </View>
          <Pressable
            testID="dashboard-ebit-tile-retry"
            onPress={load}
            accessibilityRole="button"
            accessibilityLabel="Retry loading EBITDA">
            <Text style={styles.retry}>Retry</Text>
          </Pressable>
        </View>
        );
      })() : !data ? (
        <Text style={styles.loading} testID="dashboard-ebit-tile-loading">
          Loading current-month EBITDA…
        </Text>
      ) : (
        <>
          <View style={styles.valueRow}>
            {legacy ? (
              <>
                <Text testID="dashboard-ebit-tile-value"
                  style={[styles.value, { color: curEbit >= 0 ? colors.onSurface : "#DC2626" }]}>
                  {fmtUSD(curEbit)}
                </Text>
                <View style={styles.legacyChip} testID="dashboard-ebitda-tile-legacy-chip">
                  <Text style={styles.legacyText}>{EBITDA_LEGACY_LABEL}</Text>
                </View>
              </>
            ) : (
              <>
                <Text testID="dashboard-ebitda-tile-value"
                  style={[styles.value, { color: curR.value >= 0 ? colors.onSurface : "#DC2626" }]}>
                  {fmtUSD(curR.value)}
                </Text>
                {/* Secondary EBIT chip — always visible (web parity) */}
                <View style={styles.ebitChip}>
                  <Text style={styles.ebitChipText} testID="dashboard-ebit-tile-value">
                    EBIT {fmtUSD(curEbit)}
                  </Text>
                </View>
              </>
            )}
            {delta != null && (
              <View
                testID="dashboard-ebit-tile-delta"
                style={[styles.deltaChip, { backgroundColor: deltaBg }]}
              >
                <Ionicons name={trendIconName as any} size={12} color={deltaColor} />
                <Text style={[styles.deltaText, { color: deltaColor }]}>
                  {Math.abs(delta).toFixed(1)}% vs last month
                </Text>
              </View>
            )}
            {delta == null && (
              <Text style={styles.deltaEmpty} testID="dashboard-ebit-tile-no-prior">
                (no prior-month data)
              </Text>
            )}
          </View>

          <View style={styles.spark} testID="dashboard-ebit-tile-sparkline">
            {series.map((p, i) => {
              const v = p?.ebit || 0;
              const h = 4 + Math.round((Math.abs(v) / maxAbs) * 32);
              const onPickMonth = () => {
                const range = monthEndISO(p?.month);
                if (!range) return;
                // Phase 53f · Feb-2026 — drill-down into the full
                // mobile profit-report screen with a preselected
                // custom range. The screen reads ``from``/``to``
                // from ``useLocalSearchParams`` on mount.
                router.push({
                  pathname: "/profit-report" as any,
                  params: { from: range.from, to: range.to },
                });
              };
              return (
                <Pressable
                  key={p?.month || String(i)}
                  testID={`dashboard-ebit-tile-sparkline-bar-${i}`}
                  onPress={onPickMonth}
                  accessibilityRole="button"
                  accessibilityLabel={`Open EBIT report for ${monthLabel(p?.month)}`}
                  style={[
                    styles.sparkBar,
                    {
                      height: h,
                      backgroundColor: v >= 0 ? "#16A34A" : "#DC2626",
                    },
                  ]}
                />
              );
            })}
          </View>
          <Text style={styles.sparkCaption}>
            Last {series.length} months · cash-basis
          </Text>
        </>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.lg,
    marginBottom: spacing.lg,
  },
  header: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: spacing.xs,
  },
  label: {
    fontFamily: font.bold,
    fontSize: 10,
    color: colors.muted,
    letterSpacing: 0.8,
    textTransform: "uppercase",
  },
  linkPress: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
  },
  labelPress: { flexDirection: "row", alignItems: "center", gap: 4, flexShrink: 1 },
  info: {
    fontFamily: font.regular,
    fontSize: 12,
    lineHeight: 17,
    color: colors.muted,
    marginBottom: spacing.sm,
  },
  ebitChip: {
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: radius.pill,
    backgroundColor: colors.surfaceSecondary,
  },
  ebitChipText: { fontFamily: font.semibold, fontSize: 11, color: colors.muted },
  legacyChip: {
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: radius.pill,
    backgroundColor: "#FEF3C7",
  },
  legacyText: { fontFamily: font.semibold, fontSize: 11, color: "#92400E" },
  linkText: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.brandPrimary,
  },
  row: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  errorRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
  },
  errorText: {
    fontFamily: font.medium,
    fontSize: fontSize.sm,
    color: colors.error,
  },
  retry: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.brandPrimary,
    textDecorationLine: "underline",
  },
  loading: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
  },
  valueRow: {
    flexDirection: "row",
    alignItems: "baseline",
    flexWrap: "wrap",
    gap: 8,
  },
  value: {
    fontFamily: font.bold,
    fontSize: 28,
    color: colors.onSurface,
  },
  deltaChip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: radius.pill,
  },
  deltaText: {
    fontFamily: font.semibold,
    fontSize: 11,
  },
  deltaEmpty: {
    fontFamily: font.regular,
    fontSize: 11,
    color: colors.muted,
  },
  spark: {
    flexDirection: "row",
    alignItems: "flex-end",
    height: 40,
    gap: 3,
    marginTop: spacing.sm,
  },
  sparkBar: {
    flex: 1,
    borderTopLeftRadius: 2,
    borderTopRightRadius: 2,
  },
  sparkCaption: {
    fontFamily: font.regular,
    fontSize: 10,
    color: colors.muted,
    marginTop: 4,
  },
});
