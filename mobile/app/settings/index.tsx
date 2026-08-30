/**
 * Settings Hub · Mobile — 4-tab layout (General / Branding / Integrations / Social).
 *
 * Mirrors web SettingsHub.jsx.
 * Role gate is handled by the parent settings/_layout.tsx (admin + super_admin).
 * Online-only — shows an offline banner when disconnected.
 */
import React, { useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable,
  ActivityIndicator,
} from "react-native";
import { useRouter, useLocalSearchParams } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { Header } from "@/src/components/widgets";
import { Card } from "@/src/components/ui";
import { useOnline } from "@/src/offline";
import { api } from "@/src/api";
import BrandLogo from "@/src/components/BrandLogo";
import PlatformGrid from "@/src/components/settings/PlatformGrid";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";

/* ════════════════════════════════════════════════════════════
   Tab config
   ════════════════════════════════════════════════════════════ */
type TabKey = "general" | "branding" | "integrations" | "social";

const TABS: { key: TabKey; label: string; icon: string }[] = [
  { key: "general",      label: "General",      icon: "settings-outline" },
  { key: "branding",     label: "Branding",     icon: "color-palette-outline" },
  { key: "integrations", label: "Integrations", icon: "extension-puzzle-outline" },
  { key: "social",       label: "Social",       icon: "share-social-outline" },
];

/* ════════════════════════════════════════════════════════════
   General tab
   ════════════════════════════════════════════════════════════ */
const GENERAL_LINKS: { icon: string; label: string; route: string }[] = [
  { icon: "business-outline",      label: "Tenant name & brand colours", route: "/settings/tenant" },
  { icon: "id-card-outline",       label: "Business card",               route: "/settings/business-card" },
  { icon: "document-text-outline", label: "Default terms & conditions",  route: "/settings/terms" },
  { icon: "document-outline",      label: "Legal documents",             route: "/settings/legal" },
  { icon: "notifications-outline", label: "Notification preferences",    route: "/settings/notifications" },
  { icon: "pricetag-outline",      label: "Promo codes",                 route: "/settings/promo-codes" },
  { icon: "list-outline",          label: "Service categories",          route: "/settings/service-categories" },
  { icon: "cash-outline",          label: "Income categories",           route: "/settings/income-categories" },
];

function GeneralTab() {
  const router = useRouter();
  return (
    <Card style={s.tabCard} testID="settings-general-card">
      <Text style={s.tabTitle}>General</Text>
      <Text style={s.tabHint}>
        Core tenant configuration — tap any item to jump straight in.
      </Text>
      <View style={s.linkGrid}>
        {GENERAL_LINKS.map((link) => (
          <Pressable
            key={link.route}
            style={s.linkRow}
            onPress={() => router.push(link.route as any)}
            testID={`settings-general-link-${link.route.split("/").pop()}`}
          >
            <Ionicons name={link.icon as any} size={16} color={colors.brand} />
            <Text style={s.linkLabel} numberOfLines={1}>{link.label}</Text>
            <Ionicons name="chevron-forward" size={14} color={colors.muted} />
          </Pressable>
        ))}
      </View>
    </Card>
  );
}

/* ════════════════════════════════════════════════════════════
   Branding tab
   ════════════════════════════════════════════════════════════ */
function BrandingTab() {
  return (
    <Card style={s.tabCard} testID="settings-branding-card">
      <Text style={s.tabTitle}>Branding</Text>
      <Text style={s.tabHint}>Current tenant logo</Text>
      <View style={s.brandLogoContainer}>
        <BrandLogo size="lg" variant="full" onPress={null} />
      </View>
      <View style={s.infoBox} testID="settings-branding-web-note">
        <Ionicons name="information-circle-outline" size={16} color="#0369A1" />
        <Text style={s.infoText}>
          Manage branding from the web app for now. Mobile logo upload is coming soon.
        </Text>
      </View>
    </Card>
  );
}

/* ════════════════════════════════════════════════════════════
   Integrations tab
   ════════════════════════════════════════════════════════════ */
