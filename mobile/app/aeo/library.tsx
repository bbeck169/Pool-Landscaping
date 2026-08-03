// Phase 16 · Feb-2026 — Response Library (mobile).
//
// Platform filter chips + search + list with long-press-to-delete.
// Delete uses `DELETE /api/aeo/response/templates/{id}`.
import React, { useCallback, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TextInput, Pressable,
  RefreshControl, Alert, FlatList,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Card, EmptyState } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";
import { RoleGate } from "@/src/components/RoleGate";
import { showConfirm } from "@/src/components/ConfirmModal";

type Template = {
  id: string;
  title?: string;
  body?: string;
  text?: string;
  platform?: string;
  usage_count?: number;
};

const PLATFORMS = ["all", "google", "yelp", "facebook", "x", "generic"];

export default function AeoLibrary() {
  const [platform, setPlatform] = useState<string>("all");
  const [q, setQ] = useState("");
  const [items, setItems] = useState<Template[]>([]);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const j: any = await api.get("/aeo/response/templates");
      setItems(j?.templates || j?.items || []);
    } catch {
      setItems([]);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const filtered = useMemo(() => {
    return items.filter((t) => {
      if (platform !== "all" && (t.platform || "generic").toLowerCase() !== platform)
        return false;
      if (q && !((t.title || "") + " " + (t.body || t.text || "")).toLowerCase().includes(q.toLowerCase()))
        return false;
      return true;
    });
  }, [items, platform, q]);

  const remove = (t: Template) => {
    showConfirm({
      title: "Delete template?",
      message: `"${t.title || 'Untitled'}" will be removed.`,
      confirmLabel: "Delete",
      confirmStyle: "destructive",
      onConfirm: async () => {
        try {
          await api.del(`/aeo/response/templates/${encodeURIComponent(t.id)}`);
          setItems((prev) => prev.filter((x) => x.id !== t.id));
        } catch (err: any) {
          Alert.alert("Failed", String(err?.message || err));
        }
      },
    });
  };

  return (
    <RoleGate level="admin_plus">
      <View style={styles.container}>
        <Header title="Response Library" />
        <View style={styles.top}>
          <TextInput
            testID="library-search"
            value={q}
            onChangeText={setQ}
            placeholder="Search templates…"
            placeholderTextColor={colors.muted}
            style={styles.searchInput}
          />
          <ScrollView horizontal showsHorizontalScrollIndicator={false}
                       contentContainerStyle={styles.chipRow}>
            {PLATFORMS.map((p) => {
              const on = platform === p;
              return (
                <Pressable
                  key={p}
                  testID={`library-chip-${p}`}
                  accessibilityLabel={`Platform ${p}`}
                  onPress={() => setPlatform(p)}
                  style={[styles.chip, on && styles.chipOn]}
                >
                  <Text style={[styles.chipText, on && styles.chipTextOn]}>
                    {p === "all" ? "All" : p}
                  </Text>
                </Pressable>
              );
            })}
          </ScrollView>
        </View>
        <FlatList
          data={filtered}
          keyExtractor={(item) => item.id}
          contentContainerStyle={styles.list}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={async () => {
              setRefreshing(true); await load(); setRefreshing(false);
            }} />
          }
          ListEmptyComponent={
            <EmptyState
              icon="library-outline"
              title="No templates match"
              subtitle="Try a different platform or clear the search."
              testID="library-empty"
            />
          }
          renderItem={({ item }) => (
            <Pressable
              testID={`library-row-${item.id}`}
              accessibilityLabel={`Template ${item.title || item.id}`}
              onLongPress={() => remove(item)}
              style={styles.row}
            >
              <View style={{ flex: 1 }}>
                <Text style={styles.title}>{item.title || "Untitled"}</Text>
                <Text style={styles.snippet} numberOfLines={2}>
                  {item.body || item.text || ""}
                </Text>
                <View style={styles.metaRow}>
                  <View style={styles.pill}>
                    <Text style={styles.pillText}>{item.platform || "generic"}</Text>
                  </View>
                  <Text style={styles.usage}>
                    Used {item.usage_count || 0}×
                  </Text>
                </View>
              </View>
              <Ionicons name="trash-outline" size={18} color={colors.muted} />
            </Pressable>
          )}
        />
      </View>
    </RoleGate>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.surface },
  top: { padding: spacing.lg, paddingBottom: spacing.sm, gap: spacing.sm },
  searchInput: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    padding: spacing.md, fontFamily: font.regular, fontSize: fontSize.base,
    color: colors.onSurface,
  },
  chipRow: { gap: 6, paddingRight: spacing.lg },
  chip: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: radius.pill, backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border },
  chipOn: { backgroundColor: colors.brand, borderColor: colors.brand },
  chipText: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurfaceSecondary, textTransform: "capitalize" },
  chipTextOn: { color: "#FFFFFF" },
  list: { padding: spacing.lg, paddingTop: spacing.sm, gap: spacing.sm, paddingBottom: spacing["3xl"] },
  row: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    padding: spacing.md, borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface,
  },
  title: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  snippet: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 4 },
  metaRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm, marginTop: 6 },
  pill: { paddingHorizontal: 8, paddingVertical: 2, borderRadius: radius.sm, backgroundColor: colors.brandTertiary },
  pillText: { fontFamily: font.semibold, fontSize: 11, color: colors.onBrandTertiary, textTransform: "capitalize" },
  usage: { fontFamily: font.regular, fontSize: 11, color: colors.muted },
});
