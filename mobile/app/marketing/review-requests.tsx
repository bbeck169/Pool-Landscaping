/**
 * Review Requests — admin only.
 * GET /api/marketing/review-requests
 */
import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, FlatList, TouchableOpacity,
  ActivityIndicator, RefreshControl, ScrollView,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useFocusEffect, useRouter } from "expo-router";

import { useAuth } from "@/src/auth";
import { api } from "@/src/api";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";

type ReviewReq = { id: string; customer_name?: string; customer_email?: string; status?: string; sent_at?: string; opened_at?: string; clicked_at?: string; review_left_at?: string; created_at?: string };
const STATES = [{ key: "", label: "All" }, { key: "queued", label: "Queued" }, { key: "sent", label: "Sent" }, { key: "opened", label: "Opened" }, { key: "clicked", label: "Clicked" }, { key: "left_review", label: "Reviewed" }];

const stColor: Record<string, { bg: string; fg: string }> = {
  queued: { bg: "#E0F2FE", fg: "#0369A1" }, sent: { bg: "#DBEAFE", fg: "#1D4ED8" },
  opened: { bg: "#FEF9C3", fg: "#A16207" }, clicked: { bg: "#E0F2FE", fg: "#0E7490" },
  left_review: { bg: "#DCFCE7", fg: "#166534" },
};

export default function ReviewRequestsScreen() {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { user } = useAuth();
  const role = String((user as any)?.role || "");
  const allowed = role === "admin" || role === "super_admin";

  const [items, setItems] = useState<ReviewReq[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [filter, setFilter] = useState("");

  const load = useCallback(async () => {
    if (!allowed) { setLoading(false); return; }
    try {
      const res = await api.get("/marketing/review-requests");
      setItems(Array.isArray(res) ? res : res?.review_requests || []);
    } catch {} finally { setLoading(false); setRefreshing(false); }
  }, [allowed]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  if (!allowed) {
    return (
      <View style={[s.center, { paddingTop: insets.top + 60 }]} testID="reviews-role-gate">
        <Ionicons name="lock-closed" size={36} color={colors.muted} />
        <Text style={s.gateText}>Not authorized</Text>
        <TouchableOpacity onPress={() => router.replace("/(app)")} style={s.gateBtn}><Text style={s.gateBtnText}>Go Home</Text></TouchableOpacity>
      </View>
    );
  }

  const filtered = filter ? items.filter((r) => r.status === filter) : items;

  return (
    <View style={[s.root, { paddingTop: insets.top }]}>
      <View style={s.navBar}>
        <TouchableOpacity onPress={() => router.back()} hitSlop={12}><Ionicons name="arrow-back" size={22} color={colors.onSurface} /></TouchableOpacity>
        <Text style={s.navTitle}>Review Requests</Text>
        <View style={{ width: 22 }} />
      </View>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.filterRow}>
        {STATES.map((st) => (
          <TouchableOpacity key={st.key} style={[s.pill, filter === st.key && s.pillActive]} onPress={() => setFilter(st.key)} testID={`rr-filter-${st.key || "all"}`}>
            <Text style={[s.pillText, filter === st.key && s.pillTextActive]}>{st.label}</Text>
          </TouchableOpacity>
        ))}
      </ScrollView>
      {loading ? <View style={s.center}><ActivityIndicator size="large" color={colors.brand} /></View> : (
        <FlatList
          data={filtered}
          keyExtractor={(r) => r.id}
          contentContainerStyle={s.list}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.brand} />}
          ListEmptyComponent={<View style={s.emptyWrap}><Ionicons name="star-outline" size={32} color={colors.muted} /><Text style={s.emptyText}>No review requests</Text></View>}
          renderItem={({ item }) => {
            const sc = stColor[item.status || ""] || { bg: "#F1F5F9", fg: "#475569" };
            return (
              <View style={s.card} testID={`rr-${item.id}`}>
                <View style={s.cardTop}>
                  <Text style={s.cardName}>{item.customer_name || item.customer_email || "Unknown"}</Text>
                  <View style={[s.stPill, { backgroundColor: sc.bg }]}><Text style={[s.stText, { color: sc.fg }]}>{(item.status || "unknown").toUpperCase()}</Text></View>
                </View>
                {item.customer_email ? <Text style={s.cardEmail}>{item.customer_email}</Text> : null}
                <View style={s.tsRow}>
                  {item.sent_at ? <Text style={s.ts}>Sent {new Date(item.sent_at).toLocaleDateString()}</Text> : null}
                  {item.opened_at ? <Text style={s.ts}>Opened {new Date(item.opened_at).toLocaleDateString()}</Text> : null}
                  {item.review_left_at ? <Text style={[s.ts, { color: colors.success }]}>Review {new Date(item.review_left_at).toLocaleDateString()}</Text> : null}
                </View>
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
  filterRow: { paddingHorizontal: spacing.lg, paddingVertical: spacing.sm, gap: spacing.sm },
  pill: { paddingHorizontal: 14, paddingVertical: 7, borderRadius: 999, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  pillActive: { backgroundColor: colors.brandTertiary, borderColor: colors.brandTertiary },
  pillText: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted },
  pillTextActive: { color: colors.onBrandTertiary, fontFamily: font.semibold },
  list: { padding: spacing.lg, paddingBottom: 40 },
  card: { backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.lg, marginBottom: spacing.sm, borderWidth: 1, borderColor: colors.border },
  cardTop: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  cardName: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface, flex: 1 },
  cardEmail: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
  stPill: { paddingHorizontal: 8, paddingVertical: 2, borderRadius: 999 },
  stText: { fontFamily: font.bold, fontSize: 9, letterSpacing: 0.5 },
  tsRow: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.sm, flexWrap: "wrap" },
  ts: { fontFamily: font.regular, fontSize: 11, color: colors.muted },
  emptyWrap: { alignItems: "center", paddingTop: 80 },
  emptyText: { fontFamily: font.medium, fontSize: fontSize.base, color: colors.muted, marginTop: 8 },
});
