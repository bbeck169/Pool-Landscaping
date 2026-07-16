/**
 * Phase 47 · Mobile — Budget Health card.
 *
 * Read-only admin widget for the mobile home screen. Consumes
 * `GET /api/budgets/health-summary`. Renders "this week revenue vs
 * target" + a pace pill (green/yellow/red). Silent when the user is
 * not an admin/super_admin.
 */
import React, { useEffect, useState } from "react";
import { View, Text, StyleSheet, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { useAuth } from "@/src/auth";
import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";

const PACE_LABELS: Record<string, string> = {
  on_track: "On track",
  ahead: "Ahead",
  behind: "Behind",
  no_target: "No target set",
};
const PACE_COLORS: Record<string, { bg: string; fg: string }> = {
  on_track: { bg: "#DCFCE7", fg: "#166534" },
  ahead: { bg: "#DBEAFE", fg: "#1E40AF" },
  behind: { bg: "#FEE2E2", fg: "#B91C1C" },
  no_target: { bg: colors.surfaceSecondary, fg: colors.muted },
};

function money(cents?: number | null): string {
  const v = ((cents as number) || 0) / 100;
  return v.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 0 });
}

export default function BudgetHealthCard() {
  const { user } = useAuth();
  const router = useRouter();
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const isAdmin = user?.role === "admin" || user?.role === "super_admin";

  useEffect(() => {
    if (!isAdmin) return;
    let alive = true;
    (async () => {
      setLoading(true);
      try {
        const r = await api.get("/budgets/health-summary");
        if (alive) setData(r);
      } catch { /* silent — card just hides on error */ }
      finally { if (alive) setLoading(false); }
    })();
    return () => { alive = false; };
  }, [isAdmin]);

  if (!isAdmin) return null;
  if (loading && !data) return null;
  if (!data) return null;

  const pace = data.pace || "no_target";
  const paceStyle = PACE_COLORS[pace] || PACE_COLORS.no_target;

  const monthPct = data?.this_month?.target_cents
    ? Math.min(200, Math.round((data.this_month.actual_cents / data.this_month.target_cents) * 100))
    : 0;

  return (
    <Pressable
      onPress={() => router.push("/(app)/index" as any)}
      style={styles.card}
      testID="admin-budget-health-card"
    >
      <View style={styles.header}>
        <Ionicons name="pulse-outline" size={16} color={colors.brand} />
        <Text style={styles.title}>Budget Health · {data.year}</Text>
        <View style={[styles.pacePill, { backgroundColor: paceStyle.bg }]}>
          <Text style={[styles.pacePillText, { color: paceStyle.fg }]}
                testID="admin-budget-health-pace">{PACE_LABELS[pace]}</Text>
        </View>
      </View>

      <View style={styles.row}>
        <View style={styles.col}>
          <Text style={styles.label}>This month</Text>
          <Text style={styles.value} testID="admin-budget-health-this-month">
            {money(data.this_month?.actual_cents)}
          </Text>
          <Text style={styles.sub}>
            of {money(data.this_month?.target_cents)} · {monthPct}%
          </Text>
        </View>
        <View style={styles.col}>
          <Text style={styles.label}>YTD</Text>
          <Text style={styles.value} testID="admin-budget-health-ytd">
            {money(data.ytd?.actual_cents)}
          </Text>
          <Text style={styles.sub}>
            of {money(data.ytd?.target_cents)}
          </Text>
        </View>
      </View>

      {!data.has_budget ? (
        <Text style={styles.warn} testID="admin-budget-health-no-budget">
          No budget set for {data.year}. Set one from the web console.
        </Text>
      ) : null}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.surface, borderRadius: radius.lg,
    padding: spacing.md, borderWidth: 1, borderColor: colors.border,
    marginBottom: spacing.md,
  },
  header: { flexDirection: "row", alignItems: "center", gap: 6, marginBottom: spacing.sm },
  title: { flex: 1, fontFamily: font.bold, fontSize: fontSize.sm, color: colors.onSurface },
  pacePill: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 999 },
  pacePillText: { fontFamily: font.bold, fontSize: 10, letterSpacing: 0.5, textTransform: "uppercase" },
  row: { flexDirection: "row", gap: spacing.md },
  col: { flex: 1 },
  label: { fontFamily: font.semibold, fontSize: 10, color: colors.muted, textTransform: "uppercase", letterSpacing: 0.5 },
  value: { fontFamily: font.bold, fontSize: 20, color: colors.onSurface, marginTop: 2 },
  sub: { fontFamily: font.regular, fontSize: 11, color: colors.muted, marginTop: 2 },
  warn: {
    marginTop: spacing.sm, backgroundColor: "#FEF9C3",
    borderColor: "#FDE68A", borderWidth: 1, borderRadius: radius.sm,
    padding: 8, color: "#854D0E", fontSize: 11, fontFamily: font.semibold,
  },
});
