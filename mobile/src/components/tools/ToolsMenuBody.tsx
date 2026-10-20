/**
 * Phase 42 / Phase 43 — shared body of the Tools screen AND the global
 * dropdown sheet.
 *
 * Composes: SearchBar → PinnedRow → RecentRow → CategoryChips →
 * filtered category sections. Both surfaces render this component so
 * pins, recents, search, and chip-filter behavior stay in lock-step.
 *
 * Two configurable knobs distinguish tab vs. sheet:
 *   `variant="tab"` — original Phase 42 look; shows the pins & recents
 *                     empty states inline; testIDs match `tools-*`.
 *   `variant="sheet"` — inside the dropdown; SUPPRESSES the empty
 *                       states for pins/recents (per Phase 43 spec:
 *                       "hide the section entirely, not the empty
 *                       state"); search testID becomes
 *                       `mobile-menu-search`.
 *
 * `onNavigate` is called just before `router.push()` so the sheet can
 * close itself before navigation kicks in — Phase 42's Tools tab
 * leaves it undefined (nothing to close).
 */
import React, { useMemo, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { useAuth } from "@/src/auth";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { SearchBar } from "./SearchBar";
import { PinnedRow } from "./PinnedRow";
import { RecentRow } from "./RecentRow";
import { CategoryChips } from "./CategoryChips";
import { ToolCard, type ToolCardTile } from "./ToolCard";
import { sectionsForRole } from "./sections";
import { useToolsPreferences } from "@/src/hooks/useToolsPreferences";
import { useGlobalSearch, canGlobalSearch, type SearchHit } from "@/src/hooks/useGlobalSearch";
import { routeForSearchHit, type SearchKind } from "@/src/lib/globalSearchRoutes";
import GlobalSearchResults from "@/src/components/search/GlobalSearchResults";

// TD-90 · global-search placeholder for dashboard roles (both surfaces).
export const GLOBAL_SEARCH_PLACEHOLDER = "Search customers, jobs, invoices, quotes…";

type Props = {
  variant?: "tab" | "sheet";
  onNavigate?: (tile: ToolCardTile) => void;
  quickAccessRole?: string;
};

export const ToolsMenuBody: React.FC<Props> = ({ variant = "tab", onNavigate, quickAccessRole }) => {
  const router = useRouter();
  const { user } = useAuth();
  const role = (user?.role as string) || "";
  const sections = useMemo(() => sectionsForRole(role, user as any), [role, user]);
  const searchTestID = variant === "sheet" ? "mobile-menu-search" : "tools-search";
  const inSheet = variant === "sheet";

  const [query, setQuery] = useState("");
  const [chip, setChip] = useState<string>("all");
  const { pins, recents, togglePin, markUsed, MAX_PINS } =
    useToolsPreferences(user?.id);

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

  const openTile = (t: ToolCardTile) => {
    markUsed(t.key);
    if (onNavigate) onNavigate(t);
    // Sheet callers navigate themselves after closing so we don't
    // start a route push while an animation is still playing.
    if (!onNavigate) router.push(t.route as any);
  };

  const anyResults = filteredSections.length > 0;
  const showPins = !query && (!inSheet || pins.length > 0);
  const showRecents = !query && (!inSheet || recents.length > 0);

  // TD-90 · global search (menu sheet AND Tools tab share this body).
  // Techs / non-dashboard roles stay tools-only (G1) — no fetch.
  const globalCapable = canGlobalSearch(role);
  const gs = useGlobalSearch(query, role);
  const openHit = (kind: SearchKind, hit: SearchHit) => {
    const route = routeForSearchHit(kind, hit.id);
    if (!route) return;
    // Not routed through openTile → search hits never pollute recents.
    if (onNavigate) onNavigate({ key: `search-${kind}-${hit.id}`, route, label: hit.primary, desc: hit.secondary || "", icon: "search-outline" } as any);
    else router.push(route as any);
  };

  return (
    <View style={styles.wrap}>
      <SearchBar onQueryChange={setQuery} testID={searchTestID}
        placeholder={globalCapable ? GLOBAL_SEARCH_PLACEHOLDER : undefined}
        debounceMs={globalCapable ? 0 : undefined} />
      {/* Queue Item 6 · Feb-2026 — Dashboard shortcut. Rendered
          directly under the search input on every drawer/tab so
          a Home affordance always sits at the top of the mobile
          menu. Hidden mid-search so search results stay tidy. */}
      {!query ? (
        <Pressable
          onPress={() => {
            const route = "/(app)" as any;
            if (onNavigate) {
              onNavigate({
                key: "dashboard", route,
                label: "Dashboard", desc: "", icon: "home-outline",
              } as any);
            } else {
              router.push(route);
            }
          }}
          style={dashStyles.row}
          testID="mobile-menu-dashboard-link"
        >
          <Ionicons name="home-outline" size={16} color={colors.onSurface} />
          <Text style={dashStyles.label}>Dashboard</Text>
          <Ionicons name="chevron-forward" size={14} color={colors.muted} />
        </Pressable>
      ) : null}
      <ScrollView
        contentContainerStyle={{ paddingBottom: spacing["3xl"] }}
        keyboardShouldPersistTaps="handled"
      >
        {/* Phase 55 · Quick Access — pinned shortcut chips at the top
            of the sheet. RBAC-gated per entry using the same role
            semantics as the web top bar. Suppressed entirely when a
            role has zero visible items so no empty container renders. */}
        {quickAccessRole ? (
          <QuickAccessChips role={quickAccessRole}
                             onNavigate={(route) => {
                               if (onNavigate) onNavigate({ key: `qa-${route}`, route, label: "", desc: "", icon: "flash-outline" } as any);
                               else router.push(route as any);
                             }} />
        ) : null}
        {showPins ? (
          <PinnedRow
            allTiles={allTiles}
            pins={pins}
            onOpen={openTile}
            onTogglePin={togglePin}
            maxPins={MAX_PINS}
          />
        ) : null}
        {showRecents ? (
          <RecentRow allTiles={allTiles} recents={recents} onOpen={openTile} />
        ) : null}

        <CategoryChips chips={chipData} selected={chip} onSelect={setChip} />

        <View style={styles.sectionsWrap}>
          {!anyResults && !gs.active ? (
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
                    pinned={pins.includes(t.key)}
                    onTogglePin={() => togglePin(t.key)}
                  />
                ))}
              </View>
            ))
          )}
          {gs.active ? (
            <GlobalSearchResults query={query} buckets={gs.buckets} loading={gs.loading} error={gs.error}
              total={gs.total} hasToolMatches={anyResults} onOpen={openHit} />
          ) : null}
        </View>
      </ScrollView>
    </View>
  );
};

