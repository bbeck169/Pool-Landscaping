import React, { useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, Switch, Alert, Share } from "react-native";
import * as Clipboard from "expo-clipboard";
import { Image } from "expo-image";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { useAuth } from "@/src/auth";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import { registerForPushNotifications, deregisterPushToken } from "@/src/services/pushNotifications";
// Phase O6 · Manual sync surface.
import { ManualSyncButton } from "@/src/components/sync/ManualSyncButton";
// K36 · Diagnostic ring-buffer surface.
import { getDiagnostics, formatDiagnostics, clearDiagnostics } from "@/src/utils/diagnostics";
// FLEET-B · Fleet pause toggle for technicians.
import FleetPauseToggle from "@/src/components/fleet/FleetPauseToggle";
// TB-1 · MARCO voice preferences (TTS + wake-word toggles).
import MarcoVoiceSettings from "@/src/components/marco/MarcoVoiceSettings";
// Phase (Feb-2026) — mobile admin drawer parity with the web sidebar.
// Renders the ``QUICK_ACCESS`` shortcut group + the eight canonical
// admin groups from a single source of truth so parity edits are a
// one-file change.
import { ADMIN_NAV, OWNER_NAV, QUICK_ACCESS, canSeeEntry, filterNavByIndustries, type NavEntry, type NavGroup } from "@/src/nav/adminNav";
import { useIndustries } from "@/src/hooks/useIndustries";
import { useToast } from "@/src/components/ToastProvider";

