import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, FlatList, RefreshControl, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Loading, EmptyState } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";
import { formatCustomerName } from "@/src/utils/formatCustomerName";

export default function Communications() {
  const router = useRouter();
  const [threads, setThreads] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      setThreads(await api.get("/communications"));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  return (
    <View style={styles.root}>
      <Header title="Communication" subtitle="Customer messages" back />
      {loading ? (
        <Loading testID="communications-loading" />
      ) : (
        <FlatList
          testID="communications-list"
          data={threads}
          keyExtractor={(i) => i.customer_id}
          contentContainerStyle={{ padding: spacing.lg, paddingTop: spacing.md, paddingBottom: spacing["3xl"] }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
          ListEmptyComponent={<EmptyState icon="chatbubbles-outline" title="No messages" subtitle="Customer messages will appear here." testID="communications-empty" />}
          renderItem={({ item }) => (
            <Pressable style={styles.row} onPress={() => router.push(`/communication/${item.customer_id}`)} testID={`thread-${item.customer_id}`}>
              <View style={styles.avatar}>
                <Text style={styles.avatarText}>{formatCustomerName(item).charAt(0).toUpperCase()}</Text>
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.name} numberOfLines={1}>{formatCustomerName(item)}</Text>
                <Text style={styles.preview} numberOfLines={1}>{item.last_text}</Text>
              </View>
              {item.unread > 0 ? <View style={styles.badge}><Text style={styles.badgeText}>{item.unread}</Text></View> : null}
              <Ionicons name="chevron-forward" size={18} color={colors.muted} />
            </Pressable>
          )}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.md, backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.sm },
  avatar: { width: 44, height: 44, borderRadius: 22, backgroundColor: colors.brandTertiary, alignItems: "center", justifyContent: "center" },
  avatarText: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.brand },
  name: { fontFamily: font.semibold, fontSize: fontSize.lg, color: colors.onSurface },
  preview: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted, marginTop: 1 },
  badge: { minWidth: 22, height: 22, paddingHorizontal: 6, borderRadius: 11, backgroundColor: colors.error, alignItems: "center", justifyContent: "center" },
  badgeText: { color: "#fff", fontFamily: font.bold, fontSize: fontSize.sm },
});
