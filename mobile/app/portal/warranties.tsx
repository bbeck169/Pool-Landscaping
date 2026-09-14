/**
 * Portal Warranties — customer-facing read-only warranty contracts list.
 *
 * Endpoint: GET /api/customers/me/warranties (paginated envelope).
 * Read-only in v1 — no add/edit.
 */
import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, FlatList, RefreshControl, ActivityIndicator } from "react-native";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import { EmptyState } from "@/src/components/ui";
import WarrantyCard, { WarrantyContract } from "@/src/components/warranties/WarrantyCard";

export default function PortalWarranties() {
  const [items, setItems] = useState<WarrantyContract[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      const res = await api.get("/customers/me/warranties");
      const list = res?.items || (Array.isArray(res) ? res : []);
      setItems(list);
    } catch (e: any) {
      setError(e?.message || "Failed to load warranties");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const onRefresh = () => {
    setRefreshing(true);
    load();
  };

  return (
    <View style={s.root} testID="portal-warranties-screen">
      <Header title="Warranties" subtitle="Your warranty contracts" back />

      {loading ? (
        <ActivityIndicator
          color={colors.brand}
          style={{ marginTop: spacing.xl }}
          testID="portal-warranty-loading"
        />
      ) : error ? (
        <View style={s.errorWrap} testID="portal-warranty-error">
          <Text style={s.errorText}>{error}</Text>
        </View>
      ) : (
        <FlatList
          testID="portal-warranty-list"
          data={items}
          keyExtractor={(w) => w.id}
          contentContainerStyle={s.listContent}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={onRefresh} />
          }
          ListEmptyComponent={
            <EmptyState
              icon="shield-outline"
              title="No warranty contracts on file"
              subtitle="When warranty contracts are added, they will appear here."
              testID="portal-warranty-empty"
            />
          }
          renderItem={({ item, index }) => (
            <WarrantyCard
              warranty={item}
              index={index}
              testIdPrefix="portal-warranty"
            />
          )}
        />
      )}
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  listContent: {
    padding: spacing.lg,
    paddingTop: spacing.md,
    paddingBottom: spacing["3xl"],
  },
  errorWrap: {
    padding: spacing.lg,
  },
  errorText: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: "#B91C1C",
  },
});