export default function More() {
  const { showToast } = useToast(); // TD-96-mobile-toast-sweep (undefined since 4a8d04429)
  const { user, logout } = useAuth();
  const router = useRouter();
  const [pushEnabled, setPushEnabled] = useState(true);
  const role = (user?.role as string) || "";
  const isAdmin = role === "admin" || role === "super_admin";
  const isSuperAdmin = role === "super_admin";
  const isTech = role === "technician";
  const isMarketing = role === "marketing";
  const showAdminSection = isAdmin || isSuperAdmin || isMarketing;
  const showSeoSection = isAdmin || isSuperAdmin;
  const roleLabel = user?.role === "admin" ? "Administrator" : user?.role === "customer" ? "Customer" : "Technician";
  const { industries } = useIndustries();

  // Landscape AI, CAD Design Studio, Measure (Satellite), and Virtual Bid are admin-only
  // and intentionally omitted from the technician nav.
  const techLinks = [
    { icon: "apps-outline", label: "All My Tools", onPress: () => router.push("/(app)/tools" as any) },
    { icon: "flask-outline", label: "Pool Calculators", onPress: () => router.push("/(app)/calculators" as any) },
    { icon: "magnet-outline", label: "New Lead", onPress: () => router.push("/leads/new") },
    { icon: "footsteps-outline", label: "Door-to-Door", onPress: () => router.push("/d2d") },
    { icon: "trophy-outline", label: "D2D Leaderboard", onPress: () => router.push("/d2d/leaderboard") },
    { icon: "id-card-outline", label: "Business Card", onPress: () => router.push("/card") },
    { icon: "build-outline", label: "Equipment Repair", onPress: () => router.push("/equipment") },
    { icon: "location-outline", label: "Auto Clock-In", onPress: () => router.push("/(app)/settings/auto-clockin" as any) },
    { icon: "clipboard-outline", label: "My Onboarding", onPress: () => router.push("/(app)/onboarding/mine" as any) },
    { icon: "cube-outline", label: "My Equipment", onPress: () => router.push("/(app)/assets" as any) },
    { icon: "layers-outline", label: "Inventory", onPress: () => router.push("/(app)/inventory" as any) },
  ];

  const seoLinks = [
    { icon: "search-outline", label: "Site Auditor", onPress: () => router.push("/admin/seo/audits" as any) },
    { icon: "analytics-outline", label: "Content Scorer", onPress: () => router.push("/admin/seo/content-scorer" as any) },
    { icon: "grid-outline", label: "Rank Heatmap", onPress: () => router.push("/admin/seo/rank-heatmap" as any) },
    { icon: "git-network-outline", label: "Topical Map", onPress: () => router.push("/admin/seo/topical-map" as any) },
    { icon: "sparkles-outline", label: "LLM Visibility", onPress: () => router.push("/admin/seo/llm-visibility" as any) },
    { icon: "chatbubbles-outline", label: "Atlas Agent", onPress: () => router.push("/admin/seo/atlas" as any) },
    { icon: "construct-outline", label: "OTTO Auto-Fix", onPress: () => router.push("/admin/seo/otto" as any) },
    { icon: "document-text-outline", label: "Website Studio", onPress: () => router.push("/admin/seo/studio" as any) },
    { icon: "reader-outline", label: "White-Label Reports", onPress: () => router.push("/admin/seo/reports" as any) },
  ];

  const adminLinks = [
    { icon: "pulse-outline", label: "Work Stream", onPress: () => router.push("/workstream") },
    { icon: "calculator-outline", label: "Field Estimator", onPress: () => router.push("/(app)/estimator" as any) },
    { icon: "layers-outline", label: "Inventory", onPress: () => router.push("/(app)/inventory" as any) },
    { icon: "document-text-outline", label: "Check Register", onPress: () => router.push("/(app)/checks/register" as any) },
    { icon: "home-outline", label: "Property Lookup", onPress: () => router.push("/(app)/property-lookup" as any) },
    { icon: "mail-open-outline", label: "Dunning queue", onPress: () => router.push("/(app)/dunning/queue" as any) },
    { icon: "cube-outline", label: "LiDAR Settings", onPress: () => router.push("/(app)/settings/lidar" as any) },
    { icon: "magnet-outline", label: "New Lead", onPress: () => router.push("/leads/new") },
    { icon: "earth-outline", label: "Measure (Satellite)", onPress: () => router.push("/measure") },
    { icon: "home-outline", label: "Virtual Bid", onPress: () => router.push("/virtual-bid") },
    { icon: "receipt-outline", label: "Invoices (AR)", onPress: () => router.push("/invoices") },
    { icon: "calculator-outline", label: "Estimator", onPress: () => router.push("/estimator") },
    { icon: "id-card-outline", label: "Business Card", onPress: () => router.push("/card") },
    { icon: "calculator-outline", label: "Calculators", onPress: () => router.push("/(app)/calculators" as any) },
    { icon: "navigate-outline", label: "Dispatch", onPress: () => router.push("/(app)/dispatch/board" as any) },
    { icon: "cloud-outline", label: "Weather Reschedule", onPress: () => router.push("/(app)/dispatch/weather" as any) },
    { icon: "cash-outline", label: "Batch Checks & Payroll CSV", onPress: () => router.push("/(app)/payroll/batch" as any) },
    { icon: "swap-horizontal-outline", label: "Route Coverage", onPress: () => router.push("/coverage") },
    { icon: "time-outline", label: "Timesheets", onPress: () => router.push("/timesheets") },
    { icon: "bar-chart-outline", label: "Business Reports", onPress: () => router.push("/business-reports") },
    { icon: "bar-chart-outline", label: "Reports", onPress: () => router.push("/reports") },
    { icon: "magnet-outline", label: "Leads", onPress: () => router.push("/leads") },
    { icon: "people-circle-outline", label: "Team", onPress: () => router.push("/team") },
    { icon: "pricetags-outline", label: "Price Book", onPress: () => router.push("/price-book") },
    { icon: "card-outline", label: "Payments", onPress: () => router.push("/payments") },
    { icon: "repeat-outline", label: "Auto Billing", onPress: () => router.push("/auto-billing") },
    { icon: "build-outline", label: "Equipment Repair", onPress: () => router.push("/equipment") },
    { icon: "water-outline", label: "Maintenance", onPress: () => router.push("/maintenance") },
    { icon: "library-outline", label: "Templates Library", onPress: () => router.push("/(app)/templates" as any) },
    { icon: "flask-outline", label: "Log History Report", onPress: () => router.push("/log-history") },
    { icon: "timer-outline", label: "Job Timers", onPress: () => router.push("/job-timers") },
    { icon: "stats-chart-outline", label: "Avg Job Time", onPress: () => router.push("/avg-job-time") },
    { icon: "water-outline", label: "Pool Service Report", onPress: () => router.push("/pool-service") },
    { icon: "pie-chart-outline", label: "Income by Category", onPress: () => router.push("/income-by-category") },
    { icon: "analytics-outline", label: "Profit Report", onPress: () => router.push("/profit-report") },
    { icon: "pricetag-outline", label: "Income Categories", onPress: () => router.push("/income-categories") },
    { icon: "footsteps-outline", label: "Door-to-Door", onPress: () => router.push("/d2d") },
    { icon: "bar-chart-outline", label: "D2D Sales Report", onPress: () => router.push("/d2d/report") },
    { icon: "trophy-outline", label: "D2D Leaderboard", onPress: () => router.push("/d2d/leaderboard") },
    { icon: "leaf-outline", label: "Landscape AI", onPress: () => router.push("/landscape") },
    { icon: "grid-outline", label: "Design Studio (CAD)", onPress: () => router.push("/cad") },
    { icon: "megaphone-outline", label: "Marketing", onPress: () => router.push("/marketing") },
    { icon: "megaphone-outline", label: "Broadcasts", onPress: () => router.push("/marketing/broadcasts" as any) },
    { icon: "share-social-outline", label: "Social Media", onPress: () => router.push("/social") },
    { icon: "chatbubbles-outline", label: "Communication", onPress: () => router.push("/communications") },
    { icon: "sparkles-outline", label: "AI Employees", onPress: () => router.push("/ai-employees") },
    { icon: "rocket-outline", label: "SEO Studio", onPress: () => router.push("/seo") },
    { icon: "logo-google", label: "Google Business", onPress: () => router.push("/gbp") },
    { icon: "lock-closed-outline", label: "Access Settings", onPress: () => router.push("/access-settings") },
    { icon: "eye-outline", label: "Access History", onPress: () => router.push("/access-history") },
    { icon: "construct-outline", label: "Technicians", onPress: () => router.push("/technicians") },
    { icon: "cube-outline", label: "Assets", onPress: () => router.push("/(app)/assets" as any) },
    { icon: "clipboard-outline", label: "My Onboarding", onPress: () => router.push("/(app)/onboarding/mine" as any) },
    { icon: "people-outline", label: "Customers", onPress: () => router.push("/(app)/customers") },
    { icon: "document-text-outline", label: "Quotes & Invoices", onPress: () => router.push("/(app)/quotes") },
    { icon: "settings-outline", label: "Widget Configs", onPress: () => router.push("/settings/widgets") },
    { icon: "ban-outline", label: "Suppressions", onPress: () => router.push("/marketing/suppressions") },
    { icon: "filter-outline", label: "Service Tracking", onPress: () => router.push("/tracking") },
    { icon: "gift-outline", label: "Admin Referrals", onPress: () => router.push("/admin/referrals") },
    { icon: "pricetag-outline", label: "Promo Codes", onPress: () => router.push("/settings/promo-codes") },
    { icon: "cog-outline", label: "Tenant Settings", onPress: () => router.push("/settings/tenant") },
    { icon: "id-card-outline", label: "Business Card Settings", onPress: () => router.push("/settings/business-card" as any) },
    { icon: "bulb-outline", label: "AI Brain", onPress: () => router.push("/settings/ai-brain" as any) },
    { icon: "checkmark-done-outline", label: "Local SEO Checklist", onPress: () => router.push("/settings/local-seo" as any) },
    { icon: "globe-outline", label: "Website SEO", onPress: () => router.push("/settings/website-seo" as any) },
    { icon: "link-outline", label: "Vanity Slugs", onPress: () => router.push("/settings/vanity-slugs" as any) },
  ];

  return (
    <View style={styles.root}>
      <Header title={isAdmin ? "More" : "Profile"} />
      <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}>
        <Pressable
          style={styles.profileCard}
          onPress={() => router.push("/(app)/profile" as any)}
          testID="more-profile-link"
        >
          {user?.avatar ? (
            <Image source={{ uri: user.avatar }} style={styles.avatar} />
          ) : (
            <View style={[styles.avatar, styles.avatarFallback]}>
              <Text style={styles.avatarText}>{user?.name?.charAt(0)?.toUpperCase()}</Text>
            </View>
          )}
          <View style={{ flex: 1 }}>
            <Text style={styles.name}>{user?.name}</Text>
            <Text style={styles.email}>{user?.email}</Text>
            <View style={styles.roleBadge}>
              <Text style={styles.roleText}>{roleLabel}</Text>
            </View>
          </View>
          <Ionicons name="chevron-forward" size={20} color={colors.muted} />
        </Pressable>

        {showAdminSection ? (
          <>
            {/* Quick-Access shortcut group (top of drawer) */}
            <DrawerGroup group={QUICK_ACCESS} role={role} router={router} industries={industries} />

            {/* Eight canonical admin groups mirroring web sidebar order */}
            {ADMIN_NAV.map((g) => (
              <DrawerGroup key={g.key} group={g} role={role} router={router} industries={industries} />
            ))}
          </>
        ) : null}

        {/* Owner — role-scoped entries only (Marketing Forms), not the full admin drawer */}
        {role === "owner" ? (
          <DrawerGroup group={OWNER_NAV} role={role} router={router} industries={industries} />
        ) : null}

        {false ? (
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>SEO</Text>
            {seoLinks.map((l) => (
              <Pressable key={l.label} style={styles.link} onPress={l.onPress} testID={`more-seo-${l.label.split(" ")[0].toLowerCase()}`}>
                <View style={styles.linkIcon}>
                  <Ionicons name={l.icon as any} size={20} color={colors.brand} />
                </View>
                <Text style={styles.linkLabel}>{l.label}</Text>
                <Ionicons name="chevron-forward" size={18} color={colors.muted} />
              </Pressable>
            ))}
          </View>
        ) : null}

        {isTech ? (
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Tools</Text>
            {techLinks.map((l) => (
              <Pressable key={l.label} style={styles.link} onPress={l.onPress} testID={`more-link-${l.label.split(" ")[0].toLowerCase()}`}>
                <View style={styles.linkIcon}>
                  <Ionicons name={l.icon as any} size={20} color={colors.brand} />
                </View>
                <Text style={styles.linkLabel}>{l.label}</Text>
                <Ionicons name="chevron-forward" size={18} color={colors.muted} />
              </Pressable>
            ))}
          </View>
        ) : null}

        {/* Push notifications toggle */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Notifications</Text>
          <View style={[styles.link, { justifyContent: "space-between" }]} testID="push-notifications-toggle">
            <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm }}>
              <View style={styles.linkIcon}>
                <Ionicons name="notifications-outline" size={20} color={colors.brand} />
              </View>
              <Text style={styles.linkLabel}>Push Notifications</Text>
            </View>
            <Switch
              value={pushEnabled}
              onValueChange={async (val) => {
                setPushEnabled(val);
                if (val) {
                  await registerForPushNotifications().catch(() => {});
                } else {
                  await deregisterPushToken().catch(() => {});
                }
              }}
              trackColor={{ false: colors.surfaceTertiary, true: colors.brand }}
              thumbColor="#fff"
            />
          </View>
        </View>

        {/* FLEET-B · Fleet tracking pause toggle — visible to techs */}
        {isTech && (
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Fleet Tracking</Text>
            <FleetPauseToggle />
          </View>
        )}

        {/* TB-1 · MARCO voice settings — TTS + wake-word toggles */}
        {isTech && (
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>MARCO Voice</Text>
            <MarcoVoiceSettings />
          </View>
        )}

        {/* Security section */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Security</Text>
          <Pressable style={styles.link} onPress={() => router.push("/settings/change-password")} testID="change-password-link">
            <View style={styles.linkIcon}>
              <Ionicons name="lock-closed-outline" size={20} color={colors.brand} />
            </View>
            <Text style={styles.linkLabel}>Change Password</Text>
            <Ionicons name="chevron-forward" size={18} color={colors.muted} />
          </Pressable>
        </View>

        {/* Phase O6 · Manual sync surface */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Offline & Sync</Text>
          <ManualSyncButton />
        </View>

        {/* K36 · Diagnostics — copy the last 20 nav + last 20 API breadcrumbs
            (+ any persisted crash) so support can triage a mobile crash
            without a stack trace. Renders the same testIDs as ManualSyncButton
            so QA can automate the flow. */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Support</Text>
          <Pressable
            testID="send-diagnostics-btn"
            style={styles.link}
            onPress={async () => {
              try {
                const snap = await getDiagnostics();
                const text = formatDiagnostics(snap);
                Alert.alert(
                  "Diagnostics",
                  `${snap.nav.length} nav + ${snap.api.length} API breadcrumbs${snap.lastCrash ? " · includes last crash" : ""}. Choose how to send:`,
                  [
                    {
                      text: "Copy",
                      onPress: async () => {
                        try {
                          await Clipboard.setStringAsync(text);
                          showToast("Paste into an email or chat to support.");
                        } catch {
                          Alert.alert("Copy failed", "Try Share instead.");
                        }
                      },
                    },
                    {
                      text: "Share",
                      onPress: async () => {
                        try {
                          await Share.share({ message: text, title: "Mobile Diagnostics" });
                        } catch {
                          // User cancelled — silent.
                        }
                      },
                    },
                    {
                      text: "Clear",
                      style: "destructive",
                      onPress: async () => {
                        await clearDiagnostics();
                        showToast("Diagnostic breadcrumbs reset.");
                      },
                    },
                    { text: "Cancel", style: "cancel" },
                  ],
                );
              } catch (e: any) {
                Alert.alert("Diagnostics unavailable", e?.message || String(e));
              }
            }}
          >
            <View style={styles.linkIcon}>
              <Ionicons name="bug-outline" size={20} color={colors.brand} />
            </View>
            <Text style={styles.linkLabel}>Send Diagnostics</Text>
            <Ionicons name="chevron-forward" size={18} color={colors.muted} />
          </Pressable>
        </View>

        <Pressable style={styles.logout} onPress={logout} testID="logout-button">
          <Ionicons name="log-out-outline" size={20} color={colors.error} />
          <Text style={styles.logoutText}>Sign out</Text>
        </Pressable>

        <Text style={styles.version}>Pool & Landscaping of Vistancia · v1.0</Text>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  profileCard: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.lg,
    borderWidth: 1,
    borderColor: colors.border,
  },
  avatar: { width: 64, height: 64, borderRadius: 32, backgroundColor: colors.brandTertiary },
  avatarFallback: { alignItems: "center", justifyContent: "center" },
  avatarText: { fontFamily: font.bold, fontSize: fontSize["2xl"], color: colors.brand },
  name: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface },
  email: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted, marginTop: 1 },
  roleBadge: {
    alignSelf: "flex-start",
    backgroundColor: colors.brandTertiary,
    paddingHorizontal: 10,
    paddingVertical: 3,
    borderRadius: radius.pill,
    marginTop: spacing.sm,
  },
  roleText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.brand },
  section: { marginTop: spacing.xl },
  sectionTitle: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface, marginBottom: spacing.md },
  link: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
    marginBottom: spacing.sm,
  },
  linkIcon: {
    width: 40,
    height: 40,
    borderRadius: radius.md,
    backgroundColor: colors.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
  },
  linkLabel: { flex: 1, fontFamily: font.semibold, fontSize: fontSize.lg, color: colors.onSurface },
  logout: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.sm,
    marginTop: spacing.xl,
    height: 52,
    borderRadius: radius.md,
    borderWidth: 1.5,
    borderColor: colors.error,
  },
  logoutText: { fontFamily: font.semibold, fontSize: fontSize.lg, color: colors.error },
  version: { textAlign: "center", fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: spacing.xl },
  webOnlyPill: {
    marginLeft: 8,
    paddingHorizontal: 6, paddingVertical: 2,
    borderRadius: radius.pill,
    backgroundColor: colors.surfaceTertiary,
  },
  webOnlyPillText: { fontFamily: font.semibold, fontSize: 10, color: colors.muted, letterSpacing: 0.4 },
  comingSoonPill: {
    marginLeft: 8,
    paddingHorizontal: 6, paddingVertical: 2,
    borderRadius: radius.pill,
    backgroundColor: colors.brandTertiary,
  },
  comingSoonPillText: { fontFamily: font.semibold, fontSize: 10, color: colors.brand, letterSpacing: 0.4 },
});

