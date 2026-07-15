/**
 * "All My Tools" hub — technician navigation directory.
 *
 * Surfaces every page a tech can reach as searchable, grouped tiles. Replaces
 * the old hidden-away-in-More approach and gives back tab-bar slots for the
 * pages techs actually open ten times a day (Schedule / D2D / Time Clock /
 * Tools / Profile).
 *
 * Admins land here too so they can jump directly to the pool-chemistry
 * calculators without going through More.
 */
import React, { useMemo, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, TextInput, Platform } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { Header } from "@/src/components/widgets";
import { useAuth } from "@/src/auth";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";

type Tile = {
  key: string;
  icon: any;
  label: string;
  desc: string;
  route: string;
};

type Section = {
  key: string;
  title: string;
  tiles: Tile[];
};

const TECH_SECTIONS: Section[] = [
  {
    key: "daily",
    title: "Daily Work",
    tiles: [
      { key: "schedule", icon: "today-outline", label: "Schedule", desc: "Today's stops in order", route: "/(app)/today" },
      { key: "d2d", icon: "footsteps-outline", label: "D2D Canvassing", desc: "Log knocks & book leads", route: "/(app)/d2d" },
      { key: "time-clock", icon: "time-outline", label: "Time Clock", desc: "Clock in / out, breaks, mileage", route: "/(app)/time-clock" },
      { key: "huddle", icon: "chatbubbles-outline", label: "Daily Huddle", desc: "Post yesterday / today / blockers", route: "/(app)/huddle" },
    ],
  },
  {
    key: "job",
    title: "On the Job",
    tiles: [
      { key: "estimator", icon: "calculator-outline", label: "Field Estimator", desc: "Quote on the spot", route: "/(app)/estimator" },
      { key: "calculators", icon: "flask-outline", label: "Pool Calculators", desc: "Dosing · Volume · Salt · LSI", route: "/(app)/calculators" },
      { key: "property-lookup", icon: "home-outline", label: "Property Lookup", desc: "Owner, lot size, notes (Zillow)", route: "/(app)/property-lookup" },
      { key: "inventory", icon: "layers-outline", label: "Inventory", desc: "Truck stock & re-order alerts", route: "/(app)/inventory" },
      { key: "equipment", icon: "cube-outline", label: "My Equipment", desc: "Assets assigned to me", route: "/(app)/assets" },
      { key: "new-lead", icon: "magnet-outline", label: "New Lead", desc: "Log a walk-in or referral", route: "/(app)/new-lead" },
    ],
  },
  {
    key: "records",
    title: "My Records",
    tiles: [
      { key: "onboarding", icon: "clipboard-outline", label: "My Onboarding", desc: "Checklist steps assigned to me", route: "/(app)/onboarding/mine" },
      { key: "d2d-leaderboard", icon: "trophy-outline", label: "D2D Leaderboard", desc: "See where your knocks rank", route: "/d2d/leaderboard" },
      { key: "card", icon: "id-card-outline", label: "Business Card", desc: "Share your digital card", route: "/card" },
    ],
  },
  {
    key: "account",
    title: "Account",
    tiles: [
      { key: "profile", icon: "person-outline", label: "Profile", desc: "Name, email, sign out", route: "/(app)/more" },
      { key: "auto-clockin", icon: "location-outline", label: "Auto Clock-In", desc: "Geofence settings", route: "/(app)/settings/auto-clockin" },
    ],
  },
];

const ADMIN_SECTIONS: Section[] = [
  {
    key: "adm-daily",
    title: "Daily Work",
    tiles: [
      { key: "schedule", icon: "calendar-outline", label: "Schedule", desc: "Dispatch board", route: "/(app)/schedule" },
      { key: "customers", icon: "people-outline", label: "Customers", desc: "Full customer directory", route: "/(app)/customers" },
      { key: "quotes", icon: "document-text-outline", label: "Quotes & Invoices", desc: "Send, sign, collect", route: "/(app)/quotes" },
    ],
  },
  {
    key: "adm-tools",
    title: "Tools",
    tiles: [
      { key: "business-card", icon: "id-card-outline", label: "My Business Card", desc: "NFC-ready digital card & .vcf", route: "/card" },
      { key: "calculators", icon: "flask-outline", label: "Pool Calculators", desc: "Dosing · Volume · Salt · LSI", route: "/(app)/calculators" },
      { key: "estimator", icon: "calculator-outline", label: "Field Estimator", desc: "Build a quote on-site", route: "/(app)/estimator" },
      { key: "inventory", icon: "layers-outline", label: "Inventory", desc: "Stock & purchase orders", route: "/(app)/inventory" },
      { key: "checks", icon: "document-text-outline", label: "Check Register", desc: "Write checks, batch payroll", route: "/(app)/checks/register" },
      { key: "property-lookup", icon: "home-outline", label: "Property Lookup", desc: "Owner + lot size search", route: "/(app)/property-lookup" },
      { key: "dunning", icon: "mail-open-outline", label: "Dunning Queue", desc: "Overdue invoices workflow", route: "/(app)/dunning/queue" },
    ],
  },
  {
    key: "adm-dispatch",
    title: "Dispatch",
    tiles: [
      { key: "dispatch-board", icon: "git-network-outline", label: "Dispatch Board", desc: "Auto-route unassigned jobs", route: "/(app)/dispatch/board" },
      { key: "dispatch-weather", icon: "cloud-outline", label: "Weather Reschedule", desc: "Move outdoor jobs when rain / wind spikes", route: "/(app)/dispatch/weather" },
    ],
  },
  {
    key: "adm-payroll",
    title: "Payroll",
    tiles: [
      { key: "payroll-batch", icon: "cash-outline", label: "Batch Checks & Payroll CSV", desc: "Write many checks at once + CSV import", route: "/(app)/payroll/batch" },
    ],
  },
];

