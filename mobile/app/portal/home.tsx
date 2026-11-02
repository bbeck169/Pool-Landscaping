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
// Phase 30 · Feb-2026 — shared mobile TechAvatar for tech chips.
import TechAvatar from "@/components/common/TechAvatar";
// Phase 30.1 · Feb-2026 — swap hand-rolled concierge avatar for the
// shared PersonaAvatar (bundled JPEG w/ emoji fallback) so Billy /
// Skedra render consistently with the admin persona list.
import { PersonaAvatar } from "@/src/components/personas/PersonaAvatar";
// Phase K24 — payment-method prompt modal on portal home.
import PaymentMethodPromptModal from "@/src/components/portal/PaymentMethodPromptModal";

// Phase 25 · web parity 3a738ff11 (Phase 24) — dynamic stat-tile bgs.
// Past Due > 0 → dark red, Credit > 0 → dark green; label + value flip
// to white for contrast. Zero / null keeps the default tile chassis.
const PAST_DUE_BG = "#7F1D1D";
const CREDIT_BG = "#064E3B";
// Phase 25 · web parity e2a0d8a2e (Phase 23) — section accents on the
// shared stat-tile chassis: Concierge = brand blue, Referral = success
// green, Business card = navy variant (web PORTAL_HERO_ACCENT).
const NAVY_ACCENT_BG = "#1E3A8A";
const NAVY_ACCENT_FG = "#DBEAFE";
// Phase 25 (re-issue) · web parity e2a0d8a2e (Phase 23) — dark navy
// portal-home chassis, hex values verbatim from web. Page + tiles share
// #03002e; tiles separate via the #1E293B hairline + rounded-xl (12).
const PORTAL_DARK_BG = "#03002e";
const PORTAL_DARK_BORDER = "#1E293B";
const PORTAL_TILE_RADIUS = 12;
const PORTAL_TEXT = "#FFFFFF";
const PORTAL_TEXT_MUTED = "rgba(255,255,255,0.7)";
// Phase 24 glow → static soft white halo on every KPI tile (no hover on
// touch). iOS reads shadow*, Android draws via elevation.
// My Account tiles restyle (Nov-2026, operator ask, mobile-only): the KPI
// stat tiles + Quick Action tiles leave the navy chassis for the light
// in-palette card. Same "white card on the navy portal page" pattern as the
// TD-68 portal screens (PortalPageShell). Page bg + section cards
// (Next Service Day / Last Visit / Concierge / Referral / Business card)
// keep the navy chassis. Aliases of existing theme tokens, not new tokens.
const TILE_BG = colors.surface;                       // #FFFFFF
const TILE_BORDER = colors.border;                    // #E4E4E7
const TILE_TEXT = colors.onSurface;                   // #09090B · 19.9:1 on white
const TILE_TEXT_MUTED = colors.onSurfaceSecondary;    // #52525B · 7.7:1 on white
// Quick Action labels stay on one line; shrink no further than 85% (13 → ~11pt).
export const QA_LABEL_MIN_FONT_SCALE = 0.85;
const KPI_GLOW = {
  shadowColor: "#FFFFFF", shadowOpacity: 0.6, shadowRadius: 20,
  shadowOffset: { width: 0, height: 0 }, elevation: 8,
} as const;

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
  { key: "warranties", label: "Warranties", icon: "shield-checkmark-outline", route: "/portal/warranties" },
  { key: "profile", label: "My Profile", icon: "person-outline", route: "/portal/profile" },
];

