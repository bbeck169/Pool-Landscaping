/**
 * Promo Codes — admin/super_admin only (read-heavy + toggle active).
 * GET /api/promo-codes → { promo_codes: [...], count }
 */
import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, FlatList, TouchableOpacity,
  ActivityIndicator, RefreshControl, Alert,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useFocusEffect, useRouter } from "expo-router";

import { useAuth } from "@/src/auth";
import { api } from "@/src/api";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";
import BreadcrumbBar from "@/src/components/nav/BreadcrumbBar";

export default function PromoCodesScreen() {
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
      const res = await api.get("/promo-codes");
      setItems(res?.promo_codes || (Array.isArray(res) ? res : []));
    } catch {} finally { setLoading(false); setRefreshing(false); }
  }, [allowed]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const toggleActive = async (code: any) => {
    try {
      await api.patch(`/promo-codes/${code.id}`, { is_active: !code.is_active });
      load();
    } catch (e: any) { Alert.alert("Failed", e.message); }
  };

  if (!allowed) {
    return (
      <View style={[s.center, { paddingTop: insets.top + 60 }]} testID="promo-codes-role-gate">
        <Ionicons name="lock-closed" size={36} color={colors.muted} />
        <Text style={s.gateText}>Not authorized</Text>
        <TouchableOpacity onPress={() => router.replace("/(app)")} style={s.gateBtn}>
          <Text style={s.gateBtnText}>Go Home</Text>
        </TouchableOpacity>
      </View>
    );
  }

  return (
    <View style={[s.root, { paddingTop: insets.top }]}>
      <View style={s.navBar}>
        <TouchableOpacity onPress={() => router.back()} hitSlop={12}>
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </TouchableOpacity>
        <Text style={s.navTitle}>Promo Codes</Text>
        <View style={{ width: 22 }} />
      </View>
      <BreadcrumbBar title="Promo Codes" />

      {loading ? (
        <View style={s.center}><ActivityIndicator size="large" color={colors.brand} /></View>
      ) : (
        <FlatList
          data={items}
          keyExtractor={(p) => p.id}
          contentContainerStyle={s.list}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.brand} />}
          ListEmptyComponent={
            <View style={s.emptyWrap}><Ionicons name="pricetag-outline" size={32} color={colors.muted} /><Text style={s.emptyText}>No promo codes</Text></View>
          }
          renderItem={({ item }) => {
            const isActive = item.is_active !== false;
            const isReferral = item.type === "referral_reward";
            return (
              <View style={s.card} testID={`promo-${item.id}`}>
                <View style={s.cardTop}>
                  <View style={{ flex: 1 }}>
                    <Text style={s.codeText}>{item.code}</Text>
                    <View style={s.typePillRow}>
                      <View style={[s.typePill, isReferral ? { backgroundColor: "#E0E7FF" } : { backgroundColor: "#FEF3C7" }]}>
                        <Text style={[s.typePillText, isReferral ? { color: "#3730A3" } : { color: "#A16207" }]}>
                          {isReferral ? "Referral Reward" : item.type || "Manual"}
                        </Text>
                      </View>
                      {item.discount_kind === "fixed_credit" && item.amount_cents ? (
                        <Text style={s.amountText}>${(item.amount_cents / 100).toFixed(2)} credit</Text>
                      ) : item.percent ? (
                        <Text style={s.amountText}>{item.percent}% off</Text>
                      ) : null}
                    </View>
                  </View>
                  <TouchableOpacity onPress={() => toggleActive(item)} testID={`promo-toggle-${item.id}`}>
                    <View style={[s.toggleDot, { backgroundColor: isActive ? "#16A34A" : "#9CA3AF" }]} />
                  </TouchableOpacity>
                </View>
                <View style={s.cardMeta}>
                  <Text style={s.metaText}>Uses: {item.uses_count || 0}{item.max_uses ? `/${item.max_uses}` : ""}</Text>
                  <Text style={s.metaText}>Apply: {(item.apply_to || "").replace(/_/g, " ")}</Text>
                  {item.expires_at && <Text style={s.metaText}>Expires: {new Date(item.expires_at).toLocaleDateString()}</Text>}
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
  list: { padding: spacing.lg, paddingBottom: 40 },
  card: { backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.lg, marginBottom: spacing.sm, borderWidth: 1, borderColor: colors.border },
  cardTop: { flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start" },
  codeText: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface, letterSpacing: 1 },
  typePillRow: { flexDirection: "row", alignItems: "center", gap: 8, marginTop: 4 },
  typePill: { paddingHorizontal: 8, paddingVertical: 2, borderRadius: 999 },
  typePillText: { fontFamily: font.bold, fontSize: 9, letterSpacing: 0.3 },
  amountText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.brand },
  toggleDot: { width: 12, height: 12, borderRadius: 6, marginTop: 4 },
  cardMeta: { flexDirection: "row", gap: 12, marginTop: spacing.sm, flexWrap: "wrap" },
  metaText: { fontFamily: font.regular, fontSize: 11, color: colors.muted },
  emptyWrap: { alignItems: "center", paddingTop: 80 },
  emptyText: { fontFamily: font.medium, fontSize: fontSize.base, color: colors.muted, marginTop: 8 },
});