function Tile({ tile, onPress }: { tile: Tile; onPress: () => void }) {
  return (
    <Pressable
      style={styles.tile}
      onPress={onPress}
      testID={`tools-tile-${tile.key}`}
      android_ripple={{ color: colors.border }}
    >
      <View style={styles.tileIcon}>
        <Ionicons name={tile.icon} size={22} color={colors.brand} />
      </View>
      <View style={{ flex: 1 }}>
        <Text style={styles.tileLabel}>{tile.label}</Text>
        <Text style={styles.tileDesc} numberOfLines={2}>{tile.desc}</Text>
      </View>
      <Ionicons name="chevron-forward" size={18} color={colors.muted} />
    </Pressable>
  );
}

export default function ToolsHub() {
  const router = useRouter();
  const { user } = useAuth();
  const role = (user?.role as string) || "";
  const isAdmin = role === "admin" || role === "super_admin";
  const [query, setQuery] = useState("");

  const sections = isAdmin ? ADMIN_SECTIONS : TECH_SECTIONS;

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return sections;
    return sections
      .map((s) => ({ ...s, tiles: s.tiles.filter((t) => t.label.toLowerCase().includes(q) || t.desc.toLowerCase().includes(q)) }))
      .filter((s) => s.tiles.length > 0);
  }, [query, sections]);

  const totalTiles = useMemo(() => sections.reduce((a, s) => a + s.tiles.length, 0), [sections]);

  return (
    <View style={styles.root}>
      <Header title="All My Tools" subtitle={isAdmin ? "Everything you can do — one screen" : `${totalTiles} tools available to you`} />
      <View style={styles.searchWrap}>
        <Ionicons name="search-outline" size={18} color={colors.muted} />
        <TextInput
          testID="tools-search"
          style={styles.searchInput}
          value={query}
          onChangeText={setQuery}
          placeholder="Search tools…"
          placeholderTextColor={colors.muted}
          autoCorrect={false}
          autoCapitalize="none"
        />
        {query.length > 0 ? (
          <Pressable onPress={() => setQuery("")} testID="tools-search-clear" hitSlop={12}>
            <Ionicons name="close-circle" size={18} color={colors.muted} />
          </Pressable>
        ) : null}
      </View>

      <ScrollView
        contentContainerStyle={{ padding: spacing.lg, paddingTop: spacing.sm, paddingBottom: spacing["3xl"] }}
        keyboardShouldPersistTaps="handled"
      >
        {filtered.length === 0 ? (
          <View style={styles.empty} testID="tools-empty">
            <Ionicons name="search-outline" size={28} color={colors.muted} />
            <Text style={styles.emptyText}>No tools match “{query}”.</Text>
          </View>
        ) : (
          filtered.map((s) => (
            <View key={s.key} style={styles.section} testID={`tools-section-${s.key}`}>
              <Text style={styles.sectionTitle}>{s.title}</Text>
              {s.tiles.map((t) => (
                <Tile key={t.key} tile={t} onPress={() => router.push(t.route as any)} />
              ))}
            </View>
          ))
        )}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  searchWrap: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    marginHorizontal: spacing.lg,
    marginTop: spacing.md,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    height: 44,
  },
  searchInput: {
    flex: 1,
    fontFamily: font.regular,
    fontSize: fontSize.base,
    color: colors.onSurface,
    ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}),
  },
  section: { marginTop: spacing.xl },
  sectionTitle: {
    fontFamily: font.semibold,
    fontSize: 11,
    letterSpacing: 1.2,
    textTransform: "uppercase",
    color: colors.onSurfaceSecondary,
    marginBottom: spacing.sm,
    paddingLeft: spacing.xs,
  },
  tile: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
    marginBottom: spacing.sm,
  },
  tileIcon: {
    width: 44,
    height: 44,
    borderRadius: radius.md,
    backgroundColor: colors.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
  },
  tileLabel: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  tileDesc: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
  empty: {
    alignItems: "center",
    justifyContent: "center",
    padding: spacing["3xl"],
    gap: spacing.sm,
  },
  emptyText: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted, textAlign: "center" },
});
