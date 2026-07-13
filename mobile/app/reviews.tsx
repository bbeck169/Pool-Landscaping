import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, FlatList, RefreshControl, Pressable, TextInput, Platform, Alert } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Loading, EmptyState, PrimaryButton, Sheet } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";

function Stars({ n, size = 14 }: { n: number; size?: number }) {
  return (
    <View style={{ flexDirection: "row" }}>
      {[1, 2, 3, 4, 5].map((i) => (
        <Ionicons key={i} name={i <= n ? "star" : "star-outline"} size={size} color="#CA8A04" />
      ))}
    </View>
  );
}

export default function Reviews() {
  const [data, setData] = useState<any>({ items: [], average: 0, count: 0 });
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [sel, setSel] = useState<any>(null);
  const [response, setResponse] = useState("");

  const load = useCallback(async () => {
    try {
      setData(await api.get("/reviews"));
    } catch {
      setData({ items: [], average: 0, count: 0 });
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const openRespond = (r: any) => { setSel(r); setResponse(r.response || ""); };

  const submit = async () => {
    if (!response.trim()) { Alert.alert("Missing", "Write a response."); return; }
    try {
      await api.put(`/reviews/${sel.id}/respond`, { response });
      setSel(null);
      setResponse("");
      load();
    } catch (e: any) {
      Alert.alert("Error", e?.message || "Could not respond.");
    }
  };

  return (
    <View style={styles.root}>
      <Header title="Reviews" back subtitle="Ratings & responses" />
      {loading ? (
        <Loading testID="reviews-loading" />
      ) : (
        <FlatList
          testID="reviews-list"
          data={data.items}
          keyExtractor={(i) => i.id}
          ListHeaderComponent={
            data.count ? (
              <View style={styles.summary}>
                <Text style={styles.avg}>{data.average.toFixed(1)}</Text>
                <View>
                  <Stars n={Math.round(data.average)} size={18} />
                  <Text style={styles.count}>{data.count} reviews</Text>
                </View>
              </View>
            ) : null
          }
          contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
          ListEmptyComponent={<EmptyState icon="star-outline" title="No reviews yet" subtitle="Customer reviews will show up here." testID="reviews-empty" />}
          renderItem={({ item }) => (
            <View style={styles.card} testID={`review-${item.id}`}>
              <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
                <Text style={styles.name}>{item.customer_name}</Text>
                <View style={styles.sourcePill}>
                  <Text style={styles.sourceText}>{item.source}</Text>
                </View>
              </View>
              <View style={{ marginTop: 4 }}><Stars n={item.rating} /></View>
              <Text style={styles.text}>{item.text}</Text>
              {item.response ? (
                <View style={styles.responseBox}>
                  <Ionicons name="return-down-forward" size={14} color={colors.brand} />
                  <Text style={styles.responseText}>{item.response}</Text>
                </View>
              ) : (
                <Pressable style={styles.respondBtn} onPress={() => openRespond(item)} testID={`respond-${item.id}`}>
                  <Ionicons name="chatbox-outline" size={14} color={colors.brand} />
                  <Text style={styles.respondText}>Respond</Text>
                </Pressable>
              )}
            </View>
          )}
        />
      )}

      <Sheet visible={!!sel} onClose={() => setSel(null)} title="Respond to review" testID="respond-sheet">
        {sel ? (
          <>
            <Text style={styles.name}>{sel.customer_name}</Text>
            <View style={{ marginTop: 4 }}><Stars n={sel.rating} /></View>
            <Text style={styles.text}>{sel.text}</Text>
            <Text style={[styles.inputLabel, { marginTop: spacing.md }]}>YOUR RESPONSE</Text>
            <TextInput style={[styles.input, { height: 96, paddingTop: spacing.sm }]} value={response} onChangeText={setResponse} placeholder="Thank the customer…" placeholderTextColor={colors.muted} multiline testID="response-input" />
            <View style={{ height: spacing.md }} />
            <PrimaryButton title="Post Response" onPress={submit} testID="post-response-button" />
          </>
        ) : null}
      </Sheet>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  summary: { flexDirection: "row", alignItems: "center", gap: spacing.lg, backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.lg, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.md },
  avg: { fontFamily: font.bold, fontSize: 44, color: colors.onSurface },
  count: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
  card: { backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.lg, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.md },
  name: { fontFamily: font.semibold, fontSize: fontSize.lg, color: colors.onSurface },
  sourcePill: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.pill, paddingHorizontal: 10, paddingVertical: 4, borderWidth: 1, borderColor: colors.border },
  sourceText: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
  text: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurfaceSecondary, marginTop: spacing.sm },
  responseBox: { flexDirection: "row", gap: 6, backgroundColor: colors.brandTertiary, borderRadius: radius.md, padding: spacing.md, marginTop: spacing.sm },
  responseText: { flex: 1, fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onBrandTertiary },
  respondBtn: { flexDirection: "row", alignItems: "center", gap: 5, marginTop: spacing.sm, alignSelf: "flex-start" },
  respondText: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.brand },
  inputLabel: { fontFamily: font.semibold, fontSize: 11, letterSpacing: 0.8, color: colors.onSurfaceSecondary, marginBottom: spacing.xs },
  input: { backgroundColor: colors.surfaceSecondary, borderWidth: 1.5, borderColor: colors.border, borderRadius: radius.md, paddingHorizontal: spacing.md, fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}) },
});