export default function PortalHome() {
  const { user, logout } = useAuth();
  const router = useRouter();

  // Phase 30.3 final fix · Feb-2026 — customer portal sign-out.
  //
  // Diagnostic history (kept as a breadcrumb for the next fork):
  //   * Attempt 1 wrapped ``logout()`` in ``Alert.alert(..., destructive)``.
  //     On Android/Expo Go the Alert never rendered → the destructive
  //     onPress callback never fired → tap looked dead.
  //   * Attempts 2 + 3 layered on ``router.replace`` and flex/hitSlop
  //     tweaks. Still nothing, for the same reason — the tap arrived
  //     at Alert, and Alert silently no-op'd on the user's build.
  //   * Phase 30.3-diag / diag2 dual-probe (yellow + orange
  //     visual-state buttons) proved taps ARE reaching JS and state
  //     DOES flush — Alert.alert was the only silent link.
  //
  // The fix: mirror the two proven-working sign-outs in this repo
  //   * ``mobile/app/(app)/more.tsx`` (tech drawer)
  //   * ``mobile/app/portal/profile.tsx`` (portal Profile page)
  // Both call ``onPress={logout}`` directly with no confirmation
  // dialog. We layer a try/catch + belt-and-suspenders
  // ``router.replace("/login")`` after so navigation happens
  // regardless of layout-gate timing.
  const handleSignOut = React.useCallback(async () => {
    try {
      if (__DEV__) console.log("[portal sign-out] pressed");
      await logout();
      if (__DEV__) console.log("[portal sign-out] logout ok, navigating");
      router.replace("/login");
    } catch (e) {
      if (__DEV__) console.error("[portal sign-out] failed", e);
    }
  }, [logout, router]);

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
    <View style={s.root} testID="portal-home-root">
      <Header
        title="My Account"
        subtitle={`Hi, ${user?.name?.split(" ")[0] || ""}`}
        right={(
          // Phase 30.3 final · header right-slot cluster — bell + sign-out.
          // Kept as a compact horizontal row so the header's fixed
          // right area holds both affordances without pushing the
          // title. NO confirmation dialog — mirrors the proven
          // Profile-page sign-out; Alert.alert is the exact primitive
          // that failed silently on the user's Android/Expo Go build.
          <View style={s.headerActions}>
            <NotificationBell />
            <Pressable
              testID="portal-sign-out-button"
              onPress={handleSignOut}
              hitSlop={{ top: 12, bottom: 12, left: 12, right: 12 }}
              style={({ pressed }) => [
                s.signOutBtn,
                { opacity: pressed ? 0.5 : 1 },
              ]}
              accessibilityRole="button"
              accessibilityLabel="Sign out"
            >
              <Ionicons name="log-out-outline" size={24} color={colors.error} />
            </Pressable>
          </View>
        )}
      />
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
            <View style={s.statCircle} testID="portal-stat-balance-tile">
              <Text style={s.statValue} testID="portal-stat-balance">{money(data.outstanding || 0)}</Text>
              <Text style={s.statLabel}>Balance Due</Text>
            </View>
            <StatTile
              label="Past Due"
              value={money(data.past_due || 0)}
              bgColor={(data.past_due || 0) > 0 ? PAST_DUE_BG : undefined}
              testID="portal-stat-past-due"
            />
            <StatTile
              label="Credit"
              value={money(creditBalance)}
              bgColor={creditBalance > 0 ? CREDIT_BG : undefined}
              testID="portal-stat-credit"
            />
          </View>

          {/* Phase 30.2 · Feb-2026 — the previous compact "Next
              Service" row (Surface A) that lived here has been
              removed. The richer "Next Service Day" card (Surface
              B) is now hoisted up to occupy Surface A's former
              position, above Quick Actions. Nothing about the
              card's internal styling / testIDs has changed — only
              its parent position. Testids preserved:
              ``portal-next-service-day``,
              ``portal-next-service-day-detail``,
              ``portal-next-service-day-empty``,
              ``portal-tech-avatar-next``. */}
          <View style={s.nextServiceDayCard} testID="portal-next-service-day">
            <View style={s.nextServiceDayHeader}>
              <View style={s.nextServiceDayIcon}>
                <Ionicons name="sunny-outline" size={22} color="#0369A1" />
              </View>
              <Text style={s.nextServiceDayTitle}>Next Service Day</Text>
            </View>
            {data.next_service ? (
              <Pressable
                style={s.nextServiceDayBody}
                onPress={() => router.push(`/job/${data.next_service.id}`)}
                testID="portal-next-service-day-detail"
              >
                <View style={s.nextServiceDayDateBox}>
                  <Text style={s.nextServiceDayDateNum}>
                    {(() => {
                      const d = new Date(data.next_service.scheduled_date);
                      return isNaN(d.getTime()) ? "--" : d.getDate();
                    })()}
                  </Text>
                  <Text style={s.nextServiceDayDateMonth}>
                    {(() => {
                      const d = new Date(data.next_service.scheduled_date);
                      return isNaN(d.getTime()) ? "---" : d.toLocaleDateString("en-US", { month: "short" });
                    })()}
                  </Text>
                  <Text style={s.nextServiceDayDateDay}>
                    {(() => {
                      const d = new Date(data.next_service.scheduled_date);
                      return isNaN(d.getTime()) ? "---" : d.toLocaleDateString("en-US", { weekday: "short" });
                    })()}
                  </Text>
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={s.nextServiceDayName} numberOfLines={1}>{data.next_service.title}</Text>
                  <View style={{ flexDirection: "row", alignItems: "center", gap: 6, marginTop: 2 }}>
                    {data.next_service.technician_name ? (
                      <TechAvatar
                        user={{ name: data.next_service.technician_name }}
                        size="xs"
                        testID="portal-tech-avatar-next"
                      />
                    ) : null}
                    <Text style={s.nextServiceDayMeta}>
                      {data.next_service.technician_name || "Unassigned"} · {data.next_service.service_type || "Service"}
                    </Text>
                  </View>
                  <Text style={s.nextServiceDayAddr} numberOfLines={1}>
                    {data.next_service.address || "No address"}
                  </Text>
                </View>
                <Ionicons name="chevron-forward" size={18} color={PORTAL_TEXT_MUTED} />
              </Pressable>
            ) : (
              <View style={s.nextServiceDayEmpty} testID="portal-next-service-day-empty">
                <Ionicons name="calendar-clear-outline" size={28} color={PORTAL_TEXT_MUTED} />
                <Text style={s.nextServiceDayEmptyText}>No upcoming service scheduled</Text>
              </View>
            )}
          </View>

          {/* 4. Quick Actions Grid */}
          <Text style={s.gridTitle}>Quick Actions</Text>
          <View style={s.grid}>
            {QA_SECTIONS.map((sec) => {
              const badge = badgeFor(sec.key);
              return (
                <QuickActionTile
                  key={sec.key}
                  sec={sec}
                  badge={badge}
                  onPress={() => router.push(sec.route as any)}
                />
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
              <Ionicons name="chevron-forward" size={18} color={PORTAL_TEXT_MUTED} />
            </Pressable>
          ) : null}

          {/* 6. Ask a Concierge — Phase 25 (web Phase 23): stat-tile
              chassis + BLUE (brand) accent. Replaces teal→emerald gradient. */}
          {Array.isArray(aiEmployees) && aiEmployees.length > 0 ? (
            <View style={s.conciergeWrap} testID="portal-ai-section">
              <View style={s.conciergeHeader}>
                <Ionicons name="sparkles" size={20} color={colors.brand} testID="portal-ai-section-accent" />
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
                    <PersonaAvatar
                      persona={{
                        key: emp.key,
                        name: emp.name,
                        avatar_emoji: emp.avatar,
                      }}
                      size={44}
                      testID={`portal-ai-${emp.key}-avatar`}
                    />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={s.conciergeName}>{emp.name}</Text>
                    {/* Phase 30.1 · specialty subtitle. Prefer the
                        seed's ``role`` field (e.g. "Billing
                        assistant"); fall back to description /
                        tagline so an older API response still works. */}
                    <Text style={s.conciergeSpecialty} numberOfLines={1}>
                      {emp.role || emp.description || emp.tagline || ""}
                    </Text>
                  </View>
                  <Ionicons name="chevron-forward" size={16} color={PORTAL_TEXT_MUTED} />
                </Pressable>
              ))}
            </View>
          ) : null}

          {/* 7. Refer a Friend — Phase 25 (web Phase 23): stat-tile
              chassis + GREEN (success) accent. Replaces purple→magenta. */}
          <View style={s.referralWrap} testID="portal-referral-section">
            <Ionicons name="gift" size={28} color={colors.success} testID="portal-referral-section-accent" />
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
          </View>

          {/* 8. Business Card */}
          <Pressable
            style={s.bizCard}
            onPress={() => router.push("/card" as any)}
            testID="portal-card-business"
          >
            <View style={s.bizCardIcon} testID="portal-card-business-accent">
              <Ionicons name="id-card-outline" size={22} color={NAVY_ACCENT_FG} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={s.bizCardLabel}>Business Card</Text>
              <Text style={s.bizCardSub}>Contact info, QR code & more</Text>
            </View>
            <Ionicons name="chevron-forward" size={18} color={PORTAL_TEXT_MUTED} />
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

      {/* K24 — payment method prompt (once per session) */}
      <PaymentMethodPromptModal />
    </View>
  );
}

