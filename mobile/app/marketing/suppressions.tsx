/**
 * Suppressions / Unsubscribe list — admin only, read-only.
 * GET /api/marketing/suppressions
 */
import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, FlatList, TouchableOpacity,
  ActivityIndicator, RefreshControl, TextInput,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useFocusEffect, useRouter } from "expo-router";

import { useAuth } from "@/src/auth";
import { api } from "@/src/api";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";

type Suppression = { id?: string; recipient?: string; email?: string; phone?: string; reason?: string; added_at?: string; created_at?: string };

export default function SuppressionsScreen() {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { user } = useAuth();
  const role = String((user as any)?.role || "");
  const allowed = role === "admin" || role === "super_admin";

  const [items, setItems] = useState<Suppression[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [search, setSearch] = useState("");

  const load = useCallback(async () => {
    if (!allowed) { setLoading(false); return; }
    try {
      const res = await api.get("/marketing/suppressions");
      setItems(Array.isArray(res) ? res : res?.suppressions || []);
    } catch {} finally { setLoading(false); setRefreshing(false); }
  }, [allowed]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  if (!allowed) {
    return (
      <View style={[s.center, { paddingTop: insets.top + 60 }]} testID="suppressions-role-gate">
        <Ionicons name="lock-closed" size={36} color={colors.muted} />
        <Text style={s.gateText}>Not authorized</Text>
        <TouchableOpacity onPress={() => router.replace("/(app)")} style={s.gateBtn}><Text style={s.gateBtnText}>Go Home</Text></TouchableOpacity>
      </View>
    );
  }

  const q = search.toLowerCase();
  const filtered = q ? items.filter((s) => (s.recipient || s.email || s.phone || "").toLowerCase().includes(q)) : items;

  const reasonColor: Record<string, { bg: string; fg: string }> = {
    unsubscribe: { bg: "#FEF9C3", fg: "#A16207" },
    bounce: { bg: "#FEE2E2", fg: "#B91C1C" },
    manual: { bg: "#E0F2FE", fg: "#0369A1" },
  };

  return (
    <View style={[s.root, { paddingTop: insets.top }]}>
      <View style={s.navBar}>
        <TouchableOpacity onPress={() => router.back()} hitSlop={12}><Ionicons name="arrow-back" size={22} color={colors.onSurface} /></TouchableOpacity>
        <Text style={s.navTitle}>Suppressions</Text>
        <View style={{ width: 22 }} />
      </View>

      <View style={s.searchWrap}>
        <Ionicons name="search" size={16} color={colors.muted} />
        <TextInput
          style={s.searchInput}
          value={search}
          onChangeText={setSearch}
          placeholder="Search by email or phone..."
          placeholderTextColor={colors.muted}
          testID="suppressions-search"
        />
      </View>

      <Text style={s.readOnlyNote}>Read-only view. Add/remove managed on web.</Text>

      {loading ? <View style={s.center}><ActivityIndicator size="large" color={colors.brand} /></View> : (
        <FlatList
          data={filtered}
          keyExtractor={(s, i) => s.id || String(i)}
          contentContainerStyle={s.list}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.brand} />}
          ListEmptyComponent={<View style={s.emptyWrap}><Ionicons name="ban-outline" size={32} color={colors.muted} /><Text style={s.emptyText}>No suppressions</Text></View>}
          renderItem={({ item }) => {
            const rc = reasonColor[item.reason || ""] || { bg: "#F1F5F9", fg: "#475569" };
            return (
              <View style={s.card} testID={`sup-${item.id || item.recipient}`}>
                <View style={s.cardTop}>
                  <Text style={s.cardRecip}>{item.recipient || item.email || item.phone || "—"}</Text>
                  <View style={[s.reasonPill, { backgroundColor: rc.bg }]}><Text style={[s.reasonText, { color: rc.fg }]}>{(item.reason || "unknown").toUpperCase()}</Text></View>
                </View>
                <Text style={s.cardDate}>
                  {item.added_at || item.created_at
                    ? new Date(item.added_at || item.created_at!).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })
                    : "—"}
                </Text>
              </View>
            );
          }}
        />
      )}
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: "#F8FAFC" },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 24 },
  gateText: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface, marginTop: 12 },
  gateBtn: { marginTop: 20, paddingHorizontal: 24, paddingVertical: 12, borderRadius: radius.md, backgroundColor: colors.brand },
  gateBtnText: { fontFamily: font.semibold, fontSize: fontSize.base, color: "#fff" },
  navBar: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.lg, paddingVertical: spacing.md, borderBottomWidth: 1, borderBottomColor: colors.border, backgroundColor: colors.surface },
  navTitle: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  searchWrap: { flexDirection: "row", alignItems: "center", gap: 8, marginHorizontal: spacing.lg, marginTop: spacing.sm, backgroundColor: colors.surface, borderRadius: radius.sm, paddingHorizontal: spacing.md, paddingVertical: 10, borderWidth: 1, borderColor: colors.border },
  searchInput: { flex: 1, fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface },
  readOnlyNote: { fontFamily: font.regular, fontSize: 11, color: colors.muted, fontStyle: "italic", textAlign: "center", marginTop: spacing.xs, marginBottom: spacing.xs },
  list: { padding: spacing.lg, paddingBottom: 40 },
  card: { backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.lg, marginBottom: spacing.sm, borderWidth: 1, borderColor: colors.border },
  cardTop: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  cardRecip: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface, flex: 1 },
  reasonPill: { paddingHorizontal: 8, paddingVertical: 2, borderRadius: 999 },
  reasonText: { fontFamily: font.bold, fontSize: 9, letterSpacing: 0.5 },
  cardDate: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 4 },
  emptyWrap: { alignItems: "center", paddingTop: 80 },
  emptyText: { fontFamily: font.medium, fontSize: fontSize.base, color: colors.muted, marginTop: 8 },
});
