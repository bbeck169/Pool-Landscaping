/**
 * Marketing Hub — admin/super_admin only.
 * Links to: Templates, Segments, Sequences, Review Requests, Analytics.
 */
import React from "react";
import { View, Text, StyleSheet, ScrollView, TouchableOpacity } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useRouter } from "expo-router";

import { useAuth } from "@/src/auth";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";
import BreadcrumbBar from "@/src/components/nav/BreadcrumbBar";

const ITEMS = [
  { icon: "document-text-outline" as const, label: "Templates", desc: "Email & SMS templates", route: "/marketing/templates" },
  { icon: "people-outline" as const, label: "Segments", desc: "Audience segments & filters", route: "/marketing/segments" },
  { icon: "git-branch-outline" as const, label: "Sequences", desc: "Drip campaign sequences", route: "/marketing/sequences" },
  { icon: "star-outline" as const, label: "Review Requests", desc: "Review request queue", route: "/marketing/review-requests" },
  { icon: "bar-chart-outline" as const, label: "Analytics", desc: "Campaign KPIs & stats", route: "/marketing/analytics" },
  { icon: "ban-outline" as const, label: "Suppressions", desc: "Unsubscribe & bounce list", route: "/marketing/suppressions" },
];

export default function MarketingHub() {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { user } = useAuth();

  const role = String((user as any)?.role || "");
  const allowed = role === "admin" || role === "super_admin";

  if (!allowed) {
    return (
      <View style={[s.center, { paddingTop: insets.top + 60 }]} testID="marketing-role-gate">
        <Ionicons name="lock-closed" size={36} color={colors.muted} />
        <Text style={s.gateText}>Not authorized</Text>
        <Text style={s.gateSubtext}>Marketing is available to admins only.</Text>
        <TouchableOpacity onPress={() => router.replace("/(app)")} style={s.gateBtn} testID="marketing-go-home">
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
        <Text style={s.navTitle}>Marketing</Text>
        <View style={{ width: 22 }} />
      </View>
      <BreadcrumbBar title="Marketing" />
      <ScrollView contentContainerStyle={s.scroll}>
        {ITEMS.map((item) => (
          <TouchableOpacity
            key={item.route}
            style={s.card}
            onPress={() => router.push(item.route as any)}
            testID={`mkt-${item.label.toLowerCase().replace(/ /g, "-")}`}
          >
            <View style={s.iconWrap}>
              <Ionicons name={item.icon} size={22} color={colors.brand} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={s.cardLabel}>{item.label}</Text>
              <Text style={s.cardDesc}>{item.desc}</Text>
            </View>
            <Ionicons name="chevron-forward" size={18} color={colors.muted} />
          </TouchableOpacity>
        ))}
      </ScrollView>
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: "#F8FAFC" },
  center: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface, padding: 24 },
  gateText: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface, marginTop: 12 },
  gateSubtext: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted, marginTop: 4, textAlign: "center" },
  gateBtn: { marginTop: 20, paddingHorizontal: 24, paddingVertical: 12, borderRadius: radius.md, backgroundColor: colors.brand },
  gateBtnText: { fontFamily: font.semibold, fontSize: fontSize.base, color: "#fff" },
  navBar: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.lg, paddingVertical: spacing.md, borderBottomWidth: 1, borderBottomColor: colors.border, backgroundColor: colors.surface },
  navTitle: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  scroll: { padding: spacing.lg, paddingBottom: 40 },
  card: { flexDirection: "row", alignItems: "center", gap: 12, backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.lg, marginBottom: spacing.sm, borderWidth: 1, borderColor: colors.border },
  iconWrap: { width: 42, height: 42, borderRadius: 12, backgroundColor: "#F0F9FF", alignItems: "center", justifyContent: "center" },
  cardLabel: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  cardDesc: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 1 },
});