// Phase 25 · Past Due / Credit tile with Phase-24 dynamic bg.
function StatTile({ label, value, bgColor, testID }: {
  label: string; value: string; bgColor?: string; testID: string;
}) {
  const dyn = Boolean(bgColor);
  return (
    <View
      style={[s.statCircle, dyn && { backgroundColor: bgColor, borderColor: bgColor }]}
      testID={`${testID}-tile`}
    >
      <Text style={[s.statValue, dyn && s.statTextOnDynamic]} testID={testID}>{value}</Text>
      <Text style={[s.statLabel, dyn && s.statTextOnDynamic]} testID={`${testID}-label`}>{label}</Text>
    </View>
  );
}

// Phase 25 · Quick Action tile — press glow tracked via onPressIn /
// onPressOut (mobile analogue of web's hover:shadow halo).
function QuickActionTile({ sec, badge, onPress }: { sec: any; badge: number; onPress: () => void }) {
  const [pressed, setPressed] = useState(false);
  return (
    <Pressable
      style={[s.card, pressed && s.cardPressed]}
      onPress={onPress}
      onPressIn={() => setPressed(true)}
      onPressOut={() => setPressed(false)}
      testID={`portal-card-${sec.key}`}
      accessibilityRole="button"
      accessibilityLabel={sec.label}
    >
      {badge > 0 ? (
        <View style={s.cardBadge}><Text style={s.cardBadgeText}>{badge}</Text></View>
      ) : null}
      <View style={s.cardIcon}>
        <Ionicons name={sec.icon} size={20} color={colors.brand} />
      </View>
      <Text
        style={s.cardLabel}
        numberOfLines={1}
        adjustsFontSizeToFit
        minimumFontScale={QA_LABEL_MIN_FONT_SCALE}
        testID={`portal-qa-label-${sec.key}`}
      >
        {sec.label}
      </Text>
    </Pressable>
  );
}

