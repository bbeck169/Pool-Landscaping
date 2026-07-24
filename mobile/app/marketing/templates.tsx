/**
 * Marketing Templates — email + SMS list.
 * GET /api/marketing/templates → { templates: [...], count: N }
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
import BreadcrumbBar from "@/src/components/nav/BreadcrumbBar";

type Template = {
  id?: string;
  name?: string;
  code?: string;
  subject?: string;
  body?: string;
  channel?: string;
  active?: boolean;
  is_active?: boolean;
  system?: boolean;
  category?: string;
  updated_at?: string;
};

const CHANNELS = [
  { key: "", label: "All" },
  { key: "email", label: "Email" },
  { key: "sms", label: "SMS" },
];

export default function TemplatesScreen() {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { user } = useAuth();
  const role = String((user as any)?.role || "");
  const allowed = role === "admin" || role === "super_admin";

  const [items, setItems] = useState<Template[]>([]);
  const [loading, setLoading] = useState(true);
  const [channel, setChannel] = useState("");
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    if (!allowed) { setLoading(false); return; }
    try {
      const res = await api.get("/marketing/templates");
      const templates = res?.templates || (Array.isArray(res) ? res : []);
      setItems(templates);
    } catch {} finally { setLoading(false); setRefreshing(false); }
  }, [allowed]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  if (!allowed) {
    return (
      <View style={[s.center, { paddingTop: insets.top + 60 }]} testID="templates-role-gate">
        <Ionicons name="lock-closed" size={36} color={colors.muted} />
        <Text style={s.gateText}>Not authorized</Text>
        <TouchableOpacity onPress={() => router.replace("/(app)")} style={s.gateBtn}>
          <Text style={s.gateBtnText}>Go Home</Text>
        </TouchableOpacity>
      </View>
    );
  }

  const filtered = channel ? items.filter((t) => t.channel === channel) : items;

  return (
    <View style={[s.root, { paddingTop: insets.top }]}>
      <View style={s.navBar}>
        <TouchableOpacity onPress={() => router.back()} hitSlop={12}>
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </TouchableOpacity>
        <Text style={s.navTitle}>Templates</Text>
        <View style={{ width: 22 }} />
      </View>
      <BreadcrumbBar title="Templates" />

      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.filterRow}>
        {CHANNELS.map((ch) => (
          <TouchableOpacity
            key={ch.key}
            style={[s.pill, channel === ch.key && s.pillActive]}
            onPress={() => setChannel(ch.key)}
            testID={`tpl-ch-${ch.key || "all"}`}
          >
            <Text style={[s.pillText, channel === ch.key && s.pillTextActive]}>{ch.label}</Text>
          </TouchableOpacity>
        ))}
      </ScrollView>

      {loading ? (
        <View style={s.center}><ActivityIndicator size="large" color={colors.brand} /></View>
      ) : (
        <FlatList
          data={filtered}
          keyExtractor={(t, i) => t.id || String(i)}
          contentContainerStyle={s.list}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.brand} />}
          ListEmptyComponent={
            <View style={s.emptyWrap}>
              <Ionicons name="document-text-outline" size={32} color={colors.muted} />
              <Text style={s.emptyText}>No templates</Text>
            </View>
          }
          renderItem={({ item }) => {
            const isActive = item.active ?? item.is_active ?? true;
            const displayName = item.name || item.code || "Untitled";
            return (
              <View style={s.card} testID={`tpl-${item.id}`}>
                <View style={s.cardTop}>
                  <View style={[s.chPill, item.channel === "sms" ? { backgroundColor: "#E0F2FE" } : { backgroundColor: "#F3E8FF" }]}>
                    <Text style={[s.chText, item.channel === "sms" ? { color: "#0369A1" } : { color: "#7E22CE" }]}>
                      {(item.channel || "email").toUpperCase()}
                    </Text>
                  </View>
                  <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                    {item.system && (
                      <View style={s.sysPill}><Text style={s.sysText}>SYSTEM</Text></View>
                    )}
                    <View style={[s.activeDot, { backgroundColor: isActive ? colors.success : colors.muted }]} />
                  </View>
                </View>
                <Text style={s.cardName}>{displayName}</Text>
                {item.subject ? <Text style={s.cardSubject} numberOfLines={1}>{item.subject}</Text> : null}
                {item.body ? <Text style={s.cardBody} numberOfLines={2}>{item.body}</Text> : null}
                {item.category ? <Text style={s.cardCategory}>{item.category.replace(/_/g, " ")}</Text> : null}
                <Text style={s.editNote}>Edit on web for full editor</Text>
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
  cardTop: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 6 },
  chPill: { paddingHorizontal: 8, paddingVertical: 2, borderRadius: 999 },
  chText: { fontFamily: font.bold, fontSize: 9, letterSpacing: 0.5 },
  sysPill: { backgroundColor: "#DBEAFE", paddingHorizontal: 6, paddingVertical: 1, borderRadius: 999 },
  sysText: { fontFamily: font.bold, fontSize: 8, color: "#1D4ED8", letterSpacing: 0.5 },
  activeDot: { width: 8, height: 8, borderRadius: 4 },
  cardName: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  cardSubject: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurfaceSecondary, marginTop: 2 },
  cardBody: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 4 },
  cardCategory: { fontFamily: font.medium, fontSize: 10, color: colors.brand, textTransform: "capitalize", marginTop: 4 },
  editNote: { fontFamily: font.regular, fontSize: 10, color: colors.brand, marginTop: spacing.sm, fontStyle: "italic" },
  emptyWrap: { alignItems: "center", paddingTop: 80 },
  emptyText: { fontFamily: font.medium, fontSize: fontSize.base, color: colors.muted, marginTop: 8 },
});
