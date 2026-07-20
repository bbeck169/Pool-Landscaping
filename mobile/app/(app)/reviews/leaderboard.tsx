/** Tech leaderboard — Phase 3 mobile. */
import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, FlatList, ActivityIndicator, RefreshControl } from "react-native";
import { useFocusEffect } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { Header } from "@/src/components/widgets";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";
import { getLeaderboard } from "@/src/api/reviews";
import { StarRatingDisplayNative } from "@/src/components/reviews/StarRatingDisplayNative";

export default function ReviewsLeaderboardScreen() {
  const [rows, setRows] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const reload = useCallback((silent = false) => {
    if (!silent) setLoading(true);
    getLeaderboard(1).then(setRows).catch(() => setRows([])).finally(() => { setLoading(false); setRefreshing(false); });
  }, []);

  useFocusEffect(useCallback(() => { reload(); }, [reload]));

  return (
    <View style={styles.root} testID="reviews-leaderboard">
      <Header title="Tech Leaderboard" subtitle="Ranked by average star" back />
      {loading ? <ActivityIndicator style={{ marginTop: 40 }} color={colors.brand} /> : (
        <FlatList
          data={rows}
          keyExtractor={(item) => item.technician_id}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); reload(true); }} />}
          contentContainerStyle={{ padding: spacing.lg }}
          renderItem={({ item, index }) => (
            <View style={styles.row} testID={`reviews-leaderboard-row-${item.technician_id}`}>
              <View style={[styles.medal, index === 0 && styles.gold, index === 1 && styles.silver, index === 2 && styles.bronze]}>
                <Text style={styles.medalText}>#{index + 1}</Text>
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.name}>{item.technician_name}</Text>
                <View style={styles.starRow}>
                  <StarRatingDisplayNative value={item.avg_star} size={12} showValue />
                  <Text style={styles.metaDot}>·</Text>
                  <Text style={styles.meta}>{item.review_count} reviews</Text>
                  <Text style={styles.metaDot}>·</Text>
                  <Text style={styles.meta}>{item.five_star_count} five-star</Text>
                </View>
              </View>
            </View>
          )}
          ListEmptyComponent={
            <View style={styles.empty}>
              <Ionicons name="trophy-outline" size={30} color={colors.muted} />
              <Text style={styles.emptyText}>No qualifying techs yet</Text>
              <Text style={styles.emptyHint}>Techs need at least 1 review to appear here.</Text>
            </View>
          }
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.md, backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.lg, marginBottom: spacing.sm, borderWidth: 1, borderColor: colors.border },
  medal: { width: 36, height: 36, borderRadius: 18, backgroundColor: colors.border, alignItems: "center", justifyContent: "center" },
  gold: { backgroundColor: "#FEF3C7" },
  silver: { backgroundColor: "#E5E7EB" },
  bronze: { backgroundColor: "#FDE68A" },
  medalText: { fontFamily: font.bold, fontSize: 11, color: colors.onSurface },
  name: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface, marginBottom: 2 },
  starRow: { flexDirection: "row", alignItems: "center", gap: 4 },
  meta: { fontFamily: font.regular, fontSize: 11, color: colors.muted },
  metaDot: { color: colors.muted },
  empty: { alignItems: "center", paddingTop: 60, gap: 6 },
  emptyText: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  emptyHint: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, textAlign: "center" },
});
