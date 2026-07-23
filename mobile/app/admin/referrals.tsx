/**
 * Admin Referrals — admin/super_admin only.
 * GET /api/admin/referrals → { referrals: [...] }
 */
import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, FlatList, TouchableOpacity,
  ActivityIndicator, RefreshControl,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useFocusEffect, useRouter } from "expo-router";

import { useAuth } from "@/src/auth";
import { api } from "@/src/api";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";

const STATUS_COLORS: Record<string, { bg: string; fg: string }> = {
  pending: { bg: "#FEF3C7", fg: "#A16207" },
  pending_paid_window: { bg: "#DBEAFE", fg: "#1D4ED8" },
  credited: { bg: "#DCFCE7", fg: "#166534" },
  voided: { bg: "#FEE2E2", fg: "#991B1B" },
  converted: { bg: "#E0E7FF", fg: "#3730A3" },
};

export default function AdminReferralsScreen() {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { user } = useAuth();
  const role = String((user as any)?.role || "");
  const allowed = role === "admin" || role === "super_admin";

  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    if (!allowed) { setLoading(false); return; }
    try {
      const res = await api.get("/admin/referrals");
      setItems(res?.referrals || (Array.isArray(res) ? res : []));
    } catch {} finally { setLoading(false); setRefreshing(false); }
  }, [allowed]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  if (!allowed) {
    return (
      <View style={[s.center, { paddingTop: insets.top + 60 }]} testID="admin-referrals-role-gate">
        <Ionicons name="lock-closed" size={36} color={colors.muted} />
        <Text style={s.gateText}>Not authorized</Text>
        <TouchableOpacity onPress={() => router.replace("/(app)")} style={s.gateBtn}>
          <Text style={s.gateBtnText}>Go Home</Text>
        </TouchableOpacity>
      </View>
    );
  }

  const summary = {
    total: items.length,
    pending: items.filter((r) => r.status === "pending" || r.status === "pending_paid_window").length,
    credited: items.filter((r) => r.status === "credited").length,
    voided: items.filter((r) => r.status === "voided").length,
  };

  return (
    <View style={[s.root, { paddingTop: insets.top }]}>
      <View style={s.navBar}>
        <TouchableOpacity onPress={() => router.back()} hitSlop={12}>
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </TouchableOpacity>
        <Text style={s.navTitle}>Referrals</Text>
        <View style={{ width: 22 }} />
      </View>

      {/* Summary card */}
      <View style={s.summaryCard} testID="referrals-summary">
        <View style={s.summaryItem}><Text style={s.summaryValue}>{summary.total}</Text><Text style={s.summaryLabel}>Total</Text></View>
        <View style={s.summaryItem}><Text style={[s.summaryValue, { color: "#A16207" }]}>{summary.pending}</Text><Text style={s.summaryLabel}>Pending</Text></View>
        <View style={s.summaryItem}><Text style={[s.summaryValue, { color: "#166534" }]}>{summary.credited}</Text><Text style={s.summaryLabel}>Credited</Text></View>
        <View style={s.summaryItem}><Text style={[s.summaryValue, { color: "#991B1B" }]}>{summary.voided}</Text><Text style={s.summaryLabel}>Voided</Text></View>
      </View>

      {loading ? (
        <View style={s.center}><ActivityIndicator size="large" color={colors.brand} /></View>
      ) : (
        <FlatList
          data={items}
          keyExtractor={(r) => r.id}
          contentContainerStyle={s.list}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.brand} />}
          ListEmptyComponent={
            <View style={s.emptyWrap}><Ionicons name="gift-outline" size={32} color={colors.muted} /><Text style={s.emptyText}>No referrals yet</Text></View>
          }
          renderItem={({ item }) => {
            const sc = STATUS_COLORS[item.status] || { bg: "#F1F5F9", fg: "#475569" };
            return (
              <View style={s.card} testID={`ref-${item.id}`}>
                <View style={s.cardTop}>
                  <Text style={s.cardName}>{item.friend_name || "Friend"}</Text>
                  <View style={[s.statusPill, { backgroundColor: sc.bg }]}>
                    <Text style={[s.statusText, { color: sc.fg }]}>{(item.status || "").replace(/_/g, " ").toUpperCase()}</Text>
                  </View>
                </View>
                {item.friend_email && <Text style={s.cardSub}>{item.friend_email}</Text>}
                {item.friend_phone && <Text style={s.cardSub}>{item.friend_phone}</Text>}
                {item.service_of_interest && <Text style={s.cardInterest}>Interest: {item.service_of_interest}</Text>}
                <Text style={s.cardDate}>{new Date(item.created_at).toLocaleDateString()}</Text>
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
  summaryCard: { flexDirection: "row", marginHorizontal: spacing.lg, marginVertical: spacing.md, backgroundColor: colors.surface, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, padding: spacing.md },
  summaryItem: { flex: 1, alignItems: "center" },
  summaryValue: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface },
  summaryLabel: { fontFamily: font.regular, fontSize: 10, color: colors.muted, marginTop: 2 },
  list: { padding: spacing.lg, paddingBottom: 40 },
  card: { backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.lg, marginBottom: spacing.sm, borderWidth: 1, borderColor: colors.border },
  cardTop: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  cardName: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface, flex: 1 },
  statusPill: { paddingHorizontal: 8, paddingVertical: 2, borderRadius: 999 },
  statusText: { fontFamily: font.bold, fontSize: 9, letterSpacing: 0.3 },
  cardSub: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
  cardInterest: { fontFamily: font.medium, fontSize: 11, color: colors.brand, marginTop: 4 },
  cardDate: { fontFamily: font.regular, fontSize: 11, color: colors.muted, marginTop: 4 },
  emptyWrap: { alignItems: "center", paddingTop: 80 },
  emptyText: { fontFamily: font.medium, fontSize: fontSize.base, color: colors.muted, marginTop: 8 },
});
