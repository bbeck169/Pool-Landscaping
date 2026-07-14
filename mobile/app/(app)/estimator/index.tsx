/** Phase 21 · Mobile — Field Estimator list. */
import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter, useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";

const STATUS_TONE: Record<string, { bg: string; fg: string }> = {
  draft:     { bg: "#FEF3C7", fg: "#92400E" },
  generated: { bg: "#DBEAFE", fg: "#1E40AF" },
  edited:    { bg: "#E9D5FF", fg: "#6B21A8" },
  converted: { bg: "#DCFCE7", fg: "#166534" },
  sent:      { bg: "#DCFCE7", fg: "#166534" },
};

export default function EstimatorListMobile() {
  const router = useRouter();
  const [rows, setRows] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const r = await api.get("/estimator/estimates");
      setRows(r.items || []);
    } finally { setLoading(false); }
  };
  useFocusEffect(useCallback(() => { load(); }, []));

  return (
    <View style={styles.root}>
      <Header title="Field Estimator" />
      <ScrollView contentContainerStyle={{ padding: spacing.lg,
                                             paddingBottom: 120 }}>
        {loading ? (
          <ActivityIndicator color={colors.brand} />
        ) : rows.length === 0 ? (
          <View style={styles.empty}>
            <Ionicons name="calculator-outline" size={28}
                       color={colors.muted} />
            <Text style={styles.emptyTitle}>No estimates yet</Text>
            <Text style={styles.emptyBody}>
              Tap + to snap photos and get an AI-priced estimate.
            </Text>
          </View>
        ) : rows.map((r) => {
          const tone = STATUS_TONE[r.status] || STATUS_TONE.draft;
          return (
            <Pressable key={r.id}
                       onPress={() => router.push(
                         `/(app)/estimator/${r.id}` as any)}
                       style={styles.card}
                       testID={`est-row-${r.id}`}>
              <View style={{ flex: 1, minWidth: 0 }}>
                <Text style={styles.title} numberOfLines={1}>{r.title}</Text>
                <Text style={styles.meta}>
                  {r.service_type} · {(r.created_at || "").slice(0, 10)}
                </Text>
              </View>
              <View style={{ alignItems: "flex-end", gap: 4 }}>
                <Text style={styles.total}>
                  ${(r.total || 0).toFixed(0)}
                </Text>
                <View style={[styles.pill,
                                { backgroundColor: tone.bg }]}>
                  <Text style={[styles.pillText, { color: tone.fg }]}>
                    {r.status}
                  </Text>
                </View>
              </View>
              <Ionicons name="chevron-forward" size={16}
                         color={colors.muted} />
            </Pressable>
          );
        })}
      </ScrollView>

      <Pressable style={styles.fab}
                 onPress={() => router.push("/(app)/estimator/new" as any)}
                 testID="est-new-fab">
        <Ionicons name="add" size={26} color="#fff" />
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  empty: { padding: spacing["2xl"], alignItems: "center", gap: spacing.sm },
  emptyTitle: { fontFamily: font.bold, fontSize: fontSize.lg,
                 color: colors.onSurface, marginTop: spacing.sm },
  emptyBody: { fontFamily: font.regular, fontSize: fontSize.base,
                color: colors.muted, textAlign: "center" },
  card: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    padding: spacing.md, backgroundColor: colors.surface,
    borderRadius: radius.md, borderWidth: 1,
    borderColor: colors.border, marginBottom: spacing.sm,
  },
  title: { fontFamily: font.bold, fontSize: fontSize.base,
            color: colors.onSurface },
  meta: { fontFamily: font.regular, fontSize: fontSize.sm,
           color: colors.muted, marginTop: 2 },
  total: { fontFamily: font.bold, fontSize: fontSize.base,
            color: colors.onSurface },
  pill: { paddingHorizontal: 8, paddingVertical: 2, borderRadius: 999 },
  pillText: { fontFamily: font.bold, fontSize: 9,
               textTransform: "uppercase" },
  fab: {
    position: "absolute", right: spacing.lg, bottom: spacing.xl,
    width: 56, height: 56, borderRadius: 28,
    backgroundColor: colors.brand,
    alignItems: "center", justifyContent: "center",
    shadowColor: "#000", shadowOpacity: 0.2, shadowRadius: 4,
    shadowOffset: { width: 0, height: 2 }, elevation: 4,
  },
});
