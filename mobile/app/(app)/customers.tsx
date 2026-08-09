import React, { useCallback, useMemo, useState } from "react";
import { View, Text, StyleSheet, FlatList, TextInput, RefreshControl, Pressable, Platform, Alert } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Loading, EmptyState } from "@/src/components/ui";
import { Header, IconButton } from "@/src/components/widgets";
import { ImportExport } from "@/src/components/ImportExport";
import { useBulkSelect, BulkCheckbox, BulkActionBar } from "@/src/components/bulk-select/BulkSelectToolkit";

export default function Customers() {
  const router = useRouter();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin" || user?.role === "super_admin";
  const [items, setItems] = useState<any[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [selectMode, setSelectMode] = useState(false);

  const visibleIds = useMemo(() => items.map((i) => i.id), [items]);
  const bulk = useBulkSelect(visibleIds);

  const load = useCallback(async (s: string) => {
    try {
      const q = s ? `?search=${encodeURIComponent(s)}` : "";
      setItems(await api.get(`/customers${q}`));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(search); }, [load, search]));

  const exitSelectMode = () => { setSelectMode(false); bulk.clear(); };

  const bulkDelete = async () => {
    Alert.alert(`Delete ${bulk.count} customer${bulk.count !== 1 ? "s" : ""}?`, "This action cannot be undone.", [
      { text: "Cancel", style: "cancel" },
      {
        text: "Delete", style: "destructive", onPress: async () => {
          try {
            await api.post("/customers/bulk-delete", { ids: [...bulk.selected] });
            Alert.alert("Deleted", `${bulk.count} customer${bulk.count !== 1 ? "s" : ""} removed.`);
            exitSelectMode();
            load(search);
          } catch (e: any) { Alert.alert("Error", e?.message || "Delete failed"); }
        },
      },
    ]);
  };

  return (
    <View style={styles.root}>
      <Header
        title={selectMode ? `${bulk.count} selected` : "Customers"}
        right={
          selectMode ? (
            <Pressable onPress={exitSelectMode} testID="bulk-exit-select">
              <Text style={{ fontFamily: font.semibold, fontSize: fontSize.base, color: colors.brand }}>Cancel</Text>
            </Pressable>
          ) : (
            <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.xs }}>
              {isAdmin ? <ImportExport entity="customers" label="customers" exportPath="/export/customers" importPath="/import/customers" onDone={() => load(search)} /> : null}
              <IconButton icon="add" onPress={() => router.push("/customer/new")} testID="add-customer-button" />
            </View>
          )
        }
      />
      <View style={styles.searchWrap}>
        <View style={styles.searchBox}>
          {selectMode ? (
            <BulkCheckbox
              checked={bulk.allSelected}
              indeterminate={bulk.indeterminate}
              onPress={bulk.toggleAll}
              testID="bulk-select-all-customers"
            />
          ) : (
            <Ionicons name="search" size={18} color={colors.muted} />
          )}
          <TextInput
            testID="customer-search-input"
            style={styles.searchInput}
            placeholder="Search customers"
            placeholderTextColor={colors.muted}
            value={search}
            onChangeText={(t) => { setSearch(t); load(t); }}
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
          contentContainerStyle={{ padding: spacing.lg, paddingTop: spacing.sm, paddingBottom: selectMode ? 100 : spacing["3xl"] }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(search); }} />}
          renderItem={({ item }) => (
            <Pressable
              style={[styles.row, bulk.selected.has(item.id) && styles.rowSelected]}
              onPress={() => selectMode ? bulk.toggleOne(item.id) : router.push(`/customer/${item.id}`)}
              onLongPress={() => { if (!selectMode) { setSelectMode(true); bulk.toggleOne(item.id); } }}
              testID={`customer-row-${item.id}`}
            >
              {selectMode ? (
                <BulkCheckbox checked={bulk.selected.has(item.id)} onPress={() => bulk.toggleOne(item.id)} testID={`bulk-check-${item.id}`} />
              ) : null}
              <View style={styles.avatar}>
                <Text style={styles.avatarText}>{item.name?.charAt(0)?.toUpperCase()}</Text>
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.name} numberOfLines={1}>{item.name}</Text>
                <Text style={styles.sub} numberOfLines={1}>{item.address || item.phone || item.email || "—"}</Text>
              </View>
              {!selectMode ? <Ionicons name="chevron-forward" size={18} color={colors.muted} /> : null}
            </Pressable>
          )}
        />
      )}
      <BulkActionBar
        count={bulk.count}
        onClear={exitSelectMode}
        actions={[
          { key: "bulk-delete-customers", label: "Delete", icon: "trash-outline", tone: "danger", onPress: bulkDelete },
        ]}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  searchWrap: { paddingHorizontal: spacing.lg, paddingVertical: spacing.md },
  searchBox: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    borderRadius: radius.md, paddingHorizontal: spacing.md, height: 48,
  },
  searchInput: { flex: 1, fontFamily: font.regular, fontSize: fontSize.lg, color: colors.onSurface, ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}) },
  row: {
    flexDirection: "row", alignItems: "center", gap: spacing.md,
    backgroundColor: colors.surface, borderRadius: radius.md,
    padding: spacing.md, borderWidth: 1, borderColor: colors.border,
    marginBottom: spacing.sm,
  },
  rowSelected: { borderColor: colors.brand, backgroundColor: colors.brandTertiary },
  avatar: { width: 44, height: 44, borderRadius: 22, backgroundColor: colors.brandTertiary, alignItems: "center", justifyContent: "center" },
  avatarText: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.brand },
  name: { fontFamily: font.semibold, fontSize: fontSize.lg, color: colors.onSurface },
  sub: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
});
