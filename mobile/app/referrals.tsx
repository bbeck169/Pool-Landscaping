/**
 * Referral Rewards — customer portal.
 * GET /api/referrals/me → code, stats, invites
 * GET /api/customer-portal/referrals/my → conversion history + summary
 */
import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity,
  ActivityIndicator, Share, Clipboard, Linking, RefreshControl,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useFocusEffect, useRouter } from "expo-router";

import { useAuth } from "@/src/auth";
import { api } from "@/src/api";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";

type ReferralMe = {
  referral_code: string;
  referral_link: string;
  share_qr_url?: string;
  reward_pct?: number;
  reward_description?: string;
  stats: {
    invites_sent: number;
    signups: number;
    converted: number;
    pending_review: number;
    credits_earned_pct: number;
    credits_available_months: number;
  };
  invites: any[];
};

type ReferralHistory = {
  referrals: any[];
  summary: { total_referrals: number; conversions: number; rewards_earned: number };
};

const TENANT_PHONE = "(602) 555-1234"; // fallback; actual comes from config

const referralStatusColor = (status: string) => {
  switch (status) {
    case "credited": return { bg: "#DCFCE7", fg: "#166534" };
    case "voided": return { bg: "#FEE2E2", fg: "#991B1B" };
    case "pending_paid_window": return { bg: "#DBEAFE", fg: "#1D4ED8" };
    case "converted": return { bg: "#DCFCE7", fg: "#166534" };
    default: return { bg: "#FEF3C7", fg: "#A16207" };
  }
};

