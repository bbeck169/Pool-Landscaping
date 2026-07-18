/**
 * Phase 4 · Batch B / D6 — Handbook sections list (mobile).
 * Read-only for all roles. Tapping a section deep-links to `[code].tsx`.
 */
import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, TextInput, Pressable, RefreshControl } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { router, useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, fontSize, font } from "@/src/theme";
import { Loading } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";

export default function HandbookIndex() {
  const [rows, setRows] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [q, setQ] = useState("");

  const load = useCallback(async () => {
    try {
      const r = await api.get("/handbook/sections");
      setRows(r?.rows || []);
    } finally { setLoading(false); setRefreshing(false); }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const query = q.trim().toLowerCase();
  const filtered = query
    ? rows.filter((r) => (r.title || "").toLowerCase().includes(query) || (r.code || "").toLowerCase().includes(query))
    : rows;

  if (loading) return <Loading />;

  return (
    <View style={styles.container}>
      <Header title="Handbook" />
      <View style={styles.searchBox}>
        <Ionicons name="search" size={16} color={colors.muted} />
        <TextInput value={q} onChangeText={setQ} placeholder="Search sections…"
          placeholderTextColor={colors.muted} style={styles.searchInput}
          testID="mobile-handbook-search" />
      </View>
      <ScrollView contentContainerStyle={styles.list}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}>
        {filtered.map((s) => (
          <Pressable key={s.code} style={styles.card}
            onPress={() => router.push(`/handbook/${s.code}`)}
            testID={`mobile-handbook-card-${s.code}`}>
            <View style={{ flex: 1 }}>
              <Text style={styles.cardMeta}>{s.is_system ? "System" : "Custom"} · v{s.version || 1}</Text>
              <Text style={styles.cardTitle}>{s.title}</Text>
            </View>
            <Ionicons name="chevron-forward" size={18} color={colors.muted} />
          </Pressable>
        ))}
        {filtered.length === 0 && <Text style={styles.empty}>No sections match.</Text>}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background },
  searchBox: {
    flexDirection: "row", alignItems: "center", gap: 8, paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm, marginHorizontal: spacing.md, marginTop: spacing.sm,
    backgroundColor: colors.surface, borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border,
  },
  searchInput: { flex: 1, color: colors.onSurface, fontSize: fontSize.md, padding: 0 },
  list: { padding: spacing.md, gap: spacing.sm },
  card: {
    flexDirection: "row", alignItems: "center", padding: spacing.md,
    backgroundColor: colors.surface, borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border,
  },
  cardMeta: { color: colors.muted, fontSize: fontSize.xs, marginBottom: 2 },
  cardTitle: { color: colors.onSurface, fontSize: fontSize.md, fontFamily: font.bold },
  empty: { textAlign: "center", color: colors.muted, marginTop: spacing.lg },
});