const styles = StyleSheet.create({
  wrap: { flex: 1 },
  sectionsWrap: { paddingHorizontal: spacing.lg, paddingTop: spacing.md },
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

// Phase 55 · Quick Access horizontally-scrolling chip row.
// Renders at the top of the sheet, before Pinned / Recents / chips.
// RBAC-gated per item — hides the whole strip when a role has zero
// visible entries so no empty container renders.
const QUICK_ACCESS_ITEMS: {
  route: string; label: string; icon: React.ComponentProps<typeof Ionicons>["name"];
  roles: string[];
}[] = [
  { route: "/(app)/customers",         label: "Customers",   icon: "people-outline",       roles: ["admin", "super_admin"] },
  { route: "/invoices",                label: "Invoices",    icon: "receipt-outline",       roles: ["admin", "super_admin"] },
  { route: "/(app)/estimator",         label: "Estimates",   icon: "document-text-outline", roles: ["admin", "super_admin"] },
  { route: "/(app)/schedule/calendar",  label: "Schedule",    icon: "calendar-outline",      roles: ["admin", "super_admin", "technician"] },
  { route: "/(app)/jobs",               label: "Workstream",  icon: "list-outline",          roles: ["admin", "super_admin", "technician", "customer"] },
];

function QuickAccessChips({ role, onNavigate }: { role: string; onNavigate: (r: string) => void }) {
  const visible = QUICK_ACCESS_ITEMS.filter((it) => it.roles.includes(role));
  if (visible.length === 0) return null;
  return (
    <View style={qaStyles.wrap} testID="mobile-menu-quick-access">
      <Text style={qaStyles.label}>Quick Access</Text>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={qaStyles.row}>
        {visible.map((it) => (
          <Pressable
            key={it.route}
            onPress={() => onNavigate(it.route)}
            style={qaStyles.chip}
            testID={`quick-access-${it.label.toLowerCase()}`}
          >
            <Ionicons name={it.icon} size={14} color="#fff" />
            <Text style={qaStyles.chipText}>{it.label}</Text>
          </Pressable>
        ))}
      </ScrollView>
    </View>
  );
}

const qaStyles = StyleSheet.create({
  wrap: {
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.md,
    paddingBottom: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    backgroundColor: colors.surfaceSecondary,
  },
  label: {
    fontFamily: font.semibold, fontSize: 10, letterSpacing: 1.2,
    textTransform: "uppercase", color: colors.muted, marginBottom: spacing.sm,
  },
  row: { gap: spacing.sm, flexDirection: "row" },
  chip: {
    flexDirection: "row", alignItems: "center", gap: 4,
    backgroundColor: colors.brand,
    paddingHorizontal: spacing.md, paddingVertical: 8,
    borderRadius: radius.pill, marginRight: spacing.sm,
  },
  chipText: { fontFamily: font.bold, fontSize: 12, color: "#fff" },
});

// Queue Item 6 · Feb-2026 — Dashboard shortcut row styling. Matches
// the visual density of the search input above so the two feel
// like a stacked pair.
const dashStyles = StyleSheet.create({
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    marginHorizontal: spacing.lg,
    marginTop: spacing.sm,
    marginBottom: spacing.xs,
    paddingHorizontal: spacing.md,
    paddingVertical: 10,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  label: {
    flex: 1,
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.onSurface,
  },
});