const KNOWN_INTEGRATIONS = [
  { k: "emergent_llm",    label: "Emergent LLM",           desc: "OpenAI / Claude / Gemini via Emergent" },
  { k: "google",          label: "Google",                 desc: "Places autocomplete, Geocoding, Maps tiles" },
  { k: "resend",          label: "Resend",                 desc: "Transactional email" },
  { k: "stripe",          label: "Stripe",                 desc: "Card payments" },
  { k: "stripe_webhook",  label: "Stripe Webhook",         desc: "Webhook signing secret" },
  { k: "gbp",             label: "Google Business Profile", desc: "OAuth Client ID" },
  { k: "ringcentral",     label: "RingCentral",            desc: "SMS delivery + inbound call tracking" },
];

function IntegrationsTab() {
  const [rows, setRows] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get("/settings/integrations")
      .then((r: any) => { setRows(r); setLoading(false); })
      .catch(() => { setRows({}); setLoading(false); });
  }, []);

  return (
    <Card style={s.tabCard} testID="settings-integrations-card">
      <Text style={s.tabTitle}>Integrations</Text>
      <Text style={s.tabHint}>
        Wired third-party services. Manage connections from the web app.
      </Text>
      {loading ? (
        <View style={s.loadingWrap} testID="settings-integrations-loading">
          <ActivityIndicator size="small" color={colors.brand} />
        </View>
      ) : (
        <View style={s.intGrid}>
          {KNOWN_INTEGRATIONS.map((int) => {
            const st = rows?.[int.k] || { configured: false };
            return (
              <View
                key={int.k}
                style={s.intRow}
                testID={`settings-integration-${int.k}`}
              >
                <View style={[s.intDot, { backgroundColor: st.configured ? "#16A34A" : colors.error }]} />
                <View style={{ flex: 1 }}>
                  <View style={s.intNameRow}>
                    <Text style={s.intName}>{int.label}</Text>
                    <View style={[s.intChip, { backgroundColor: st.configured ? "#DCFCE7" : "#FEE2E2" }]}>
                      <Text style={[s.intChipText, { color: st.configured ? "#166534" : "#991B1B" }]}>
                        {st.configured ? "Configured" : "Not configured"}
                      </Text>
                    </View>
                  </View>
                  <Text style={s.intDesc}>{int.desc}</Text>
                  {st.configured && st.preview ? (
                    <Text style={s.intPreview} numberOfLines={1}>{st.preview}</Text>
                  ) : null}
                </View>
              </View>
            );
          })}
        </View>
      )}
      <View style={[s.infoBox, { marginTop: spacing.md }]} testID="settings-integrations-web-note">
        <Ionicons name="information-circle-outline" size={16} color="#0369A1" />
        <Text style={s.infoText}>
          OAuth flows and API key management are available on the web app.
        </Text>
      </View>
    </Card>
  );
}

/* ════════════════════════════════════════════════════════════
   Social tab
   ════════════════════════════════════════════════════════════ */
function SocialTab({ online }: { online: boolean }) {
  const router = useRouter();
  return (
    <View testID="settings-social-page">
      <Card style={s.tabCard}>
        <View style={s.socialHeader}>
          <View style={{ flex: 1 }}>
            <Text style={s.tabTitle}>Social connections</Text>
            <Text style={s.tabHint}>
              Manage cadence for every social channel. Brand Brain / Autopilot / Review Queue live on the Soshie workspace.
            </Text>
          </View>
          <Pressable
            style={s.soshieLink}
            onPress={() => router.push("/soshie")}
            testID="settings-social-open-soshie"
          >
            <Ionicons name="sparkles-outline" size={14} color={colors.brand} />
            <Text style={s.soshieLinkText}>Open Soshie</Text>
            <Ionicons name="open-outline" size={12} color={colors.brand} />
          </Pressable>
        </View>
      </Card>
      <View style={{ marginTop: spacing.md }}>
        <PlatformGrid disabled={!online} />
      </View>
    </View>
  );
}

/* ════════════════════════════════════════════════════════════
   Offline banner
   ════════════════════════════════════════════════════════════ */
function OfflineBanner() {
  return (
    <View style={s.offlineBanner} testID="settings-offline-banner">
      <Ionicons name="cloud-offline" size={16} color="#92400E" />
      <Text style={s.offlineText}>
        {"You're offline — Settings needs a connection"}
      </Text>
    </View>
  );
}

/* ════════════════════════════════════════════════════════════
   Main Hub
   ════════════════════════════════════════════════════════════ */
