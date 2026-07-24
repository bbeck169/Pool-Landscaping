import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, FlatList, RefreshControl, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize, money } from "@/src/theme";
import { Loading, EmptyState, StatusChip } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";

export default function PortalEstimates() {
  const router = useRouter();
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setItems(await api.get(`/quotes?doc_type=quote`));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const decide = async (id: string, decision: "approve" | "decline") => {
    setBusy(id + decision);
    try {
      const updated = await api.post(`/quotes/${id}/decision?decision=${decision}`);
      setItems((prev) => prev.map((q) => (q.id === id ? updated : q)));
    } catch {}
    finally { setBusy(null); }
  };

  const isPending = (q: any) => q.status !== "accepted" && q.status !== "declined";

  return (
    <View style={styles.root}>
      <Header title="Estimates" subtitle="Review & approve quotes" back />
      {loading ? (
        <Loading testID="portal-estimates-loading" />
      ) : items.length === 0 ? (
        <EmptyState icon="document-text-outline" title="No estimates yet" subtitle="Quotes from our team will appear here." testID="portal-estimates-empty" />
      ) : (
        <FlatList
          testID="portal-estimates-list"
          data={items}
          keyExtractor={(i) => i.id}
          contentContainerStyle={{ padding: spacing.lg, paddingTop: spacing.sm, paddingBottom: spacing["3xl"] }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
          renderItem={({ item }) => (
            <View style={styles.card} testID={`portal-estimate-${item.id}`}>
              <Pressable onPress={() => router.push(`/estimate-view/${item.id}`)}>
                <View style={styles.topRow}>
                  <View style={styles.typeBadge}>
                    <Ionicons name="document-text-outline" size={16} color={colors.brand} />
                    <Text style={styles.typeText}>Estimate</Text>
                  </View>
                  <StatusChip status={item.status} />
                </View>
                <Text style={styles.title} numberOfLines={1}>{item.title}</Text>
                <Text style={styles.total}>{money(item.total)}</Text>
              </Pressable>
              {isPending(item) ? (
                <View style={styles.actions}>
                  <Pressable
                    style={[styles.btn, styles.decline]}
                    onPress={() => decide(item.id, "decline")}
                    disabled={!!busy}
                    testID={`estimate-decline-${item.id}`}
                  >
                    <Ionicons name="close" size={16} color={colors.error} />
                    <Text style={[styles.btnText, { color: colors.error }]}>{busy === item.id + "decline" ? "…" : "Decline"}</Text>
                  </Pressable>
                  <Pressable
                    style={[styles.btn, styles.approve]}
                    onPress={() => decide(item.id, "approve")}
                    disabled={!!busy}
                    testID={`estimate-approve-${item.id}`}
                  >
                    <Ionicons name="checkmark" size={16} color="#fff" />
                    <Text style={[styles.btnText, { color: "#fff" }]}>{busy === item.id + "approve" ? "…" : "Approve"}</Text>
                  </Pressable>
                </View>
              ) : null}
            </View>
          )}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  card: { backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.lg, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.md, gap: 4 },
  topRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 4 },
  typeBadge: { flexDirection: "row", alignItems: "center", gap: 5 },
  typeText: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.brand },
  title: { fontFamily: font.semibold, fontSize: fontSize.lg, color: colors.onSurface },
  total: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface, marginTop: 2 },
  actions: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.md },
  btn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, height: 44, borderRadius: radius.md },
  approve: { backgroundColor: colors.brand },
  decline: { backgroundColor: colors.surface, borderWidth: 1.5, borderColor: colors.error },
  btnText: { fontFamily: font.semibold, fontSize: fontSize.base },
});
