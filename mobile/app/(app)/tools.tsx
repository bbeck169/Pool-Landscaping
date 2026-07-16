/**
 * Phase 42 · Tools Hub redesign.
 *
 * Layout top→bottom:
 *   Header · SearchBar · PinnedRow · RecentRow · CategoryChips · Sections
 *
 * The 6-category admin IA (Phase 35) and 4-section tech IA are preserved
 * intact — this pass only adds surface-level personalization (pins,
 * recents, chip filter, search) plus a bigger-tap-target card style.
 * No tools move between categories; no RBAC gates are loosened.
 *
 * `useToolsPreferences` scopes pins/recents by user.id so a shared
 * device doesn't leak favorites across accounts. All persistence
 * happens AsyncStorage-side; if it fails we fall back gracefully to the
 * plain hub.
 */
import React, { useMemo, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { Header } from "@/src/components/widgets";
import { useAuth } from "@/src/auth";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { SearchBar } from "@/src/components/tools/SearchBar";
import { PinnedRow } from "@/src/components/tools/PinnedRow";
import { RecentRow } from "@/src/components/tools/RecentRow";
import { CategoryChips } from "@/src/components/tools/CategoryChips";
import { ToolCard, type ToolCardTile } from "@/src/components/tools/ToolCard";
import { useToolsPreferences } from "@/src/hooks/useToolsPreferences";

type Section = { key: string; title: string; tiles: ToolCardTile[] };

const TECH_SECTIONS: Section[] = [
  {
    key: "daily",
    title: "Daily Work",
    tiles: [
      { key: "schedule", icon: "today-outline", label: "Schedule", desc: "Day / Week / Month calendar", route: "/(app)/schedule/calendar" },
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
    key: "adm-finance",
    title: "Finance",
    tiles: [
      { key: "cfo", icon: "trending-up-outline", label: "AI CFO", desc: "Revenue · expenses · cash · AR", route: "/(app)/cfo" },
      { key: "checks", icon: "document-text-outline", label: "Check Register", desc: "Write checks, batch payroll", route: "/(app)/checks/register" },
      { key: "payroll-batch", icon: "cash-outline", label: "Payroll Batch + CSV", desc: "Batch checks & payroll import", route: "/(app)/payroll/batch" },
      { key: "dunning", icon: "mail-open-outline", label: "Dunning Queue", desc: "Overdue invoices workflow", route: "/(app)/dunning/queue" },
    ],
  },
  {
    key: "adm-ai-employees",
    title: "AI Employees",
    tiles: [
      { key: "ai-cfo-qna", icon: "chatbubbles-outline", label: "AI CFO Q&A", desc: "Ask the CFO — natural language", route: "/(app)/cfo" },
    ],
  },
  {
    key: "adm-marketing",
    title: "Marketing",
    tiles: [
      { key: "marketing-studio", icon: "megaphone-outline", label: "Marketing Studio", desc: "Campaigns, sequences, reviews", route: "/(app)/marketing" as any },
    ],
  },
  {
    key: "adm-operations",
    title: "Operations",
    tiles: [
      { key: "schedule", icon: "calendar-outline", label: "Schedule", desc: "Day/Week/Month/Custom", route: "/(app)/schedule/calendar" },
      { key: "dispatch-board", icon: "git-network-outline", label: "Dispatch Board", desc: "Auto-route unassigned jobs", route: "/(app)/dispatch/board" },
      { key: "dispatch-weather", icon: "cloud-outline", label: "Weather Reschedule", desc: "Move outdoor jobs on bad weather", route: "/(app)/dispatch/weather" },
      { key: "estimator", icon: "calculator-outline", label: "Field Estimator", desc: "Build a quote on-site", route: "/(app)/estimator" },
      { key: "calculators", icon: "flask-outline", label: "Pool Calculators", desc: "Dosing · Volume · Salt · LSI", route: "/(app)/calculators" },
      { key: "inventory", icon: "layers-outline", label: "Inventory", desc: "Stock & purchase orders", route: "/(app)/inventory" },
    ],
  },
  {
    key: "adm-customers",
    title: "Customers",
    tiles: [
      { key: "customers", icon: "people-outline", label: "Customers", desc: "Full customer directory", route: "/(app)/customers" },
      { key: "quotes", icon: "document-text-outline", label: "Quotes & Invoices", desc: "Send, sign, collect", route: "/(app)/quotes" },
      { key: "property-lookup", icon: "home-outline", label: "Property Lookup", desc: "Owner + lot size search", route: "/(app)/property-lookup" },
      { key: "business-card", icon: "id-card-outline", label: "My Business Card", desc: "NFC-ready digital card & .vcf", route: "/card" },
    ],
  },
  {
    key: "adm-reports",
    title: "Reports",
    tiles: [
      { key: "reports-hub", icon: "bar-chart-outline", label: "Reports Hub", desc: "Business summary & analytics", route: "/(app)/reports" as any },
    ],
  },
];

export default function ToolsHub() {
  const router = useRouter();
  const { user } = useAuth();
  const role = (user?.role as string) || "";
  const isAdmin = role === "admin" || role === "super_admin";
  const sections = isAdmin ? ADMIN_SECTIONS : TECH_SECTIONS;

  const [query, setQuery] = useState("");
  const [chip, setChip] = useState<string>("all");
  const { pins, recents, togglePin, markUsed, MAX_PINS } =
    useToolsPreferences(user?.id);

  // Flat universe (post-RBAC — role branch already picked one).
  const allTiles: ToolCardTile[] = useMemo(() => {
    const seen = new Set<string>();
    const flat: ToolCardTile[] = [];
    for (const s of sections) {
      for (const t of s.tiles) {
        if (seen.has(t.key)) continue;
        seen.add(t.key);
        flat.push(t);
      }
    }
    return flat;
  }, [sections]);

  const chipData = useMemo(
    () => sections.map((s) => ({ key: s.key, label: s.title })),
    [sections],
  );

  // Section list narrowed by (chip AND search).
  const filteredSections = useMemo(() => {
    const q = query.trim().toLowerCase();
    return sections
      .filter((s) => chip === "all" || s.key === chip)
      .map((s) => ({
        ...s,
        tiles: q
          ? s.tiles.filter(
              (t) =>
                t.label.toLowerCase().includes(q) ||
                t.desc.toLowerCase().includes(q),
            )
          : s.tiles,
      }))
      .filter((s) => s.tiles.length > 0);
  }, [sections, chip, query]);

  const totalTiles = allTiles.length;
  const openTile = (t: ToolCardTile) => {
    markUsed(t.key);
    router.push(t.route as any);
  };

  const anyResults = filteredSections.length > 0;

  return (
    <View style={styles.root}>
      <Header
        title="Tools"
        subtitle={
          isAdmin
            ? "Everything you can do — one screen"
            : `${totalTiles} tools available to you`
        }
      />
      <SearchBar onQueryChange={setQuery} />

      <ScrollView
        contentContainerStyle={{ paddingBottom: spacing["3xl"] }}
        keyboardShouldPersistTaps="handled"
      >
        {/* Personalization rows — hidden when the search bar is active so
            they don't compete with the filtered results the tech asked for. */}
        {!query ? (
          <>
            <PinnedRow
              allTiles={allTiles}
              pins={pins}
              onOpen={openTile}
              onTogglePin={togglePin}
              maxPins={MAX_PINS}
            />
            <RecentRow allTiles={allTiles} recents={recents} onOpen={openTile} />
          </>
        ) : null}

        <CategoryChips chips={chipData} selected={chip} onSelect={setChip} />

        <View style={styles.sectionsWrap}>
          {!anyResults ? (
            <View style={styles.empty} testID="tools-empty">
              <Ionicons name="search-outline" size={28} color={colors.muted} />
              <Text style={styles.emptyText}>
                No tools match{query ? ` “${query}”` : " the current filter"}.
              </Text>
              {(query || chip !== "all") ? (
                <Pressable
                  style={styles.emptyBtn}
                  onPress={() => { setQuery(""); setChip("all"); }}
                  testID="tools-empty-clear"
                >
                  <Text style={styles.emptyBtnText}>Clear filters</Text>
                </Pressable>
              ) : null}
            </View>
          ) : (
            filteredSections.map((s) => (
              <View key={s.key} style={styles.section} testID={`tools-section-${s.key}`}>
                <Text style={styles.sectionTitle}>{s.title}</Text>
                {s.tiles.map((t) => (
                  <ToolCard
                    key={t.key}
                    tile={t}
                    onPress={() => openTile(t)}
                    testIDPrefix="tools-card"
                  />
                ))}
              </View>
            ))
          )}
        </View>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  sectionsWrap: {
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.md,
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
  empty: {
    alignItems: "center",
    justifyContent: "center",
    padding: spacing["3xl"],
    gap: spacing.md,
  },
  emptyText: {
    fontFamily: font.medium,
    fontSize: fontSize.sm,
    color: colors.muted,
    textAlign: "center",
  },
  emptyBtn: {
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.brand,
  },
  emptyBtnText: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.brand,
  },
});
