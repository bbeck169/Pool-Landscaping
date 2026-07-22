/**
 * Marketing Analytics — admin only.
 * GET /api/marketing/analytics/overview → { window, campaigns, sequences, review_requests, top_sequences, top_campaigns, trend }
 * GET /api/marketing/campaigns → recent campaigns list
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

type AnalyticsOverview = {
  window: string;
  campaigns: {
    total_sent: number;
    active: number;
    delivered: number;
    opened: number;
    clicked: number;
    converted: number;
  };
  sequences: {
    total_enrolments: number;
    active: number;
    completed: number;
    halted: number;
    avg_completion_hours: number;
  };
  review_requests: {
    total: number;
    sent: number;
    opened: number;
    reviewed: number;
    expired: number;
    failed: number;
    review_rate_pct: number;
    avg_rating: number | null;
  };
  top_sequences?: any[];
  top_campaigns?: any[];
};

type Campaign = {
  id: string;
  name?: string;
  subject?: string;
  channel?: string;
  status?: string;
  sent_count?: number;
  open_count?: number;
  click_count?: number;
  created_at?: string;
};

export default function AnalyticsScreen() {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { user } = useAuth();
  const role = String((user as any)?.role || "");
  const allowed = role === "admin" || role === "super_admin";

  const [data, setData] = useState<AnalyticsOverview | null>(null);
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
        <TouchableOpacity onPress={() => router.replace("/(app)")} style={s.gateBtn}>
          <Text style={s.gateBtnText}>Go Home</Text>
        </TouchableOpacity>
      </View>
    );
  }

  if (loading) {
    return (
      <View style={[s.center, { paddingTop: insets.top + 60 }]}>
        <ActivityIndicator size="large" color={colors.brand} />
      </View>
    );
  }

  const camp = data?.campaigns;
  const seq = data?.sequences;
  const rev = data?.review_requests;

  return (
    <View style={[s.root, { paddingTop: insets.top }]}>
      <View style={s.navBar}>
        <TouchableOpacity onPress={() => router.back()} hitSlop={12}>
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </TouchableOpacity>
        <Text style={s.navTitle}>Analytics</Text>
        <View style={{ width: 22 }} />
      </View>

      <ScrollView
        contentContainerStyle={s.scroll}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={() => { setRefreshing(true); load(); }}
            tintColor={colors.brand}
          />
        }
      >
        {/* Campaign KPIs */}
        <Text style={s.sectionLabel}>CAMPAIGNS ({data?.window || "30d"})</Text>
        <View style={s.kpiGrid} testID="analytics-campaign-kpis">
          <KPICard label="Total Sent" value={String(camp?.total_sent || 0)} icon="send" color="#0F766E" />
          <KPICard label="Active" value={String(camp?.active || 0)} icon="flash" color="#0369A1" />
          <KPICard label="Delivered" value={String(camp?.delivered || 0)} icon="checkmark-circle" color="#166534" />
          <KPICard label="Opened" value={String(camp?.opened || 0)} icon="mail-open" color="#7E22CE" />
          <KPICard label="Clicked" value={String(camp?.clicked || 0)} icon="hand-left" color="#0E7490" />
          <KPICard label="Converted" value={String(camp?.converted || 0)} icon="trophy" color="#B45309" />
        </View>

        {/* Sequences Summary */}
        <View style={s.card} testID="analytics-sequences-summary">
          <Text style={s.cardSectionLabel}>SEQUENCES</Text>
          <View style={s.summRow}>
            <Text style={s.summLabel}>Total Enrolments</Text>
            <Text style={s.summValue}>{seq?.total_enrolments || 0}</Text>
          </View>
          <View style={s.summRow}>
            <Text style={s.summLabel}>Active</Text>
            <Text style={s.summValue}>{seq?.active || 0}</Text>
          </View>
          <View style={s.summRow}>
            <Text style={s.summLabel}>Completed</Text>
            <Text style={s.summValue}>{seq?.completed || 0}</Text>
          </View>
          <View style={s.summRow}>
            <Text style={s.summLabel}>Halted</Text>
            <Text style={s.summValue}>{seq?.halted || 0}</Text>
          </View>
        </View>

        {/* Review Requests Summary */}
        <View style={s.card} testID="analytics-reviews-summary">
          <Text style={s.cardSectionLabel}>REVIEW REQUESTS</Text>
          <View style={s.summRow}>
            <Text style={s.summLabel}>Total</Text>
            <Text style={s.summValue}>{rev?.total || 0}</Text>
          </View>
          <View style={s.summRow}>
            <Text style={s.summLabel}>Sent</Text>
            <Text style={s.summValue}>{rev?.sent || 0}</Text>
          </View>
          <View style={s.summRow}>
            <Text style={s.summLabel}>Opened</Text>
            <Text style={s.summValue}>{rev?.opened || 0}</Text>
          </View>
          <View style={s.summRow}>
            <Text style={s.summLabel}>Reviewed</Text>
            <Text style={s.summValue}>{rev?.reviewed || 0}</Text>
          </View>
          <View style={s.summRow}>
            <Text style={s.summLabel}>Review Rate</Text>
            <Text style={s.summValue}>{(rev?.review_rate_pct || 0).toFixed(1)}%</Text>
          </View>
          {rev?.avg_rating != null && (
            <View style={s.summRow}>
              <Text style={s.summLabel}>Avg Rating</Text>
              <Text style={s.summValue}>{rev.avg_rating.toFixed(1)} ★</Text>
            </View>
          )}
        </View>

        {/* Top Sequences */}
        {data?.top_sequences && data.top_sequences.length > 0 && (
          <>
            <Text style={s.sectionHeader}>Top Sequences</Text>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.campScroll}>
              {data.top_sequences.slice(0, 8).map((ts: any) => (
                <View key={ts.id} style={s.campCard} testID={`top-seq-${ts.id}`}>
                  <Text style={s.campName} numberOfLines={2}>{ts.name || "Untitled"}</Text>
                  <View style={s.campMeta}>
                    <Text style={s.campStat}>Enrolments: {ts.enrolments || 0}</Text>
                    <Text style={s.campStat}>Completed: {ts.completed || 0}</Text>
                  </View>
                </View>
              ))}
            </ScrollView>
          </>
        )}

        {/* Recent Campaigns */}
        <Text style={s.sectionHeader}>Recent Campaigns</Text>
        {campaigns.length === 0 ? (
          <View style={s.emptyWrap}>
            <Ionicons name="megaphone-outline" size={28} color={colors.muted} />
            <Text style={s.emptyText}>No campaigns yet</Text>
          </View>
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
                  <Text style={[s.campChText, { color: c.channel === "sms" ? "#0369A1" : "#7E22CE" }]}>
                    {(c.channel || "email").toUpperCase()}
                  </Text>
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
  sectionLabel: { fontFamily: font.bold, fontSize: 10, color: colors.muted, textTransform: "uppercase", letterSpacing: 1, marginBottom: spacing.sm },
  kpiGrid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm, marginBottom: spacing.md },
  kpiCard: { width: "48%", backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: colors.border, alignItems: "center", flexGrow: 1, minWidth: 140 },
  kpiValue: { fontFamily: font.bold, fontSize: fontSize.xl, marginTop: 4 },
  kpiLabel: { fontFamily: font.regular, fontSize: 11, color: colors.muted, marginTop: 2 },
  card: { backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.lg, marginBottom: spacing.md, borderWidth: 1, borderColor: colors.border },
  cardSectionLabel: { fontFamily: font.bold, fontSize: 10, color: colors.muted, textTransform: "uppercase", letterSpacing: 1, marginBottom: spacing.sm },
  summRow: { flexDirection: "row", justifyContent: "space-between", paddingVertical: 6 },
  summLabel: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted },
  summValue: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  sectionHeader: { fontFamily: font.bold, fontSize: fontSize.base, color: colors.onSurface, marginBottom: spacing.sm, marginTop: spacing.sm },
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
