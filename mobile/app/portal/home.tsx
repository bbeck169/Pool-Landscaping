import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, RefreshControl, Pressable,
  Linking, Dimensions,
} from "react-native";
import { Image } from "expo-image";
import { LinearGradient } from "expo-linear-gradient";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { colors, spacing, radius, font, fontSize, money, IMAGES } from "@/src/theme";
import { Loading, StatusChip } from "@/src/components/ui";
import { Header, NotificationBell } from "@/src/components/widgets";
import Tour, { TourStep } from "@/src/components/Tour";
import AsyncStorage from "@react-native-async-storage/async-storage";

const TOUR_KEY = "portal_tour_v2_done";
const TOUR_STEPS: TourStep[] = [
  { targetTestID: "portal-cta-call", title: "Call Us Anytime", body: "Tap here to instantly dial our office.", icon: "call" },
  { targetTestID: "portal-request-service-btn", title: "Request a Service", body: "Need a repair or one-off visit? Tell us here.", icon: "add-circle-outline" },
  { targetTestID: "portal-hero", title: "Your Dashboard", body: "Balance due, upcoming & completed jobs at a glance.", icon: "stats-chart-outline" },
  { targetTestID: "portal-card-services", title: "Service Records", body: "View all past and upcoming service visits.", icon: "clipboard-outline" },
  { targetTestID: "portal-card-photos", title: "Service Photos", body: "Browse photos taken during each visit.", icon: "images-outline" },
  { targetTestID: "portal-card-invoices", title: "Invoices & Billing", body: "View, pay, and download invoices.", icon: "receipt-outline" },
  { targetTestID: "portal-card-paymethod", title: "Payment Methods", body: "Manage your saved payment methods.", icon: "wallet-outline" },
  { targetTestID: "portal-card-messages", title: "AI Chat", body: "Ask questions and get instant answers.", icon: "chatbubble-outline" },
  { targetTestID: "portal-ai-section", title: "Concierge Service", body: "Our AI concierges are ready to help 24/7.", icon: "sparkles" },
  { targetTestID: "portal-referral-section", title: "Refer a Friend", body: "Earn $55 credit for every friend who signs up.", icon: "gift" },
  { targetTestID: "portal-card-profile", title: "Your Profile", body: "View and manage your account details.", icon: "person-outline" },
  { targetTestID: "portal-card-business", title: "Business Card", body: "Share our contact info or scan the QR code.", icon: "id-card-outline" },
];

const SCREEN_W = Dimensions.get("window").width;
const IS_NARROW = SCREEN_W < 480;

const QA_SECTIONS: { key: string; label: string; icon: any; route: string }[] = [
  { key: "services", label: "Service Records", icon: "clipboard-outline", route: "/portal/services" },
  { key: "service-reports", label: "Service Reports", icon: "document-text-outline", route: "/portal/service-reports" },
  { key: "appts", label: "Appointments", icon: "checkmark-done-outline", route: "/portal/appointments" },
  { key: "photos", label: "Photos", icon: "images-outline", route: "/portal/photos" },
  { key: "videos", label: "Videos", icon: "videocam-outline", route: "/portal/videos" },
  { key: "chats", label: "Chat Threads", icon: "chatbubbles-outline", route: "/portal/chats" },
  { key: "invoices", label: "Invoices", icon: "receipt-outline", route: "/portal/invoices" },
  { key: "estimates", label: "Estimates", icon: "document-text-outline", route: "/portal/estimates" },
  { key: "payments", label: "Payments", icon: "card-outline", route: "/portal/payments" },
  { key: "paymethod", label: "Payment Method", icon: "wallet-outline", route: "/portal/payment-method" },
  { key: "messages", label: "Messages (AI)", icon: "chatbubble-outline", route: "/portal/messages" },
  { key: "documents", label: "Documents", icon: "folder-open-outline", route: "/portal/documents" },
  { key: "profile", label: "My Profile", icon: "person-outline", route: "/portal/profile" },
];