const s = StyleSheet.create({
  // Phase 30.3 hotfix · header-right cluster. The parent `Header`
  // component (widgets.tsx:73) renders its LEFT block with
  // `flex: 1`, so any right-slot child WITHOUT an explicit
  // `flexShrink: 0` can be squeezed to sub-pixel width on wide
  // devices — visually still there, but taps route to the flex:1
  // sibling instead. `flexShrink: 0` + `minWidth`-safe spacing on
  // both children keeps the touch region intact.
  headerActions: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    flexShrink: 0,
  },
  signOutBtn: {
    padding: 8,
    borderRadius: 8,
    alignItems: "center",
    justifyContent: "center",
    flexShrink: 0,
  },
  root: { flex: 1, backgroundColor: PORTAL_DARK_BG },

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
    backgroundColor: TILE_BG, borderRadius: PORTAL_TILE_RADIUS,
    paddingVertical: 14, borderWidth: 1, borderColor: TILE_BORDER,
    ...KPI_GLOW,
  },
  // Phase 25 — text on a dynamic (red / green) tile bg.
  statTextOnDynamic: { color: "#FFFFFF" },
  statValue: { fontFamily: font.bold, fontSize: fontSize.xl, color: TILE_TEXT },
  statLabel: { fontFamily: font.medium, fontSize: 11, color: TILE_TEXT_MUTED, marginTop: 2 },
  heroInner: { flex: 1, padding: spacing.lg, justifyContent: "flex-end" },
  heroLabel: { fontFamily: font.medium, fontSize: fontSize.base, color: "rgba(255,255,255,0.85)" },
  heroValue: { fontFamily: font.bold, fontSize: 34, color: "#fff", marginTop: 2 },
  heroRow: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.md },
  heroPill: { flexDirection: "row", alignItems: "center", gap: 5, backgroundColor: "rgba(255,255,255,0.18)", paddingHorizontal: 10, paddingVertical: 5, borderRadius: radius.pill },
  heroPillText: { fontFamily: font.medium, fontSize: fontSize.sm, color: "#fff" },

  // Next Service
  nextCard: {
    flexDirection: "row", alignItems: "center", gap: spacing.md,
    backgroundColor: PORTAL_DARK_BG, borderRadius: PORTAL_TILE_RADIUS, padding: spacing.md,
    borderWidth: 1, borderColor: PORTAL_DARK_BORDER, marginBottom: spacing.lg,
  },
  nextIcon: { width: 44, height: 44, borderRadius: radius.md, backgroundColor: colors.brandTertiary, alignItems: "center", justifyContent: "center" },
  nextLabel: { fontFamily: font.medium, fontSize: fontSize.sm, color: PORTAL_TEXT_MUTED },
  nextTitle: { fontFamily: font.semibold, fontSize: fontSize.lg, color: PORTAL_TEXT },
  nextMeta: { fontFamily: font.regular, fontSize: fontSize.sm, color: PORTAL_TEXT_MUTED, marginTop: 1 },

  // Quick Actions Grid
  gridTitle: { fontFamily: font.bold, fontSize: fontSize.xl, color: PORTAL_TEXT, marginBottom: spacing.md },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.md, marginBottom: spacing.lg },
  card: {
    width: "47.5%", flexGrow: 1, backgroundColor: TILE_BG,
    borderRadius: PORTAL_TILE_RADIUS, padding: spacing.md, borderWidth: 1, borderColor: TILE_BORDER,
  },
  cardIcon: { width: 36, height: 36, borderRadius: radius.sm, backgroundColor: colors.brandTertiary, alignItems: "center", justifyContent: "center", marginBottom: spacing.sm },
  // 13pt: the longest label ("Payment Method") measured 116px at 14pt vs a
  // 112px label box at 320dp; 13pt ≈ 108px fits without relying on
  // adjustsFontSizeToFit (ignored on web).
  cardLabel: { fontFamily: font.semibold, fontSize: 13, color: TILE_TEXT },
  cardBadge: { position: "absolute", top: spacing.md, right: spacing.md, minWidth: 22, height: 22, paddingHorizontal: 6, borderRadius: 11, backgroundColor: colors.error, alignItems: "center", justifyContent: "center" },
  cardBadgeText: { color: "#fff", fontFamily: font.bold, fontSize: fontSize.sm },
  // Phase 25 · web Phase 24 hover glow → mobile press glow (onPressIn).
  // Soft white halo + brightness-95 analogue so the press reads on the
  // light chassis too. Android draws the halo via elevation (API 28+
  // honours shadowColor).
  cardPressed: {
    backgroundColor: colors.surfaceSecondary,
    shadowColor: "#FFFFFF", shadowOpacity: 0.6, shadowRadius: 20,
    shadowOffset: { width: 0, height: 0 }, elevation: 8,
  },

  // Last Visit
  lastVisitCard: {
    flexDirection: "row", alignItems: "center", gap: spacing.md,
    backgroundColor: PORTAL_DARK_BG, borderRadius: PORTAL_TILE_RADIUS, padding: spacing.md,
    borderWidth: 1, borderColor: PORTAL_DARK_BORDER, marginBottom: spacing.lg,
  },

  // Next Service Day
  nextServiceDayCard: {
    backgroundColor: PORTAL_DARK_BG, borderRadius: PORTAL_TILE_RADIUS,
    borderWidth: 1, borderColor: PORTAL_DARK_BORDER, marginBottom: spacing.lg,
    overflow: "hidden",
  },
  nextServiceDayHeader: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
    borderBottomWidth: 1, borderBottomColor: PORTAL_DARK_BORDER,
    backgroundColor: PORTAL_DARK_BG,
  },
  nextServiceDayIcon: {
    width: 36, height: 36, borderRadius: 18,
    backgroundColor: "#E0F2FE",
    alignItems: "center", justifyContent: "center",
  },
  nextServiceDayTitle: {
    fontFamily: font.bold, fontSize: fontSize.base, color: PORTAL_TEXT,
    letterSpacing: 0.3,
  },
  nextServiceDayBody: {
    flexDirection: "row", alignItems: "center", gap: spacing.md,
    padding: spacing.md,
  },
  nextServiceDayDateBox: {
    width: 56, alignItems: "center", justifyContent: "center",
    backgroundColor: colors.brand, borderRadius: radius.md,
    paddingVertical: spacing.sm,
  },
  nextServiceDayDateNum: {
    fontFamily: font.bold, fontSize: 22, color: "#fff", lineHeight: 24,
  },
  nextServiceDayDateMonth: {
    fontFamily: font.semibold, fontSize: 11, color: "rgba(255,255,255,0.85)",
    textTransform: "uppercase", letterSpacing: 0.6,
  },
  nextServiceDayDateDay: {
    fontFamily: font.medium, fontSize: 10, color: "rgba(255,255,255,0.7)",
    textTransform: "uppercase", marginTop: 1,
  },
  nextServiceDayName: {
    fontFamily: font.semibold, fontSize: fontSize.lg, color: PORTAL_TEXT,
  },
  nextServiceDayMeta: {
    fontFamily: font.regular, fontSize: fontSize.sm, color: PORTAL_TEXT_MUTED, marginTop: 2,
  },
  nextServiceDayAddr: {
    fontFamily: font.regular, fontSize: fontSize.sm, color: PORTAL_TEXT_MUTED, marginTop: 1,
  },
  nextServiceDayEmpty: {
    alignItems: "center", justifyContent: "center",
    paddingVertical: spacing.xl, gap: spacing.sm,
  },
  nextServiceDayEmptyText: {
    fontFamily: font.medium, fontSize: fontSize.base, color: PORTAL_TEXT_MUTED,
    textAlign: "center",
  },
  lastVisitIcon: { width: 44, height: 44, borderRadius: radius.md, backgroundColor: colors.brandTertiary, alignItems: "center", justifyContent: "center" },
  lastVisitLabel: { fontFamily: font.medium, fontSize: fontSize.sm, color: PORTAL_TEXT_MUTED },
  lastVisitTitle: { fontFamily: font.semibold, fontSize: fontSize.lg, color: PORTAL_TEXT },
  lastVisitDate: { fontFamily: font.regular, fontSize: fontSize.sm, color: PORTAL_TEXT_MUTED, marginTop: 1 },

  // Ask a Concierge
  // Phase 25 — shared dark stat-tile chassis (#03002e + #1E293B + 12).
  conciergeWrap: {
    backgroundColor: PORTAL_DARK_BG, borderRadius: PORTAL_TILE_RADIUS, borderWidth: 1,
    borderColor: PORTAL_DARK_BORDER, padding: 18, marginBottom: spacing.lg,
  },
  conciergeHeader: { flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 4 },
  conciergeTitle: { fontFamily: font.bold, fontSize: fontSize.lg, color: PORTAL_TEXT, textTransform: "uppercase", letterSpacing: 1 },
  conciergeSubtitle: { fontFamily: font.regular, fontSize: fontSize.base, color: PORTAL_TEXT_MUTED, marginBottom: spacing.md, lineHeight: 20 },
  conciergeCard: {
    flexDirection: "row", alignItems: "center", gap: spacing.md,
    backgroundColor: PORTAL_DARK_BG, borderWidth: 1,
    borderColor: PORTAL_DARK_BORDER, borderRadius: PORTAL_TILE_RADIUS,
    padding: spacing.md, marginTop: spacing.sm,
  },
  conciergeAvatar: { width: 44, height: 44, borderRadius: 22, backgroundColor: colors.brandTertiary, alignItems: "center", justifyContent: "center", overflow: "hidden" },
  // Phase 30.1 · specialty subtitle style. White on the teal→emerald
  // gradient at 85% alpha for legibility without competing with the
  // persona name.
  conciergeSpecialty: {
    fontFamily: font.regular,
    fontSize: 12,
    lineHeight: 16,
    color: PORTAL_TEXT_MUTED,
    marginTop: 2,
  },
  conciergeEmoji: { fontSize: 22 },
  conciergeName: { fontFamily: font.bold, fontSize: fontSize.base, color: PORTAL_TEXT },
  conciergeDesc: { fontFamily: font.regular, fontSize: fontSize.sm, color: PORTAL_TEXT_MUTED, marginTop: 2, lineHeight: 16 },

  // Refer a Friend
  referralWrap: {
    backgroundColor: PORTAL_DARK_BG, borderRadius: PORTAL_TILE_RADIUS, borderWidth: 1,
    borderColor: PORTAL_DARK_BORDER, padding: 20, marginBottom: spacing.lg,
    alignItems: "center",
  },
  referralTitle: { fontFamily: font.bold, fontSize: fontSize.xl, color: PORTAL_TEXT, marginTop: spacing.sm, textAlign: "center" },
  referralBody: { fontFamily: font.regular, fontSize: fontSize.base, color: PORTAL_TEXT_MUTED, marginTop: spacing.xs, textAlign: "center", lineHeight: 20 },
  referralBtn: {
    backgroundColor: colors.success, borderRadius: radius.pill, paddingHorizontal: 28, paddingVertical: 12, marginTop: spacing.md,
    minHeight: 44, justifyContent: "center",
  },
  referralBtnText: { fontFamily: font.bold, fontSize: fontSize.base, color: "#FFFFFF" },

  // Business Card
  bizCard: {
    flexDirection: "row", alignItems: "center", gap: spacing.md,
    backgroundColor: PORTAL_DARK_BG, borderRadius: PORTAL_TILE_RADIUS, padding: spacing.md,
    borderWidth: 1, borderColor: PORTAL_DARK_BORDER, marginBottom: spacing.md,
  },
  bizCardIcon: { width: 44, height: 44, borderRadius: radius.md, backgroundColor: NAVY_ACCENT_BG, alignItems: "center", justifyContent: "center" },
  bizCardLabel: { fontFamily: font.semibold, fontSize: fontSize.lg, color: PORTAL_TEXT },
  bizCardSub: { fontFamily: font.regular, fontSize: fontSize.sm, color: PORTAL_TEXT_MUTED, marginTop: 1 },
});
