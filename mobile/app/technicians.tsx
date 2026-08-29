import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, FlatList, RefreshControl, Pressable } from "react-native";
import { Image } from "expo-image";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";

import { api } from "@/src/api";
import { writeCache, readCache } from "@/src/services/readCache";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Loading, EmptyState } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";

export default function Technicians() {
  const router = useRouter();
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await api.get("/technicians");
      setItems(data);
      writeCache("technicians", data).catch(() => {});
    } catch {
      const cached = await readCache<any[]>("technicians");
      if (cached) setItems(cached);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load])
  );

  return (
    <View style={styles.root}>
      <Header title="Technicians" back />
      {loading ? (
        <Loading testID="technicians-loading" />
      ) : items.length === 0 ? (
        <EmptyState icon="construct-outline" title="No technicians" testID="technicians-empty" />
      ) : (
        <FlatList
          testID="technicians-list"
          data={items}
          keyExtractor={(i) => i.id}
          contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
          renderItem={({ item }) => (
            <Pressable style={styles.row} onPress={() => router.push(`/technician/${item.id}`)} testID={`technician-row-${item.id}`}>
              {item.avatar ? (
                <Image source={{ uri: item.avatar }} style={styles.avatar} />
              ) : (
                <View style={[styles.avatar, styles.fallback]}>
                  <Ionicons name="person" size={22} color={colors.muted} />
                </View>
              )}
              <View style={{ flex: 1 }}>
                <Text style={styles.name}>{item.name}</Text>
                <Text style={styles.sub}>{item.specialty}</Text>
              </View>
              <View style={styles.badge}>
                <Text style={styles.badgeText}>{item.active_jobs} active</Text>
              </View>
            </Pressable>
          )}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  row: {
    flexDirection: "row", alignItems: "center", gap: spacing.md,
    backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.md,
    borderWidth: 1, borderColor: colors.border, marginBottom: spacing.sm,
  },
  avatar: { width: 52, height: 52, borderRadius: 26, backgroundColor: colors.surfaceTertiary },
  fallback: { alignItems: "center", justifyContent: "center" },
  name: { fontFamily: font.semibold, fontSize: fontSize.lg, color: colors.onSurface },
  sub: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
  badge: { backgroundColor: colors.brandTertiary, paddingHorizontal: 10, paddingVertical: 4, borderRadius: radius.pill },
  badgeText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.brand },
});