export default function PortalHome() {
  const { user } = useAuth();
  const router = useRouter();
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [aiEmployees, setAiEmployees] = useState<any[]>([]);
  const [tenantPhone, setTenantPhone] = useState("(602) 887-4400");
  const [showTour, setShowTour] = useState(false);
  const [creditBalance, setCreditBalance] = useState(0);

  const load = useCallback(async () => {
    try {
      const [dashboard, aiRes, cfg, creditsRes] = await Promise.all([
        api.get("/dashboard"),
        api.get("/customer-portal/ai-employees").catch(() => ({ employees: [] })),
        api.get("/config/public").catch(() => ({})),
        api.get("/customer-portal/credits/balance").catch(() => ({ balance_cents: 0 })),
      ]);
      setData(dashboard);
      setAiEmployees(aiRes?.employees || aiRes || []);
      if (cfg?.tenant_phone) setTenantPhone(cfg.tenant_phone);
      setCreditBalance(((creditsRes?.balance_cents || 0) / 100));

      // Check if tour has been shown
      const tourDone = await AsyncStorage.getItem(TOUR_KEY).catch(() => null);
      if (!tourDone) setShowTour(true);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const badgeFor = (key: string) => {
    if (!data) return 0;
    if (key === "invoices") return data.unpaid_invoices || 0;
    if (key === "estimates") return data.pending_estimates || 0;
    if (key === "messages") return data.unread_messages || 0;
    return 0;
  };

  return (
    <View style={s.root}>
      <Header title="My Account" subtitle={`Hi, ${user?.name?.split(" ")[0] || ""}`} right={<NotificationBell />} />
      {loading || !data ? (
        <Loading testID="portal-home-loading" />
      ) : (
        <ScrollView
          testID="portal-home-scroll"
          contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
        >
          {/* 1. Top CTA Row: Call Now + Request Service */}
          <View
            testID="portal-cta-row"
            style={[s.ctaRow, { flexDirection: IS_NARROW ? "column" : "row" }]}
          >
            <Pressable
              testID="portal-cta-call"
              style={s.ctaCallBtn}
              onPress={() => Linking.openURL(`tel:${tenantPhone}`)}
            >
              <Ionicons name="call" size={18} color="#fff" />
              <Text style={s.ctaCallText}>Call Now</Text>
            </Pressable>
            <Pressable
              testID="portal-request-service-btn"
              style={s.ctaRequestBtn}
              onPress={() => router.push("/request-service" as any)}
            >
              <LinearGradient
                colors={["#0284C7", "#16A34A"]}
                start={{ x: 0, y: 0 }}
                end={{ x: 1, y: 0 }}
                style={s.ctaRequestGrad}
              >
                <Ionicons name="add-circle-outline" size={18} color="#fff" />
                <Text style={s.ctaRequestText}>Request Service</Text>
              </LinearGradient>
            </Pressable>
          </View>

          {/* 2. Welcome-back Hero Card */}
          <View style={s.hero} testID="portal-hero">
            <Image source={{ uri: IMAGES.dashboardHero }} style={StyleSheet.absoluteFill} contentFit="cover" />
            <LinearGradient colors={["rgba(0,60,95,0.55)", "rgba(26,43,60,0.92)"]} style={StyleSheet.absoluteFill} />
            <View style={s.heroInner}>
              <Text style={s.heroLabel}>Balance Due</Text>
              <Text style={s.heroValue} testID="portal-balance">{money(data.outstanding)}</Text>
              <View style={s.heroRow}>
                <View style={s.heroPill}>
                  <Ionicons name="flash" size={14} color="#fff" />
                  <Text style={s.heroPillText}>{data.active_jobs} upcoming</Text>
                </View>
                <View style={s.heroPill}>
                  <Ionicons name="checkmark-done" size={14} color="#fff" />
                  <Text style={s.heroPillText}>{data.completed_jobs} completed</Text>
                </View>
              </View>
            </View>
          </View>

          {/* 2b. Stat Circles Row — Balance Due, Past Due, Credit */}
          <View style={s.statsRow} testID="portal-stat-circles">
            <View style={s.statCircle}>
              <Text style={s.statValue} testID="portal-stat-balance">{money(data.outstanding || 0)}</Text>
              <Text style={s.statLabel}>Balance Due</Text>
            </View>
            <View style={[s.statCircle, (data.past_due || 0) > 0 && s.statCircleWarn]}>
              <Text style={[s.statValue, (data.past_due || 0) > 0 && { color: colors.error }]} testID="portal-stat-past-due">
                {money(data.past_due || 0)}
              </Text>
              <Text style={s.statLabel}>Past Due</Text>
            </View>
            <View style={[s.statCircle, creditBalance > 0 && s.statCircleCredit]}>
              <Text style={[s.statValue, creditBalance > 0 && { color: "#166534" }]} testID="portal-stat-credit">
                {money(creditBalance)}
              </Text>
              <Text style={s.statLabel}>Credit</Text>
            </View>
          </View>

          {/* 3. Next Service */}
          {data.next_service ? (
            <Pressable style={s.nextCard} onPress={() => router.push(`/job/${data.next_service.id}`)} testID="portal-next-service">
              <View style={s.nextIcon}>
                <Ionicons name="calendar" size={20} color={colors.brand} />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={s.nextLabel}>Next Service</Text>
                <Text style={s.nextTitle} numberOfLines={1}>{data.next_service.title}</Text>
                <Text style={s.nextMeta}>{(data.next_service.scheduled_date || "").slice(0, 10) || "To be scheduled"}</Text>
              </View>
              <StatusChip status={data.next_service.status} />
            </Pressable>
          ) : null}

          {/* 4. Quick Actions Grid */}
          <Text style={s.gridTitle}>Quick Actions</Text>
          <View style={s.grid}>
            {QA_SECTIONS.map((sec) => {
              const badge = badgeFor(sec.key);
              return (
                <Pressable key={sec.key} style={s.card} onPress={() => router.push(sec.route as any)} testID={`portal-card-${sec.key}`}>
                  {badge > 0 ? (
                    <View style={s.cardBadge}><Text style={s.cardBadgeText}>{badge}</Text></View>
                  ) : null}
                  <View style={s.cardIcon}>
                    <Ionicons name={sec.icon} size={22} color={colors.brand} />
                  </View>
                  <Text style={s.cardLabel}>{sec.label}</Text>
                </Pressable>
              );
            })}
          </View>

          {/* 5. Last Visit Card */}
          {data.last_visit ? (
            <Pressable
              style={s.lastVisitCard}
              testID="last-visit-card"
              onPress={() => data.last_visit.id && router.push(`/portal/service/${data.last_visit.id}` as any)}
            >
              <View style={s.lastVisitIcon}>
                <Ionicons name="time-outline" size={22} color={colors.brand} />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={s.lastVisitLabel}>Last Visit</Text>
                <Text style={s.lastVisitTitle} numberOfLines={1}>
                  {data.last_visit.title || "Recent service"}
                </Text>
                <Text style={s.lastVisitDate}>
                  {(data.last_visit.date || data.last_visit.scheduled_date || "").slice(0, 10)}
                </Text>
              </View>
              <Ionicons name="chevron-forward" size={18} color={colors.muted} />
            </Pressable>
          ) : null}

          {/* 6. Ask a Concierge — teal→emerald gradient */}
          {Array.isArray(aiEmployees) && aiEmployees.length > 0 ? (
            <LinearGradient
              colors={["#0891B2", "#0EA5E9", "#10B981"]}
              start={{ x: 0, y: 0 }}
              end={{ x: 1, y: 1 }}
              style={s.conciergeWrap}
              testID="portal-ai-section"
            >
              <View style={s.conciergeHeader}>
                <Ionicons name="sparkles" size={20} color="#fff" />
                <Text style={s.conciergeTitle}>ASK A CONCIERGE</Text>
              </View>
              <Text style={s.conciergeSubtitle}>
                Chat with one of our AI concierges — no wait, answers in seconds.
              </Text>
              {aiEmployees.map((emp: any) => (
                <Pressable
                  key={emp.id || emp.key}
                  testID={`portal-ai-${emp.key || emp.id}-card`}
                  style={s.conciergeCard}
                  onPress={() => router.push(`/ai-chat/${emp.id}` as any)}
                >
                  <View style={s.conciergeAvatar}>
                    <Text style={s.conciergeEmoji}>{emp.avatar || "🤖"}</Text>
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={s.conciergeName}>{emp.name}</Text>
                    <Text style={s.conciergeDesc} numberOfLines={2}>{emp.description || emp.tagline || ""}</Text>
                  </View>
                  <Ionicons name="chevron-forward" size={16} color="rgba(255,255,255,0.7)" />
                </Pressable>
              ))}
            </LinearGradient>
          ) : null}

          {/* 7. Refer a Friend — purple→magenta gradient */}
          <LinearGradient
            colors={["#7C3AED", "#A855F7", "#EC4899"]}
            start={{ x: 0, y: 0 }}
            end={{ x: 1, y: 1 }}
            style={s.referralWrap}
            testID="portal-referral-section"
          >
            <Ionicons name="gift" size={28} color="#fff" />
            <Text style={s.referralTitle}>Refer a Friend — earn $55 credit</Text>
            <Text style={s.referralBody}>
              You&apos;ll get $55 in credit after their first paid month.
            </Text>
            <Pressable
              style={s.referralBtn}
              onPress={() => router.push("/referrals" as any)}
              testID="portal-referral-cta"
            >
              <Text style={s.referralBtnText}>Send Referral</Text>
            </Pressable>
          </LinearGradient>

          {/* 8. Business Card */}
          <Pressable
            style={s.bizCard}
            onPress={() => router.push("/card" as any)}
            testID="portal-card-business"
          >
            <View style={s.bizCardIcon}>
              <Ionicons name="id-card-outline" size={22} color={colors.brand} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={s.bizCardLabel}>Business Card</Text>
              <Text style={s.bizCardSub}>Contact info, QR code & more</Text>
            </View>
            <Ionicons name="chevron-forward" size={18} color={colors.muted} />
          </Pressable>
        </ScrollView>
      )}

      <Tour
        steps={TOUR_STEPS}
        visible={showTour}
        onFinish={() => {
          setShowTour(false);
          AsyncStorage.setItem(TOUR_KEY, "1").catch(() => {});
        }}
      />
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },

  // CTA Row
  ctaRow: { gap: 12, marginBottom: spacing.lg },
  ctaCallBtn: {
    flex: 1,
    minHeight: 48,
    backgroundColor: "#0F766E",
    borderRadius: radius.md,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    paddingVertical: 12,
    paddingHorizontal: 16,
  },
  ctaCallText: { fontFamily: font.bold, fontSize: fontSize.base, color: "#fff" },
  ctaRequestBtn: { flex: 1, minHeight: 48, borderRadius: radius.md, overflow: "hidden" },
  ctaRequestGrad: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    paddingVertical: 12,
    paddingHorizontal: 16,
    borderRadius: radius.md,
  },
  ctaRequestText: { fontFamily: font.bold, fontSize: fontSize.base, color: "#fff" },

  // Hero
  hero: { height: 150, borderRadius: radius.lg, overflow: "hidden", marginBottom: spacing.md },

  // Stat Circles
  statsRow: { flexDirection: "row", gap: spacing.md, marginBottom: spacing.lg },
  statCircle: {
    flex: 1, alignItems: "center", justifyContent: "center",
    backgroundColor: colors.surface, borderRadius: radius.lg,
    paddingVertical: 14, borderWidth: 1, borderColor: colors.border,
  },
  statCircleWarn: { borderColor: colors.error, backgroundColor: "#FEF2F2" },
  statCircleCredit: { borderColor: "#22C55E", backgroundColor: "#F0FDF4" },
  statValue: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface },
  statLabel: { fontFamily: font.medium, fontSize: 11, color: colors.muted, marginTop: 2 },
  heroInner: { flex: 1, padding: spacing.lg, justifyContent: "flex-end" },
  heroLabel: { fontFamily: font.medium, fontSize: fontSize.base, color: "rgba(255,255,255,0.85)" },
  heroValue: { fontFamily: font.bold, fontSize: 34, color: "#fff", marginTop: 2 },
  heroRow: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.md },
  heroPill: { flexDirection: "row", alignItems: "center", gap: 5, backgroundColor: "rgba(255,255,255,0.18)", paddingHorizontal: 10, paddingVertical: 5, borderRadius: radius.pill },
  heroPillText: { fontFamily: font.medium, fontSize: fontSize.sm, color: "#fff" },

  // Next Service
  nextCard: {
    flexDirection: "row", alignItems: "center", gap: spacing.md,
    backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.md,
    borderWidth: 1, borderColor: colors.border, marginBottom: spacing.lg,
  },
  nextIcon: { width: 44, height: 44, borderRadius: radius.md, backgroundColor: colors.brandTertiary, alignItems: "center", justifyContent: "center" },
  nextLabel: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted },
  nextTitle: { fontFamily: font.semibold, fontSize: fontSize.lg, color: colors.onSurface },
  nextMeta: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 1 },

  // Quick Actions Grid
  gridTitle: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface, marginBottom: spacing.md },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.md, marginBottom: spacing.lg },
  card: {
    width: "47.5%", flexGrow: 1, backgroundColor: colors.surface,
    borderRadius: radius.lg, padding: spacing.lg, borderWidth: 1, borderColor: colors.border,
  },
  cardIcon: { width: 44, height: 44, borderRadius: radius.md, backgroundColor: colors.brandTertiary, alignItems: "center", justifyContent: "center", marginBottom: spacing.sm },
  cardLabel: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  cardBadge: { position: "absolute", top: spacing.md, right: spacing.md, minWidth: 22, height: 22, paddingHorizontal: 6, borderRadius: 11, backgroundColor: colors.error, alignItems: "center", justifyContent: "center" },
  cardBadgeText: { color: "#fff", fontFamily: font.bold, fontSize: fontSize.sm },

  // Last Visit
  lastVisitCard: {
    flexDirection: "row", alignItems: "center", gap: spacing.md,
    backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.md,
    borderWidth: 1, borderColor: colors.border, marginBottom: spacing.lg,
  },
  lastVisitIcon: { width: 44, height: 44, borderRadius: radius.md, backgroundColor: colors.brandTertiary, alignItems: "center", justifyContent: "center" },
  lastVisitLabel: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted },
  lastVisitTitle: { fontFamily: font.semibold, fontSize: fontSize.lg, color: colors.onSurface },
  lastVisitDate: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 1 },

  // Ask a Concierge
  conciergeWrap: {
    borderRadius: 24, padding: 18, marginBottom: spacing.lg,
    shadowColor: "#000", shadowOpacity: 0.15,
    shadowOffset: { width: 0, height: 6 }, shadowRadius: 12, elevation: 6,
  },
  conciergeHeader: { flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 4 },
  conciergeTitle: { fontFamily: font.bold, fontSize: fontSize.lg, color: "#fff", textTransform: "uppercase", letterSpacing: 1 },
  conciergeSubtitle: { fontFamily: font.regular, fontSize: fontSize.base, color: "rgba(255,255,255,0.92)", marginBottom: spacing.md, lineHeight: 20 },
  conciergeCard: {
    flexDirection: "row", alignItems: "center", gap: spacing.md,
    backgroundColor: "rgba(255,255,255,0.16)", borderWidth: 1,
    borderColor: "rgba(255,255,255,0.28)", borderRadius: radius.lg,
    padding: spacing.md, marginTop: spacing.sm,
  },
  conciergeAvatar: { width: 44, height: 44, borderRadius: 22, backgroundColor: "rgba(255,255,255,0.2)", alignItems: "center", justifyContent: "center" },
  conciergeEmoji: { fontSize: 22 },
  conciergeName: { fontFamily: font.bold, fontSize: fontSize.base, color: "#fff" },
  conciergeDesc: { fontFamily: font.regular, fontSize: fontSize.sm, color: "rgba(255,255,255,0.85)", marginTop: 2, lineHeight: 16 },

  // Refer a Friend
  referralWrap: {
    borderRadius: 24, padding: 20, marginBottom: spacing.lg,
    shadowColor: "#000", shadowOpacity: 0.15,
    shadowOffset: { width: 0, height: 6 }, shadowRadius: 12, elevation: 6,
    alignItems: "center",
  },
  referralTitle: { fontFamily: font.bold, fontSize: fontSize.xl, color: "#fff", marginTop: spacing.sm, textAlign: "center" },
  referralBody: { fontFamily: font.regular, fontSize: fontSize.base, color: "rgba(255,255,255,0.92)", marginTop: spacing.xs, textAlign: "center", lineHeight: 20 },
  referralBtn: {
    backgroundColor: "#fff", borderRadius: radius.pill, paddingHorizontal: 28, paddingVertical: 12, marginTop: spacing.md,
  },
  referralBtnText: { fontFamily: font.bold, fontSize: fontSize.base, color: "#7C3AED" },

  // Business Card
  bizCard: {
    flexDirection: "row", alignItems: "center", gap: spacing.md,
    backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.md,
    borderWidth: 1, borderColor: colors.border, marginBottom: spacing.md,
  },
  bizCardIcon: { width: 44, height: 44, borderRadius: radius.md, backgroundColor: colors.brandTertiary, alignItems: "center", justifyContent: "center" },
  bizCardLabel: { fontFamily: font.semibold, fontSize: fontSize.lg, color: colors.onSurface },
  bizCardSub: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 1 },
});
