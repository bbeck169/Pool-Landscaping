import React from "react";
import { View, Text, StyleSheet, ScrollView, Pressable } from "react-native";
import { Image } from "expo-image";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { useAuth } from "@/src/auth";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";

export default function More() {
  const { user, logout } = useAuth();
  const router = useRouter();
  const role = (user?.role as string) || "";
  const isAdmin = role === "admin";
  const isSuperAdmin = role === "super_admin";
  const isTech = role === "technician";
  const isMarketing = role === "marketing";
  const showAdminSection = isAdmin || isSuperAdmin || isMarketing;
  const showSeoSection = isAdmin || isSuperAdmin;
  const roleLabel = user?.role === "admin" ? "Administrator" : user?.role === "customer" ? "Customer" : "Technician";

  // Landscape AI, CAD Design Studio, Measure (Satellite), and Virtual Bid are admin-only
  // and intentionally omitted from the technician nav.
  const techLinks = [
    { icon: "calculator-outline", label: "Field Estimator", onPress: () => router.push("/(app)/estimator" as any) },
    { icon: "magnet-outline", label: "New Lead", onPress: () => router.push("/leads/new") },
    { icon: "footsteps-outline", label: "Door-to-Door", onPress: () => router.push("/d2d") },
    { icon: "trophy-outline", label: "D2D Leaderboard", onPress: () => router.push("/d2d/leaderboard") },
    { icon: "id-card-outline", label: "Business Card", onPress: () => router.push("/card") },
    { icon: "build-outline", label: "Equipment Repair", onPress: () => router.push("/equipment") },
    { icon: "location-outline", label: "Auto Clock-In", onPress: () => router.push("/(app)/settings/auto-clockin" as any) },
    { icon: "clipboard-outline", label: "My Onboarding", onPress: () => router.push("/(app)/onboarding/mine" as any) },
    { icon: "cube-outline", label: "My Equipment", onPress: () => router.push("/(app)/assets" as any) },
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
    { icon: "calculator-outline", label: "Field Estimator", onPress: () => router.push("/(app)/estimator" as any) },
    { icon: "cube-outline", label: "LiDAR Settings", onPress: () => router.push("/(app)/settings/lidar" as any) },
    { icon: "magnet-outline", label: "New Lead", onPress: () => router.push("/leads/new") },
    { icon: "earth-outline", label: "Measure (Satellite)", onPress: () => router.push("/measure") },
    { icon: "home-outline", label: "Virtual Bid", onPress: () => router.push("/virtual-bid") },
    { icon: "receipt-outline", label: "Invoices (AR)", onPress: () => router.push("/invoices") },
    { icon: "calculator-outline", label: "Estimator", onPress: () => router.push("/estimator") },
    { icon: "id-card-outline", label: "Business Card", onPress: () => router.push("/card") },
    { icon: "calculator-outline", label: "Calculators", onPress: () => router.push("/(app)/tools") },
    { icon: "navigate-outline", label: "Dispatch", onPress: () => router.push("/dispatch") },
    { icon: "swap-horizontal-outline", label: "Route Coverage", onPress: () => router.push("/coverage") },
    { icon: "time-outline", label: "Timesheets", onPress: () => router.push("/timesheets") },
    { icon: "pulse-outline", label: "Work Stream", onPress: () => router.push("/work-stream") },
    { icon: "bar-chart-outline", label: "Business Reports", onPress: () => router.push("/business-reports") },
    { icon: "bar-chart-outline", label: "Reports", onPress: () => router.push("/reports") },
    { icon: "magnet-outline", label: "Leads", onPress: () => router.push("/leads") },
    { icon: "people-circle-outline", label: "Team", onPress: () => router.push("/team") },
    { icon: "pricetags-outline", label: "Price Book", onPress: () => router.push("/price-book") },
    { icon: "card-outline", label: "Payments", onPress: () => router.push("/payments") },
    { icon: "repeat-outline", label: "Auto Billing", onPress: () => router.push("/auto-billing") },
    { icon: "build-outline", label: "Equipment Repair", onPress: () => router.push("/equipment") },
    { icon: "water-outline", label: "Maintenance", onPress: () => router.push("/maintenance") },
    { icon: "flask-outline", label: "Log History Report", onPress: () => router.push("/log-history") },
    { icon: "timer-outline", label: "Job Timers", onPress: () => router.push("/job-timers") },
    { icon: "stats-chart-outline", label: "Avg Job Time", onPress: () => router.push("/avg-job-time") },
    { icon: "water-outline", label: "Pool Service Report", onPress: () => router.push("/pool-service") },
    { icon: "pie-chart-outline", label: "Income by Category", onPress: () => router.push("/income-by-category") },
    { icon: "pricetag-outline", label: "Income Categories", onPress: () => router.push("/income-categories") },
    { icon: "footsteps-outline", label: "Door-to-Door", onPress: () => router.push("/d2d") },
    { icon: "bar-chart-outline", label: "D2D Sales Report", onPress: () => router.push("/d2d/report") },
    { icon: "trophy-outline", label: "D2D Leaderboard", onPress: () => router.push("/d2d/leaderboard") },
    { icon: "leaf-outline", label: "Landscape AI", onPress: () => router.push("/landscape") },
    { icon: "grid-outline", label: "Design Studio (CAD)", onPress: () => router.push("/cad") },
    { icon: "megaphone-outline", label: "Marketing", onPress: () => router.push("/marketing") },
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
  ];

  return (
    <View style={styles.root}>
      <Header title={isAdmin ? "More" : "Profile"} />
      <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}>
        <View style={styles.profileCard}>
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
        </View>

        {showAdminSection ? (
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Management</Text>
            {adminLinks.map((l) => (
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

        {showSeoSection ? (
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
});
