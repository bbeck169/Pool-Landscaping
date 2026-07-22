/**
 * Marketing Analytics — admin only.
 * GET /api/marketing/analytics/overview
 * GET /api/marketing/campaigns (recent campaigns with stats)
 */
import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity,
  ActivityIndicator, RefreshControl,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useFocusEffect, useRouter } from "expo-router";

import { useAuth } from "@/src/auth";
import { api } from "@/src/api";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";

type Analytics = {
  window: string;
  campaigns: { total: number; sent: number; active: number };
  totals: { sends: number; opens: number; clicks: number; replies: number; unsubscribes: number; bounces: number };
  rates: { open_rate: number; click_rate: number; reply_rate: number; unsubscribe_rate: number; bounce_rate: number };
};

type Campaign = { id: string; name?: string; subject?: string; channel?: string; status?: string; sent_count?: number; open_count?: number; click_count?: number; created_at?: string };

const pct = (n: number) => `${(n * 100).toFixed(1)}%`;

export default function AnalyticsScreen() {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { user } = useAuth();
  const role = String((user as any)?.role || "");
  const allowed = role === "admin" || role === "super_admin";

  const [data, setData] = useState<Analytics | null>(null);
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    if (!allowed) { setLoading(false); return; }
    try {
      const [an, camp] = await Promise.all([
        api.get("/marketing/analytics/overview").catch(() => null),
        api.get("/marketing/campaigns").catch(() => []),
      ]);
      if (an) setData(an);
      const clist = Array.isArray(camp) ? camp : camp?.campaigns || camp?.items || [];
      setCampaigns(clist.slice(0, 10));
    } catch {} finally { setLoading(false); setRefreshing(false); }
  }, [allowed]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  if (!allowed) {
    return (
      <View style={[s.center, { paddingTop: insets.top + 60 }]} testID="analytics-role-gate">
        <Ionicons name="lock-closed" size={36} color={colors.muted} />
        <Text style={s.gateText}>Not authorized</Text>
        <TouchableOpacity onPress={() => router.replace("/(app)")} style={s.gateBtn}><Text style={s.gateBtnText}>Go Home</Text></TouchableOpacity>
      </View>
    );
  }

  if (loading) return <View style={[s.center, { paddingTop: insets.top + 60 }]}><ActivityIndicator size="large" color={colors.brand} /></View>;

  const rates = data?.rates;
  const totals = data?.totals;

  return (
    <View style={[s.root, { paddingTop: insets.top }]}>
      <View style={s.navBar}>
        <TouchableOpacity onPress={() => router.back()} hitSlop={12}><Ionicons name="arrow-back" size={22} color={colors.onSurface} /></TouchableOpacity>
        <Text style={s.navTitle}>Analytics</Text>
        <View style={{ width: 22 }} />
      </View>
      <ScrollView
        contentContainerStyle={s.scroll}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.brand} />}
      >
        {/* KPI cards */}
        <View style={s.kpiGrid} testID="analytics-kpis">
          <KPICard label="Sends" value={String(totals?.sends || 0)} icon="send" color="#0F766E" />
          <KPICard label="Open Rate" value={pct(rates?.open_rate || 0)} icon="mail-open" color="#0369A1" />
          <KPICard label="Click Rate" value={pct(rates?.click_rate || 0)} icon="hand-left" color="#7E22CE" />
          <KPICard label="Reply Rate" value={pct(rates?.reply_rate || 0)} icon="chatbubble" color="#0E7490" />
          <KPICard label="Unsub Rate" value={pct(rates?.unsubscribe_rate || 0)} icon="remove-circle" color="#C2410C" />
          <KPICard label="Bounce Rate" value={pct(rates?.bounce_rate || 0)} icon="alert-circle" color="#B91C1C" />
        </View>

        {/* Campaign summary */}
        <View style={s.card} testID="analytics-campaign-summary">
          <Text style={s.sectionLabel}>CAMPAIGN SUMMARY ({data?.window || "30d"})</Text>
          <View style={s.summRow}>
            <Text style={s.summLabel}>Total Campaigns</Text>
            <Text style={s.summValue}>{data?.campaigns?.total || 0}</Text>
          </View>
          <View style={s.summRow}>
            <Text style={s.summLabel}>Sent</Text>
            <Text style={s.summValue}>{data?.campaigns?.sent || 0}</Text>
          </View>
          <View style={s.summRow}>
            <Text style={s.summLabel}>Active</Text>
            <Text style={s.summValue}>{data?.campaigns?.active || 0}</Text>
          </View>
        </View>

        {/* Recent campaigns */}
        <Text style={s.sectionHeader}>Recent Campaigns</Text>
        {campaigns.length === 0 ? (
          <View style={s.emptyWrap}><Ionicons name="megaphone-outline" size={28} color={colors.muted} /><Text style={s.emptyText}>No campaigns yet</Text></View>
        ) : (
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.campScroll}>
            {campaigns.map((c) => (
              <View key={c.id} style={s.campCard} testID={`camp-${c.id}`}>
                <Text style={s.campName} numberOfLines={2}>{c.name || c.subject || "Untitled"}</Text>
                <View style={s.campMeta}>
                  <Text style={s.campStat}>Sent: {c.sent_count || 0}</Text>
                  <Text style={s.campStat}>Opens: {c.open_count || 0}</Text>
                  <Text style={s.campStat}>Clicks: {c.click_count || 0}</Text>
                </View>
                <View style={[s.campChPill, { backgroundColor: c.channel === "sms" ? "#E0F2FE" : "#F3E8FF" }]}>
                  <Text style={[s.campChText, { color: c.channel === "sms" ? "#0369A1" : "#7E22CE" }]}>{(c.channel || "email").toUpperCase()}</Text>
                </View>
              </View>
            ))}
          </ScrollView>
        )}
      </ScrollView>
    </View>
  );
}

