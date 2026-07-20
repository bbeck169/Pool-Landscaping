/** Reviews Hub — Phase 3 mobile parity (Feb 2026). */
import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, ActivityIndicator } from "react-native";
import { useRouter, useFocusEffect } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Header } from "@/src/components/widgets";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";
import { getStats, getLatestSyncPerPlatform } from "@/src/api/reviews";
import { StarRatingDisplayNative } from "@/src/components/reviews/StarRatingDisplayNative";

const CARDS = [
  { key: "requests",    icon: "send-outline",         label: "Requests",    route: "/(app)/reviews/requests", accent: "#0284C7" },
  { key: "recent",      icon: "chatbubbles-outline",  label: "Recent Reviews", route: "/(app)/reviews/recent",   accent: "#7C3AED" },
  { key: "leaderboard", icon: "trophy-outline",       label: "Leaderboard", route: "/(app)/reviews/leaderboard", accent: "#EA580C" },
  { key: "platforms",   icon: "globe-outline",        label: "Platforms",   route: "/(app)/reviews/platforms",   accent: "#16A34A" },
  { key: "widget",      icon: "code-slash-outline",   label: "Widget",      route: "/(app)/reviews/widget",      accent: "#0891B2" },
] as const;

export default function ReviewsHubScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const [stats, setStats] = useState<any>(null);
  const [syncStrip, setSyncStrip] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useFocusEffect(useCallback(() => {
    setLoading(true);
    Promise.allSettled([getStats(), getLatestSyncPerPlatform()])
      .then(([s, l]) => {
        setStats(s.status === "fulfilled" ? s.value : null);
        setSyncStrip(l.status === "fulfilled" ? l.value : null);
      })
      .finally(() => setLoading(false));
  }, []));

  return (
    <View testID="reviews-hub" style={styles.root}>
      <Header title="Reviews" subtitle="Ratings, requests & platforms" back />
      <ScrollView contentContainerStyle={[styles.scroll, { paddingBottom: insets.bottom + 24 }]}>
        {/* KPI cards */}
        <View style={styles.kpiRow}>
          <View style={[styles.kpi, styles.kpiAccent]} testID="reviews-kpi-avg">
            <Text style={styles.kpiLabel}>AVERAGE</Text>
            {loading ? <ActivityIndicator size="small" color={colors.brand} /> : (
              <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
                <Text style={styles.kpiValue}>{stats ? (stats.avg_star || 0).toFixed(1) : "—"}</Text>
                <StarRatingDisplayNative value={stats?.avg_star || 0} size={13} />
              </View>
            )}
            <Text style={styles.kpiHint}>{stats?.total ? `${stats.total} reviews` : "—"}</Text>
          </View>
          <View style={styles.kpi} testID="reviews-kpi-public">
            <Text style={styles.kpiLabel}>PUBLIC</Text>
            <Text style={styles.kpiValue}>{stats?.count_public ?? "—"}</Text>
            <Text style={styles.kpiHint}>{stats?.count_private != null ? `${stats.count_private} private` : ""}</Text>
          </View>
          <View style={styles.kpi} testID="reviews-kpi-delta">
            <Text style={styles.kpiLabel}>30-DAY</Text>
            <Text style={styles.kpiValue}>{stats?.delta_last_30d ?? "—"}</Text>
            <Text style={styles.kpiHint}>new reviews</Text>
          </View>
        </View>

        {/* Sync strip */}
        {syncStrip ? (
          <View style={styles.syncStrip} testID="reviews-sync-strip">
            <Text style={styles.syncStripLabel}>Last sync</Text>
            <View style={{ flexDirection: "row", gap: 6, flexWrap: "wrap" }}>
              {["google", "facebook", "yelp"].map((p) => {
                const row = syncStrip?.[p];
                const tone = row?.status === "ok" ? "#16A34A" : row?.status === "error" ? "#DC2626" : "#94A3B8";
                return (
                  <View key={p} style={[styles.syncChip, { borderColor: tone }]}>
                    <View style={[styles.syncDot, { backgroundColor: tone }]} />
                    <Text style={styles.syncChipText}>
                      {p} · {row?.status || "never"}
                    </Text>
                  </View>
                );
              })}
            </View>
          </View>
        ) : null}

        {/* Nav cards */}
        <View style={styles.cardsGrid}>
          {CARDS.map((c) => (
            <TouchableOpacity
              key={c.key}
              testID={`reviews-hub-${c.key}`}
              activeOpacity={0.7}
              style={styles.card}
              onPress={() => router.push(c.route as any)}
            >
              <View style={[styles.iconCircle, { backgroundColor: c.accent + "18" }]}>
                <Ionicons name={c.icon as any} size={22} color={c.accent} />
              </View>
              <Text style={styles.cardLabel}>{c.label}</Text>
            </TouchableOpacity>
          ))}
        </View>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  scroll: { padding: spacing.lg },
  kpiRow: { flexDirection: "row", gap: spacing.sm, marginBottom: spacing.md },
  kpi: {
    flex: 1, backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md, padding: spacing.md,
    borderWidth: 1, borderColor: colors.border,
    minHeight: 82,
  },
  kpiAccent: { backgroundColor: "#FEF3C7", borderColor: "#FDE68A" },
  kpiLabel: { fontFamily: font.bold, fontSize: 9, color: colors.muted, letterSpacing: 0.5, marginBottom: 4 },
  kpiValue: { fontFamily: font.bold, fontSize: 22, color: colors.onSurface },
  kpiHint: { fontFamily: font.regular, fontSize: 10, color: colors.muted, marginTop: 2 },
  syncStrip: {
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.sm,
    padding: spacing.md, marginBottom: spacing.md,
    borderWidth: 1, borderColor: colors.border,
  },
  syncStripLabel: { fontFamily: font.bold, fontSize: 10, color: colors.muted, letterSpacing: 0.5, marginBottom: 6 },
  syncChip: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: 8, paddingVertical: 3, borderRadius: 999,
    borderWidth: 1, backgroundColor: colors.surface,
  },
  syncDot: { width: 6, height: 6, borderRadius: 3 },
  syncChipText: { fontFamily: font.medium, fontSize: 10, color: colors.onSurface, textTransform: "capitalize" },
  cardsGrid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  card: {
    width: "48%", backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md, padding: spacing.lg,
    borderWidth: 1, borderColor: colors.border,
  },
  iconCircle: {
    width: 40, height: 40, borderRadius: 20,
    alignItems: "center", justifyContent: "center", marginBottom: 6,
  },
  cardLabel: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
});
