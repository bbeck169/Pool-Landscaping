import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, FlatList, TextInput, RefreshControl, Pressable, Platform } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Loading, EmptyState } from "@/src/components/ui";
import { Header, IconButton } from "@/src/components/widgets";
import { ImportExport } from "@/src/components/ImportExport";

export default function Customers() {
  const router = useRouter();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [items, setItems] = useState<any[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async (s: string) => {
    try {
      const q = s ? `?search=${encodeURIComponent(s)}` : "";
      setItems(await api.get(`/customers${q}`));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      load(search);
    }, [load])
  );

  return (
    <View style={styles.root}>
      <Header
        title="Customers"
        right={
          <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.xs }}>
            {isAdmin ? <ImportExport entity="customers" label="customers" exportPath="/export/customers" importPath="/import/customers" onDone={() => load(search)} /> : null}
            <IconButton icon="add" onPress={() => router.push("/customer/new")} testID="add-customer-button" />
          </View>
        }
      />
      <View style={styles.searchWrap}>
        <View style={styles.searchBox}>
          <Ionicons name="search" size={18} color={colors.muted} />
          <TextInput
            testID="customer-search-input"
            style={styles.searchInput}
            placeholder="Search customers"
            placeholderTextColor={colors.muted}
            value={search}
            onChangeText={(t) => {
              setSearch(t);
              load(t);
            }}
            autoCapitalize="none"
          />
        </View>
      </View>
      {loading ? (
        <Loading testID="customers-loading" />
      ) : items.length === 0 ? (
        <EmptyState icon="people-outline" title="No customers found" subtitle="Add your first customer to get started." testID="customers-empty" />
      ) : (
        <FlatList
          testID="customers-list"
          data={items}
          keyExtractor={(i) => i.id}
          contentContainerStyle={{ padding: spacing.lg, paddingTop: spacing.sm, paddingBottom: spacing["3xl"] }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(search); }} />}
          renderItem={({ item }) => (
            <Pressable style={styles.row} onPress={() => router.push(`/customer/${item.id}`)} testID={`customer-row-${item.id}`}>
              <View style={styles.avatar}>
                <Text style={styles.avatarText}>{item.name?.charAt(0)?.toUpperCase()}</Text>
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.name} numberOfLines={1}>{item.name}</Text>
                <Text style={styles.sub} numberOfLines={1}>{item.address || item.phone || item.email || "—"}</Text>
              </View>
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
  searchWrap: { paddingHorizontal: spacing.lg, paddingVertical: spacing.md },
  searchBox: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    height: 48,
  },
  searchInput: { flex: 1, fontFamily: font.regular, fontSize: fontSize.lg, color: colors.onSurface, ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}) },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
    marginBottom: spacing.sm,
  },
  avatar: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: colors.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
  },
  avatarText: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.brand },
  name: { fontFamily: font.semibold, fontSize: fontSize.lg, color: colors.onSurface },
  sub: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
});
