/**
 * Phase 39B · mobile port of web `dashboard/DashboardActionCards.jsx`.
 * GET /dashboard/action-cards on mount + every 60 s. 7 cards; each
 * hides at count 0 except Intelligence Alerts (alwaysShow). Parent
 * mounts for admin / super_admin / manager (backend 403s others).
 * Web-only targets (Intelligence alerts) route to `/web-only`.
 */
import React, { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font } from "@/src/theme";

const POLL_MS = 60_000;
const alerts = (category?: string) => ({
  pathname: "/web-only",
  params: { title: "Intelligence Alerts", webPath: `/admin/intelligence/alerts${category ? `?category=${category}` : ""}` },
});

export const ACTION_CARDS: { key: string; label: string; icon: any; accent: string; href: any; alwaysShow?: boolean }[] = [
  { key: "today_routes", label: "Today's Routes", icon: "bus-outline", accent: "#0284C7", href: "/(app)/dispatch/board" },
  { key: "pending_checkins", label: "Approve Check-ins", icon: "clipboard-outline", accent: "#0EA5E9", href: "/checkins" },
  { key: "unpaid_invoices", label: "Unpaid Invoices", icon: "cash-outline", accent: "#F59E0B", href: { pathname: "/invoices", params: { status: "unpaid" } } },
  { key: "overdue_invoices", label: "Overdue Invoices", icon: "alert-circle-outline", accent: "#DC2626", href: { pathname: "/invoices", params: { status: "overdue" } } },
  { key: "new_leads_today", label: "New Leads Today", icon: "people-outline", accent: "#7C3AED", href: { pathname: "/leads", params: { filter: "today" } } },
  { key: "open_alerts", label: "Open Intelligence Alerts", icon: "notifications-outline", accent: "#0284C7", href: alerts(), alwaysShow: true },
  { key: "missed_services_today", label: "Missed Services Today", icon: "warning-outline", accent: "#DC2626", href: alerts("missed_service") },
];

export default function DashboardActionCards() {
  const router = useRouter();
  const [counts, setCounts] = useState<Record<string, number> | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      setCounts((await api.get("/dashboard/action-cards")) || {});
      setError("");
    } catch (e: any) {
      setError(e?.message || "Failed to load dashboard summary");
    }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, POLL_MS);
    return () => clearInterval(t);
  }, [load]);

  if (counts === null && !error) {
    return (
      <View style={s.grid} testID="dashboard-action-cards-skeleton">
        {ACTION_CARDS.map((c) => <View key={c.key} style={[s.card, s.skeleton]} />)}
      </View>
    );
  }

  const visible = ACTION_CARDS.filter((c) => c.alwaysShow || Number(counts?.[c.key] || 0) > 0);
  if (!visible.length) return null;

  return (
    <View style={s.grid} testID="dashboard-action-cards">
      {visible.map((c) => (
        <Pressable
          key={c.key}
          onPress={() => router.push(c.href)}
          style={({ pressed }) => [s.card, { borderLeftColor: c.accent }, pressed && { opacity: 0.85 }]}
          testID={`dashboard-action-card-${c.key}`}
          accessibilityRole="button"
        >
          <View style={s.top}>
            <Ionicons name={c.icon} size={14} color={c.accent} />
            <Text style={s.count} testID={`dashboard-action-card-${c.key}-count`}>{Number(counts?.[c.key] || 0)}</Text>
          </View>
          <Text style={s.label} numberOfLines={2}>{c.label}</Text>
        </Pressable>
      ))}
    </View>
  );
}

const s = StyleSheet.create({
  grid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm, marginBottom: spacing.lg },
  card: {
    width: "48%", flexGrow: 1, minHeight: 72, padding: spacing.md, backgroundColor: colors.surface,
    borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, borderLeftWidth: 4,
  },
  skeleton: { backgroundColor: colors.surfaceSecondary, borderLeftColor: colors.border },
  top: { flexDirection: "row", alignItems: "center", gap: 6, marginBottom: 4 },
  count: { fontFamily: font.bold, fontSize: 13, color: colors.muted, letterSpacing: 0.5 },
  label: { fontFamily: font.medium, fontSize: 12, color: colors.onSurface, lineHeight: 16 },
});