// ── Data-driven drawer render (Feb-2026 parity) ────────────────────

function DrawerGroup({ group, role, router, industries }: {
  group: NavGroup;
  role: string;
  router: ReturnType<typeof useRouter>;
  industries: string[];
}) {
  const industryFiltered = filterNavByIndustries(group.entries, industries);
  const visible = industryFiltered.filter((e) => canSeeEntry(role, e));
  if (visible.length === 0) return null;
  return (
    <View style={styles.section} testID={`drawer-group-${group.key}`}>
      <Text style={styles.sectionTitle}>{group.label}</Text>
      {visible.map((e) => (
        <DrawerRow key={e.testID} entry={e} router={router} />
      ))}
    </View>
  );
}

function DrawerRow({ entry, router }: {
  entry: NavEntry;
  router: ReturnType<typeof useRouter>;
}) {
  const onPress = () => {
    if (entry.tier === "t3") {
      router.push({
        pathname: "/web-only",
        params: { title: entry.label, webPath: entry.route },
      });
    } else if (entry.tier === "t2") {
      // Best-effort: navigate to the real mobile route first (in case
      // the screen was quietly added between drawer edits). If Expo
      // Router bounces to 404 the fallback route below will still
      // render the ComingSoonPage.
      router.push(entry.route as any);
    } else {
      router.push(entry.route as any);
    }
  };

  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => [
        styles.link,
        entry.tier === "t3" && { opacity: 0.75 },
        pressed && { opacity: 0.85 },
      ]}
      testID={entry.testID}
      accessibilityRole="button"
      accessibilityLabel={entry.label}
    >
      <View style={styles.linkIcon}>
        <Ionicons name={entry.icon as any} size={20} color={colors.brand} />
      </View>
      <Text style={styles.linkLabel}>{entry.label}</Text>
      {entry.tier === "t2" ? (
        <View style={styles.comingSoonPill}>
          <Text style={styles.comingSoonPillText}>SOON</Text>
        </View>
      ) : entry.tier === "t3" ? (
        <View style={styles.webOnlyPill}>
          <Text style={styles.webOnlyPillText}>WEB</Text>
        </View>
      ) : null}
      <Ionicons name="chevron-forward" size={18} color={colors.muted} />
    </Pressable>
  );
}
