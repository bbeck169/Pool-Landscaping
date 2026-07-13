import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, FlatList, RefreshControl, Pressable, Alert } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Loading, EmptyState } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";

export default function EstimateTemplates() {
  const [templates, setTemplates] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try { setTemplates(await api.get("/estimate-templates")); }
    catch { setTemplates([]); }
    finally { setLoading(false); setRefreshing(false); }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const remove = (t: any) => {
    Alert.alert("Delete template", `Remove "${t.name}"?`, [
      { text: "Cancel", style: "cancel" },
      { text: "Delete", style: "destructive", onPress: async () => { await api.del(`/estimate-templates/${t.id}`); load(); } },
    ]);
  };

  return (
    <View style={styles.root}>
      <Header title="Estimate Templates" back subtitle="Reusable cost breakdowns" />
      {loading ? (
        <Loading testID="templates-loading" />
      ) : templates.length === 0 ? (
        <EmptyState icon="albums-outline" title="No templates" subtitle="Save an estimate as a template to reuse it." testID="templates-empty" />
      ) : (
        <FlatList
          testID="templates-list"
          data={templates}
          keyExtractor={(t) => t.id}
          contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
          renderItem={({ item }) => (
            <View style={styles.card} testID={`template-${item.id}`}>
              <View style={[styles.dot, { backgroundColor: item.prebuilt ? "#0284C7" : "#7C3AED" }]}>
                <Ionicons name={item.prebuilt ? "star" : "albums"} size={15} color="#fff" />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.cardTitle} numberOfLines={1}>{item.name}</Text>
                <Text style={styles.cardMeta}>{(item.line_items || []).length} items · OH {item.overhead_pct}% · Margin {item.margin_pct}%{item.prebuilt ? " · Prebuilt" : ""}</Text>
              </View>
              {!item.prebuilt ? (
                <Pressable hitSlop={10} onPress={() => remove(item)} testID={`template-delete-${item.id}`}>
                  <Ionicons name="trash-outline" size={19} color={colors.error} />
                </Pressable>
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
  card: { flexDirection: "row", alignItems: "center", gap: spacing.md, backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.sm },
  dot: { width: 32, height: 32, borderRadius: 16, alignItems: "center", justifyContent: "center" },
  cardTitle: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  cardMeta: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
});