export default function ReferralsScreen() {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { user } = useAuth();

  const [me, setMe] = useState<ReferralMe | null>(null);
  const [history, setHistory] = useState<ReferralHistory | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [copied, setCopied] = useState(false);
  const [tenantPhone, setTenantPhone] = useState(TENANT_PHONE);

  const load = useCallback(async () => {
    try {
      const [meRes, histRes] = await Promise.all([
        api.get("/referrals/me").catch(() => null),
        api.get("/customer-portal/referrals/my").catch(() => null),
      ]);
      if (meRes) setMe(meRes);
      if (histRes) setHistory(histRes);
      // Try to get tenant phone
      try {
        const cfg = await api.get("/config/public");
        if (cfg?.tenant_phone) setTenantPhone(cfg.tenant_phone);
      } catch {}
    } catch {} finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const copyCode = () => {
    if (!me?.referral_code) return;
    Clipboard.setString(me.referral_code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const shareCode = async () => {
    if (!me) return;
    try {
      await Share.share({
        message: `Hey — I use Pool & Landscaping of Vistancia for my pool/yard. Use my code ${me.referral_code} and we both get ${me.reward_description || "$55 credit"}. Book here: ${me.referral_link}`,
      });
    } catch {}
  };

  const role = String((user as any)?.role || "");
  if (role !== "customer") {
    return (
      <View style={[s.center, { paddingTop: insets.top + 60 }]} testID="referrals-role-gate">
        <Ionicons name="lock-closed" size={36} color={colors.muted} />
        <Text style={s.gateText}>Customer-only feature</Text>
        <TouchableOpacity onPress={() => router.replace("/(app)")} style={s.gateBtn}>
          <Text style={s.gateBtnText}>Go Home</Text>
        </TouchableOpacity>
      </View>
    );
  }

  if (loading) {
    return <View style={[s.center, { paddingTop: insets.top + 60 }]}><ActivityIndicator size="large" color={colors.brand} /></View>;
  }

  const stats = me?.stats;
  const summary = history?.summary;
  const referrals = history?.referrals || [];
  const totalEarned = summary?.rewards_earned || 0;

  return (
    <View style={[s.root, { paddingTop: insets.top }]}>
      <View style={s.navBar}>
        <TouchableOpacity onPress={() => router.back()} hitSlop={12}>
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </TouchableOpacity>
        <Text style={s.navTitle}>Refer & Earn</Text>
        <View style={{ width: 22 }} />
      </View>

      <ScrollView
        contentContainerStyle={s.scroll}
        showsVerticalScrollIndicator={false}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.brand} />}
      >
        {/* Code card */}
        <View style={s.codeCard} testID="referral-code-card">
          <Ionicons name="gift" size={32} color={colors.brand} />
          <Text style={s.codeLabel}>Your Referral Code</Text>
          <TouchableOpacity onPress={copyCode} style={s.codeBox} testID="referral-copy-code">
            <Text style={s.codeText}>{me?.referral_code || "—"}</Text>
            <Ionicons name={copied ? "checkmark-circle" : "copy"} size={20} color={copied ? colors.success : colors.brand} />
          </TouchableOpacity>
          {copied && <Text style={s.copiedToast}>Copied to clipboard!</Text>}
          <Text style={s.rewardDesc}>{me?.reward_description || "Earn $55 credit for each friend who signs up"}</Text>
        </View>

        {/* Share button */}
        <TouchableOpacity style={s.shareBtn} onPress={shareCode} testID="referral-share-btn">
          <Ionicons name="share-social" size={20} color="#fff" />
          <Text style={s.shareBtnText}>Share Your Code</Text>
        </TouchableOpacity>

        {/* Credits summary */}
        <View style={s.card} testID="referral-credits-card">
          <Text style={s.sectionLabel}>YOUR REWARDS</Text>
          <View style={s.creditsRow}>
            <View style={s.creditItem}>
              <Text style={s.creditAmount}>${totalEarned.toFixed(0)}</Text>
              <Text style={s.creditLabel}>Total Earned</Text>
            </View>
            <View style={s.creditDivider} />
            <View style={s.creditItem}>
              <Text style={s.creditAmount}>{stats?.credits_available_months || 0}</Text>
              <Text style={s.creditLabel}>Months Available</Text>
            </View>
            <View style={s.creditDivider} />
            <View style={s.creditItem}>
              <Text style={s.creditAmount}>{stats?.converted || 0}</Text>
              <Text style={s.creditLabel}>Conversions</Text>
            </View>
          </View>
          <View style={s.infoRow}>
            <Ionicons name="information-circle" size={14} color={colors.brand} />
            <Text style={s.infoText}>Credits are auto-applied to your next invoice.</Text>
          </View>
        </View>

        {/* Referral history */}
        <View style={s.card} testID="referral-history">
          <Text style={s.sectionLabel}>REFERRAL HISTORY</Text>
          {referrals.length === 0 ? (
            <View style={s.emptyWrap}>
              <Ionicons name="people-outline" size={28} color={colors.muted} />
              <Text style={s.emptyText}>No referrals yet — share your code above to earn credits.</Text>
            </View>
          ) : (
            referrals.map((r: any) => {
              const sc = referralStatusColor(r.status);
              const daysLeft = r.status === "pending_paid_window" && r.paid_window_ends_at
                ? Math.max(0, Math.ceil((new Date(r.paid_window_ends_at).getTime() - Date.now()) / 86400000))
                : null;
              return (
              <View key={r.id} style={s.historyRow} testID={`referral-row-${r.id}`}>
                <View style={{ flex: 1 }}>
                  <Text style={s.histName}>{r.friend_name || r.converted_customer_name || r.referee_name || "Friend"}</Text>
                  <Text style={s.histDate}>
                    {r.converted_at || r.created_at
                      ? new Date(r.converted_at || r.created_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })
                      : ""}
                  </Text>
                </View>
                <View style={[s.histPill, { backgroundColor: sc.bg }]}>
                  <Text style={[s.histPillText, { color: sc.fg }]}>
                    {r.status === "pending_paid_window" ? `Waiting${daysLeft != null ? ` ${daysLeft}d` : ""}` :
                     r.status === "credited" ? "Credited" :
                     r.status === "voided" ? "Voided" :
                     r.status === "converted" ? "Converted" : "Pending"}
                  </Text>
                </View>
              </View>
              );
            })
          )}
        </View>

        {/* Call Now CTA */}
        <TouchableOpacity
          style={s.callBtn}
          onPress={() => Linking.openURL(`tel:${tenantPhone}`)}
          testID="referral-call-now"
        >
          <Ionicons name="call" size={20} color="#fff" />
          <Text style={s.callBtnText}>Call Now</Text>
        </TouchableOpacity>
      </ScrollView>
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: "#F8FAFC" },
  center: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface, padding: 24 },
  gateText: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface, marginTop: 12 },
  gateBtn: { marginTop: 20, paddingHorizontal: 24, paddingVertical: 12, borderRadius: radius.md, backgroundColor: colors.brand },
  gateBtnText: { fontFamily: font.semibold, fontSize: fontSize.base, color: "#fff" },
  navBar: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.lg, paddingVertical: spacing.md, borderBottomWidth: 1, borderBottomColor: colors.border, backgroundColor: colors.surface },
  navTitle: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  scroll: { padding: spacing.lg, paddingBottom: 40 },
  codeCard: { backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.xl, alignItems: "center", borderWidth: 1, borderColor: colors.border, marginBottom: spacing.md },
  codeLabel: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.muted, marginTop: spacing.sm },
  codeBox: { flexDirection: "row", alignItems: "center", gap: 10, backgroundColor: "#F0F9FF", paddingHorizontal: 20, paddingVertical: 12, borderRadius: radius.md, marginTop: spacing.sm, borderWidth: 1, borderColor: "#BAE6FD" },
  codeText: { fontFamily: font.bold, fontSize: 24, color: colors.brand, letterSpacing: 3 },
  copiedToast: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.success, marginTop: 4 },
  rewardDesc: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, textAlign: "center", marginTop: spacing.sm },
  shareBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, backgroundColor: colors.brand, paddingVertical: 16, borderRadius: radius.md, marginBottom: spacing.md },
  shareBtnText: { fontFamily: font.bold, fontSize: fontSize.lg, color: "#fff" },
  card: { backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.lg, marginBottom: spacing.md, borderWidth: 1, borderColor: colors.border },
  sectionLabel: { fontFamily: font.bold, fontSize: 10, color: colors.muted, textTransform: "uppercase", letterSpacing: 1, marginBottom: spacing.sm },
  creditsRow: { flexDirection: "row", justifyContent: "space-around", paddingVertical: spacing.md },
  creditItem: { alignItems: "center" },
  creditAmount: { fontFamily: font.bold, fontSize: fontSize["2xl"], color: colors.brand },
  creditLabel: { fontFamily: font.regular, fontSize: 11, color: colors.muted, marginTop: 2 },
  creditDivider: { width: 1, backgroundColor: colors.border },
  infoRow: { flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: "#F0F9FF", padding: spacing.sm, borderRadius: radius.sm, marginTop: spacing.sm },
  infoText: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.brand, flex: 1 },
  emptyWrap: { alignItems: "center", paddingVertical: spacing.xl },
  emptyText: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, textAlign: "center", marginTop: 8 },
  historyRow: { flexDirection: "row", alignItems: "center", paddingVertical: spacing.sm, borderBottomWidth: 1, borderBottomColor: colors.border },
  histName: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  histDate: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
  histPill: { paddingHorizontal: 10, paddingVertical: 3, borderRadius: 999 },
  histConverted: { backgroundColor: "#DCFCE7" },
  histPending: { backgroundColor: "#FEF9C3" },
  histPillText: { fontFamily: font.bold, fontSize: 10, letterSpacing: 0.5 },
  callBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, backgroundColor: "#0F766E", paddingVertical: 16, borderRadius: radius.md, marginTop: spacing.sm },
  callBtnText: { fontFamily: font.bold, fontSize: fontSize.lg, color: "#fff" },
});
