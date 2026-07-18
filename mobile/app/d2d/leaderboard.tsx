import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, FlatList, RefreshControl } from "react-native";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Loading, EmptyState } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";

const MEDAL = ["🥇", "🥈", "🥉"];

export default function D2DLeaderboard() {
  const [reps, setReps] = useState<any[] | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try { setReps(await api.get("/d2d/leaderboard")); } catch { setReps([]); }
    finally { setRefreshing(false); }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  if (reps === null) return <Loading testID="d2d-leaderboard-loading" />;

  return (
    <View style={styles.root}>
      <Header title="D2D Leaderboard" back subtitle="Sold · conversions · knocks" />
      {reps.length === 0 ? (
        <EmptyState icon="trophy-outline" title="No activity yet" subtitle="Log doors to climb the board." testID="d2d-leaderboard-empty" />
      ) : (
        <FlatList
          testID="d2d-leaderboard-list"
          data={reps}
          keyExtractor={(r) => r.tech_id}
          contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
          renderItem={({ item }) => (
            <View style={[styles.row, item.is_me && styles.rowMe]} testID={`d2d-rank-${item.tech_id}`}>
              <Text style={styles.rank}>{MEDAL[item.rank - 1] || `#${item.rank}`}</Text>
              <View style={{ flex: 1 }}>
                <Text style={styles.name}>{item.tech_name}{item.is_me ? " (you)" : ""}</Text>
                <Text style={styles.meta}>{item.knocks} knocks · {item.leads} leads · {item.conversion_rate}% conv.</Text>
              </View>
              <View style={styles.soldBox}>
                <Text style={styles.soldNum}>{item.sold}</Text>
                <Text style={styles.soldLabel}>sold</Text>
              </View>
            </View>
          )}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.md, backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.sm },
  rowMe: { borderColor: colors.brand, borderWidth: 2, backgroundColor: colors.brandTertiary },
  rank: { fontFamily: font.bold, fontSize: fontSize.xl, width: 40, textAlign: "center", color: colors.onSurface },
  name: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  meta: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 1 },
  soldBox: { alignItems: "center", minWidth: 44 },
  soldNum: { fontFamily: font.bold, fontSize: fontSize.xl, color: "#16A34A" },
  soldLabel: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted },
});
