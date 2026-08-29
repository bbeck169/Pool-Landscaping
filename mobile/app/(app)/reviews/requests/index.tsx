/** Reviews Requests list — Phase 3 mobile. */
import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, FlatList, TouchableOpacity, ActivityIndicator, RefreshControl } from "react-native";
import { useRouter, useFocusEffect } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { Header } from "@/src/components/widgets";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";
import { listRequests, OUTCOMES } from "@/src/api/reviews";
import { OutcomePillNative } from "@/src/components/reviews/OutcomePillNative";
import { StarRatingDisplayNative } from "@/src/components/reviews/StarRatingDisplayNative";
import { formatCustomerName } from "@/src/utils/formatCustomerName";

export default function ReviewsRequestsListScreen() {
  const router = useRouter();
  const [rows, setRows] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [filter, setFilter] = useState("");

  const reload = useCallback((silent = false) => {
    if (!silent) setLoading(true);
    listRequests(filter ? { status: filter } : {})
      .then((d) => setRows(d))
      .catch(() => setRows([]))
      .finally(() => { setLoading(false); setRefreshing(false); });
  }, [filter]);

  useFocusEffect(useCallback(() => { reload(); }, [reload]));

  return (
    <View style={styles.root} testID="reviews-requests-list">
      <Header title="Review Requests" subtitle={`${rows.length} total`} back />
      {/* Filter chips */}
      <View style={styles.chips}>
        <TouchableOpacity
          testID="reviews-filter-all"
          style={[styles.chip, !filter && styles.chipActive]}
          onPress={() => setFilter("")}
        >
          <Text style={[styles.chipLabel, !filter && styles.chipLabelActive]}>All</Text>
        </TouchableOpacity>
        {OUTCOMES.map((o) => (
          <TouchableOpacity
            key={o.code}
            testID={`reviews-filter-${o.code}`}
            style={[styles.chip, filter === o.code && styles.chipActive]}
            onPress={() => setFilter(o.code)}
          >
            <Text style={[styles.chipLabel, filter === o.code && styles.chipLabelActive]}>{o.label}</Text>
          </TouchableOpacity>
        ))}
      </View>
      {loading ? (
        <ActivityIndicator style={{ marginTop: 40 }} color={colors.brand} />
      ) : (
        <FlatList
          data={rows}
          keyExtractor={(item) => item.id}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); reload(true); }} />}
          contentContainerStyle={{ padding: spacing.lg }}
          renderItem={({ item }) => (
            <TouchableOpacity
              testID={`reviews-request-row-${item.id}`}
              style={styles.row}
              activeOpacity={0.7}
              onPress={() => router.push({ pathname: "/(app)/reviews/requests/[id]", params: { id: item.id } })}
            >
              <View style={styles.rowTop}>
                <Text style={styles.rowName} numberOfLines={1}>{formatCustomerName(item)}</Text>
                <OutcomePillNative outcome={item.outcome} />
              </View>
              <Text style={styles.rowMeta} numberOfLines={1}>
                {item.technician_name || "unassigned"} · {(item.sent_via || "").replace("_", " ")}
              </Text>
              <View style={styles.rowFoot}>
                <Text style={styles.rowDate}>{(item.sent_at || "").slice(0, 10)}</Text>
                {item.star_rating_submitted ? <StarRatingDisplayNative value={item.star_rating_submitted} size={11} /> : null}
              </View>
            </TouchableOpacity>
          )}
          ListEmptyComponent={
            <View style={styles.empty}>
              <Ionicons name="send-outline" size={30} color={colors.muted} />
              <Text style={styles.emptyText}>No review requests</Text>
            </View>
          }
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 6, padding: spacing.lg, paddingBottom: 0 },
  chip: {
    backgroundColor: colors.surfaceSecondary, borderWidth: 1,
    borderColor: colors.border, paddingHorizontal: 10, paddingVertical: 4,
    borderRadius: 999,
  },
  chipActive: { backgroundColor: colors.brand, borderColor: colors.brand },
  chipLabel: { fontFamily: font.medium, fontSize: 11, color: colors.onSurface },
  chipLabelActive: { color: "#fff" },
  row: {
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.md,
    padding: spacing.lg, marginBottom: spacing.sm,
    borderWidth: 1, borderColor: colors.border,
  },
  rowTop: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 4 },
  rowName: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface, flex: 1, marginRight: 8 },
  rowMeta: { fontFamily: font.regular, fontSize: 11, color: colors.muted, marginBottom: 4, textTransform: "capitalize" },
  rowFoot: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  rowDate: { fontFamily: font.regular, fontSize: 10, color: colors.muted },
  empty: { alignItems: "center", paddingTop: 60, gap: 6 },
  emptyText: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted },
});
