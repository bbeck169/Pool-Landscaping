/**
 * TD-90 · grouped backend results under the tools matches (web
 * `GlobalSearchBar` order: Customers · Jobs · Invoices · Quotes · Leads).
 * Copy mirrors web: "Searching…" while in flight, `No results for "<q>"`
 * when nothing (tools included) matches. On error the previous buckets
 * stay and one muted line is added (web keeps buckets silently).
 */
import React from "react";
import { View, Text, ActivityIndicator, StyleSheet } from "react-native";
import { colors, spacing, font, fontSize } from "@/src/theme";
import type { SearchBuckets, SearchHit } from "@/src/hooks/useGlobalSearch";
import { GLOBAL_SEARCH_GROUPS, type SearchKind } from "@/src/lib/globalSearchRoutes";
import GlobalSearchRow from "./GlobalSearchRow";

type Props = {
  query: string;
  buckets: SearchBuckets;
  loading: boolean;
  error: boolean;
  total: number;
  hasToolMatches: boolean;
  onOpen: (kind: SearchKind, hit: SearchHit) => void;
};

export default function GlobalSearchResults({ query, buckets, loading, error, total, hasToolMatches, onOpen }: Props) {
  return (
    <View testID="global-search-results">
      {loading ? (
        <View style={s.status} testID="global-search-loading">
          <ActivityIndicator size="small" color={colors.brand} />
          <Text style={s.statusText}>Searching…</Text>
        </View>
      ) : null}
      {error ? (
        <Text style={s.statusText} testID="global-search-error">Couldn’t search right now — showing the last results.</Text>
      ) : null}
      {GLOBAL_SEARCH_GROUPS.filter((g) => buckets[g.key].length > 0).map((g) => (
        <View key={g.key} style={s.group} testID={`global-search-group-${g.key}`}>
          <Text style={s.title}>{g.label}</Text>
          {buckets[g.key].map((hit) => (
            <GlobalSearchRow key={`${g.kind}-${hit.id}`} kind={g.kind} icon={g.icon} hit={hit} onPress={() => onOpen(g.kind, hit)} />
          ))}
        </View>
      ))}
      {!loading && !error && total === 0 && !hasToolMatches ? (
        <Text style={s.empty} testID="global-search-empty">{`No results for “${query.trim()}”`}</Text>
      ) : null}
    </View>
  );
}

const s = StyleSheet.create({
  status: { flexDirection: "row", alignItems: "center", gap: spacing.sm, marginTop: spacing.lg },
  statusText: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted, marginTop: spacing.md },
  group: { marginTop: spacing.xl },
  title: {
    fontFamily: font.semibold, fontSize: 11, letterSpacing: 1.2, textTransform: "uppercase",
    color: colors.onSurfaceSecondary, marginBottom: spacing.sm, paddingLeft: spacing.xs,
  },
  empty: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted, textAlign: "center", padding: spacing["3xl"] },
});