export default function SettingsHubScreen() {
  const params = useLocalSearchParams<{ tab?: string }>();
  const initialTab = (TABS.find((t) => t.key === params.tab)?.key) || "general";
  const [tab, setTab] = useState<TabKey>(initialTab);
  const online = useOnline();

  return (
    <View style={s.root} testID="settings-hub">
      <Header
        title="Settings"
        back
        subtitle="Tenant configuration & integrations"
      />

      {!online && <OfflineBanner />}

      {/* Segment tabs */}
      <View style={s.segment} testID="settings-hub-tabs">
        {TABS.map((t) => {
          const active = tab === t.key;
          return (
            <Pressable
              key={t.key}
              onPress={() => setTab(t.key)}
              style={[s.segBtn, active && s.segBtnActive]}
              testID={`settings-tab-${t.key}`}
              accessibilityRole="tab"
              accessibilityLabel={t.label}
              accessibilityState={{ selected: active }}
            >
              <Ionicons
                name={t.icon as any}
                size={14}
                color={active ? "#fff" : colors.onSurfaceSecondary}
              />
              <Text
                style={[
                  s.segText,
                  { color: active ? "#fff" : colors.onSurfaceSecondary },
                ]}
                numberOfLines={1}
              >
                {t.label}
              </Text>
            </Pressable>
          );
        })}
      </View>

      {/* Tab content */}
      <ScrollView
        style={s.content}
        contentContainerStyle={s.contentInner}
        showsVerticalScrollIndicator={false}
      >
        {tab === "general" && <GeneralTab />}
        {tab === "branding" && <BrandingTab />}
        {tab === "integrations" && <IntegrationsTab />}
        {tab === "social" && <SocialTab online={online} />}
      </ScrollView>
    </View>
  );
}

/* ════════════════════════════════════════════════════════════
   Styles
   ════════════════════════════════════════════════════════════ */
const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  offlineBanner: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    backgroundColor: "#FEF3C7",
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm + 2,
  },
  offlineText: {
    fontFamily: font.medium,
    fontSize: fontSize.sm,
    color: "#92400E",
    flex: 1,
  },
  segment: {
    flexDirection: "row",
    marginHorizontal: spacing.lg,
    marginTop: spacing.md,
    backgroundColor: colors.surfaceTertiary,
    borderRadius: radius.md,
    padding: 3,
  },
  segBtn: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 3,
    paddingVertical: 9,
    borderRadius: radius.md - 2,
  },
  segBtnActive: {
    backgroundColor: colors.brand,
  },
  segText: {
    fontFamily: font.semibold,
    fontSize: 11,
  },
  content: { flex: 1 },
  contentInner: {
    padding: spacing.lg,
    paddingBottom: spacing["2xl"],
  },
  tabCard: { marginBottom: 0 },
  tabTitle: {
    fontFamily: font.semibold,
    fontSize: fontSize.lg,
    color: colors.onSurface,
  },
  tabHint: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
    marginTop: 4,
    marginBottom: spacing.md,
  },
  /* General links */
  linkGrid: { gap: spacing.sm },
  linkRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.md,
  },
  linkLabel: {
    flex: 1,
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.onSurface,
  },
  /* Branding */
  brandLogoContainer: {
    alignItems: "center",
    paddingVertical: spacing.xl,
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
  },
  infoBox: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: spacing.sm,
    marginTop: spacing.md,
    backgroundColor: "#EFF6FF",
    borderRadius: radius.md,
    padding: spacing.md,
  },
  infoText: {
    flex: 1,
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: "#0369A1",
    lineHeight: 20,
  },
  /* Integrations */
  loadingWrap: {
    paddingVertical: spacing.xl,
    alignItems: "center",
  },
  intGrid: { gap: spacing.sm },
  intRow: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: spacing.sm,
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    padding: spacing.md,
  },
  intDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    marginTop: 5,
  },
  intNameRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    flexWrap: "wrap",
  },
  intName: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.onSurface,
  },
  intChip: {
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: radius.pill,
  },
  intChipText: {
    fontFamily: font.bold,
    fontSize: 10,
    textTransform: "uppercase",
  },
  intDesc: {
    fontFamily: font.regular,
    fontSize: 12,
    color: colors.muted,
    marginTop: 2,
  },
  intPreview: {
    fontFamily: font.regular,
    fontSize: 12,
    color: colors.onSurface,
    marginTop: 2,
  },
  /* Social */
  socialHeader: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: spacing.md,
  },
  soshieLink: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  soshieLinkText: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.brand,
  },
});
