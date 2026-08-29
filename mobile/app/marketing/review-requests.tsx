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
import { formatCustomerName } from "@/src/utils/formatCustomerName";

type ReviewReq = {
  id: string;
  customer_id?: string;
  customer_name?: string | null;
  channel?: string;
  variant?: string;
  status?: string;
  source?: string;
  requested_at?: string;
  sent_at?: string;
  opened_at?: string;
  reviewed_at?: string;
  review_rating?: number | null;
  created_at?: string;
};

const STATES = [
  { key: "", label: "All" },
  { key: "queued", label: "Queued" },
  { key: "sent", label: "Sent" },
  { key: "opened", label: "Opened" },
  { key: "reviewed", label: "Reviewed" },
  { key: "expired", label: "Expired" },
  { key: "failed", label: "Failed" },
];

const stColor: Record<string, { bg: string; fg: string }> = {
  queued: { bg: "#E0F2FE", fg: "#0369A1" },
  sent: { bg: "#DBEAFE", fg: "#1D4ED8" },
  opened: { bg: "#FEF9C3", fg: "#A16207" },
  clicked: { bg: "#E0F2FE", fg: "#0E7490" },
  reviewed: { bg: "#DCFCE7", fg: "#166534" },
  left_review: { bg: "#DCFCE7", fg: "#166534" },
  expired: { bg: "#F1F5F9", fg: "#475569" },
  failed: { bg: "#FEE2E2", fg: "#B91C1C" },
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
        <TouchableOpacity onPress={() => router.replace("/(app)")} style={s.gateBtn}>
          <Text style={s.gateBtnText}>Go Home</Text>
        </TouchableOpacity>
      </View>
    );
  }

  const filtered = filter ? items.filter((r) => r.status === filter) : items;

  return (
    <View style={[s.root, { paddingTop: insets.top }]}>
      <View style={s.navBar}>
        <TouchableOpacity onPress={() => router.back()} hitSlop={12}>
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </TouchableOpacity>
        <Text style={s.navTitle}>Review Requests</Text>
        <View style={{ width: 22 }} />
      </View>

      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.filterRow}>
        {STATES.map((st) => (
          <TouchableOpacity
            key={st.key}
            style={[s.pill, filter === st.key && s.pillActive]}
            onPress={() => setFilter(st.key)}
            testID={`rr-filter-${st.key || "all"}`}
          >
            <Text style={[s.pillText, filter === st.key && s.pillTextActive]}>{st.label}</Text>
          </TouchableOpacity>
        ))}
      </ScrollView>

      {loading ? (
        <View style={s.center}><ActivityIndicator size="large" color={colors.brand} /></View>
      ) : (
        <FlatList
          data={filtered}
          keyExtractor={(r) => r.id}
          contentContainerStyle={s.list}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.brand} />
          }
          ListEmptyComponent={
            <View style={s.emptyWrap}>
              <Ionicons name="star-outline" size={32} color={colors.muted} />
              <Text style={s.emptyText}>No review requests</Text>
            </View>
          }
          renderItem={({ item }) => {
            const sc = stColor[item.status || ""] || { bg: "#F1F5F9", fg: "#475569" };
            const displayName = formatCustomerName(item);
            return (
              <View style={s.card} testID={`rr-${item.id}`}>
                <View style={s.cardTop}>
                  <Text style={s.cardName} numberOfLines={1}>{displayName}</Text>
                  <View style={[s.stPill, { backgroundColor: sc.bg }]}>
                    <Text style={[s.stText, { color: sc.fg }]}>{(item.status || "unknown").toUpperCase()}</Text>
                  </View>
                </View>

                <View style={s.metaRow}>
                  {item.channel && (
                    <View style={s.metaChip}>
                      <Ionicons name={item.channel === "sms" ? "chatbox" : "mail"} size={10} color={colors.muted} />
                      <Text style={s.metaText}>{item.channel}</Text>
                    </View>
                  )}
                  {item.variant && (
                    <View style={s.metaChip}>
                      <Text style={s.metaText}>Variant {item.variant}</Text>
                    </View>
                  )}
                  {item.source && (
                    <View style={s.metaChip}>
                      <Text style={s.metaText}>{item.source.replace(/_/g, " ")}</Text>
                    </View>
                  )}
                </View>

                <View style={s.tsRow}>
                  {item.sent_at && (
                    <Text style={s.ts}>Sent {new Date(item.sent_at).toLocaleDateString()}</Text>
                  )}
                  {item.opened_at && (
                    <Text style={s.ts}>Opened {new Date(item.opened_at).toLocaleDateString()}</Text>
                  )}
                  {item.reviewed_at && (
                    <Text style={[s.ts, { color: colors.success }]}>
                      Reviewed {new Date(item.reviewed_at).toLocaleDateString()}
                      {item.review_rating != null ? ` (${item.review_rating}★)` : ""}
                    </Text>
                  )}
                  {!item.sent_at && item.requested_at && (
                    <Text style={s.ts}>Requested {new Date(item.requested_at).toLocaleDateString()}</Text>
                  )}
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
  cardName: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface, flex: 1, marginRight: 8 },
  stPill: { paddingHorizontal: 8, paddingVertical: 2, borderRadius: 999 },
  stText: { fontFamily: font.bold, fontSize: 9, letterSpacing: 0.5 },
  metaRow: { flexDirection: "row", gap: 6, marginTop: 6, flexWrap: "wrap" },
  metaChip: { flexDirection: "row", alignItems: "center", gap: 3, backgroundColor: "#F1F5F9", paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4 },
  metaText: { fontFamily: font.medium, fontSize: 10, color: colors.muted, textTransform: "capitalize" },
  tsRow: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.sm, flexWrap: "wrap" },
  ts: { fontFamily: font.regular, fontSize: 11, color: colors.muted },
  emptyWrap: { alignItems: "center", paddingTop: 80 },
  emptyText: { fontFamily: font.medium, fontSize: fontSize.base, color: colors.muted, marginTop: 8 },
});
