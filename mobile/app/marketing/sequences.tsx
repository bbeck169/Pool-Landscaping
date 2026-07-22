/**
 * Drip Sequences — admin only.
 * GET /api/marketing/sequences
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

type Step = { delay_days?: number; template_code?: string; channel?: string };
type Seq = { id: string; name: string; description?: string; steps?: Step[]; active?: boolean; created_at?: string };

export default function SequencesScreen() {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { user } = useAuth();
  const role = String((user as any)?.role || "");
  const allowed = role === "admin" || role === "super_admin";

  const [items, setItems] = useState<Seq[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    if (!allowed) { setLoading(false); return; }
    try {
      const res = await api.get("/marketing/sequences");
      setItems(Array.isArray(res) ? res : res?.sequences || []);
    } catch {} finally { setLoading(false); setRefreshing(false); }
  }, [allowed]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  if (!allowed) {
    return (
      <View style={[s.center, { paddingTop: insets.top + 60 }]} testID="sequences-role-gate">
        <Ionicons name="lock-closed" size={36} color={colors.muted} />
        <Text style={s.gateText}>Not authorized</Text>
        <TouchableOpacity onPress={() => router.replace("/(app)")} style={s.gateBtn}><Text style={s.gateBtnText}>Go Home</Text></TouchableOpacity>
      </View>
    );
  }

  return (
    <View style={[s.root, { paddingTop: insets.top }]}>
      <View style={s.navBar}>
        <TouchableOpacity onPress={() => router.back()} hitSlop={12}><Ionicons name="arrow-back" size={22} color={colors.onSurface} /></TouchableOpacity>
        <Text style={s.navTitle}>Sequences</Text>
        <View style={{ width: 22 }} />
      </View>
      {loading ? <View style={s.center}><ActivityIndicator size="large" color={colors.brand} /></View> : (
        <FlatList
          data={items}
          keyExtractor={(s) => s.id}
          contentContainerStyle={s.list}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.brand} />}
          ListEmptyComponent={<View style={s.emptyWrap}><Ionicons name="git-branch-outline" size={32} color={colors.muted} /><Text style={s.emptyText}>No sequences</Text></View>}
          renderItem={({ item }) => (
            <View style={s.card} testID={`seq-${item.id}`}>
              <View style={s.cardTop}>
                <Text style={s.cardName}>{item.name}</Text>
                <View style={[s.activeDot, { backgroundColor: item.active ? colors.success : colors.muted }]} />
              </View>
              {item.description ? <Text style={s.cardDesc} numberOfLines={2}>{item.description}</Text> : null}
              {item.steps && item.steps.length > 0 && (
                <View style={s.stepsWrap}>
                  <Text style={s.stepsLabel}>{item.steps.length} steps</Text>
                  {item.steps.slice(0, 4).map((st, i) => (
                    <View key={i} style={s.stepRow}>
                      <View style={s.stepDot} />
                      <Text style={s.stepText}>Day {st.delay_days || 0} — {st.template_code || st.channel || "Step"}</Text>
                    </View>
                  ))}
                  {item.steps.length > 4 && <Text style={s.moreText}>+{item.steps.length - 4} more steps</Text>}
                </View>
              )}
            </View>
          )}
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
  cardTop: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  cardName: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface, flex: 1 },
  cardDesc: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 4 },
  activeDot: { width: 8, height: 8, borderRadius: 4 },
  stepsWrap: { marginTop: spacing.sm, paddingTop: spacing.sm, borderTopWidth: 1, borderTopColor: colors.border },
  stepsLabel: { fontFamily: font.bold, fontSize: 10, color: colors.muted, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: spacing.xs },
  stepRow: { flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 3 },
  stepDot: { width: 6, height: 6, borderRadius: 3, backgroundColor: colors.brand },
  stepText: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurface },
  moreText: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.brand, marginTop: 4 },
  emptyWrap: { alignItems: "center", paddingTop: 80 },
  emptyText: { fontFamily: font.medium, fontSize: fontSize.base, color: colors.muted, marginTop: 8 },
});