function KPICard({ label, value, icon, color }: { label: string; value: string; icon: any; color: string }) {
  return (
    <View style={s.kpiCard}>
      <Ionicons name={icon} size={18} color={color} />
      <Text style={[s.kpiValue, { color }]}>{value}</Text>
      <Text style={s.kpiLabel}>{label}</Text>
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: "#F8FAFC" },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 24 },
  gateText: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface, marginTop: 12 },
  gateBtn: { marginTop: 20, paddingHorizontal: 24, paddingVertical: 12, borderRadius: radius.md, backgroundColor: colors.brand },
  gateBtnText: { fontFamily: font.semibold, fontSize: fontSize.base, color: "#fff" },
  navBar: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.lg, paddingVertical: spacing.md, borderBottomWidth: 1, borderBottomColor: colors.border, backgroundColor: colors.surface },
  navTitle: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  scroll: { padding: spacing.lg, paddingBottom: 40 },
  kpiGrid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm, marginBottom: spacing.md },
  kpiCard: { width: "48%", backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: colors.border, alignItems: "center", flexGrow: 1, minWidth: 140 },
  kpiValue: { fontFamily: font.bold, fontSize: fontSize.xl, marginTop: 4 },
  kpiLabel: { fontFamily: font.regular, fontSize: 11, color: colors.muted, marginTop: 2 },
  card: { backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.lg, marginBottom: spacing.md, borderWidth: 1, borderColor: colors.border },
  sectionLabel: { fontFamily: font.bold, fontSize: 10, color: colors.muted, textTransform: "uppercase", letterSpacing: 1, marginBottom: spacing.sm },
  summRow: { flexDirection: "row", justifyContent: "space-between", paddingVertical: 6 },
  summLabel: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted },
  summValue: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  sectionHeader: { fontFamily: font.bold, fontSize: fontSize.base, color: colors.onSurface, marginBottom: spacing.sm },
  campScroll: { gap: spacing.sm, paddingBottom: spacing.md },
  campCard: { width: 200, backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: colors.border },
  campName: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface, marginBottom: 6 },
  campMeta: { gap: 2 },
  campStat: { fontFamily: font.regular, fontSize: 11, color: colors.muted },
  campChPill: { paddingHorizontal: 8, paddingVertical: 2, borderRadius: 999, alignSelf: "flex-start", marginTop: spacing.sm },
  campChText: { fontFamily: font.bold, fontSize: 9, letterSpacing: 0.5 },
  emptyWrap: { alignItems: "center", paddingVertical: spacing.xl },
  emptyText: { fontFamily: font.medium, fontSize: fontSize.base, color: colors.muted, marginTop: 8 },
});
