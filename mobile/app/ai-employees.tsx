import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, FlatList, RefreshControl, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Loading, EmptyState } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";

export default function AIEmployees() {
  const router = useRouter();
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      setItems(await api.get("/ai-employees"));
    } catch {
      setItems([]);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  return (
    <View style={styles.root}>
      <Header title="AI Employees" back subtitle="Your always-on AI team" />
      {loading ? (
        <Loading testID="ai-loading" />
      ) : items.length === 0 ? (
        <EmptyState icon="sparkles-outline" title="No AI employees" testID="ai-empty" />
      ) : (
        <FlatList
          testID="ai-employees-list"
          data={items}
          keyExtractor={(i) => i.id}
          contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
          renderItem={({ item }) => (
            <Pressable
              style={styles.card}
              onPress={() => router.push({ pathname: "/ai-chat/[id]", params: { id: item.id, name: item.name, role: item.role } })}
              testID={`ai-employee-${item.id}`}
            >
              <View style={styles.avatar}>
                <Ionicons name={item.icon as any} size={24} color="#fff" />
              </View>
              <View style={{ flex: 1 }}>
                <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                  <Text style={styles.name}>{item.name}</Text>
                  <View style={styles.aiBadge}>
                    <Ionicons name="sparkles" size={10} color={colors.brand} />
                    <Text style={styles.aiBadgeText}>AI</Text>
                  </View>
                </View>
                <Text style={styles.role}>{item.role}</Text>
                <Text style={styles.tagline}>{item.tagline}</Text>
              </View>
              <Ionicons name="chevron-forward" size={20} color={colors.muted} />
            </Pressable>
          )}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  card: { flexDirection: "row", alignItems: "center", gap: spacing.md, backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.lg, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.md },
  avatar: { width: 52, height: 52, borderRadius: 26, backgroundColor: colors.brand, alignItems: "center", justifyContent: "center" },
  name: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  aiBadge: { flexDirection: "row", alignItems: "center", gap: 2, backgroundColor: colors.brandTertiary, paddingHorizontal: 6, paddingVertical: 2, borderRadius: radius.pill },
  aiBadgeText: { fontFamily: font.bold, fontSize: 9, color: colors.brand },
  role: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.brand, marginTop: 1 },
  tagline: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
});
