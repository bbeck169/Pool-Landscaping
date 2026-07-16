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

type Props = {
  variant?: "tab" | "sheet";
  onNavigate?: (tile: ToolCardTile) => void;
};

export const ToolsMenuBody: React.FC<Props> = ({ variant = "tab", onNavigate }) => {
  const router = useRouter();
  const { user } = useAuth();
  const role = (user?.role as string) || "";
  const sections = useMemo(() => sectionsForRole(role), [role]);
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

  return (
    <View style={styles.wrap}>
      <SearchBar onQueryChange={setQuery} testID={searchTestID} />
      <ScrollView
        contentContainerStyle={{ paddingBottom: spacing["3xl"] }}
        keyboardShouldPersistTaps="handled"
      >
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
