/**
 * Phase 39B · mobile port of web `mass-messaging/MassMessagingCard.jsx`.
 * Admin / super_admin only (self-guards, same as web). Web opens an
 * inline compose dialog; mobile routes to the existing broadcasts
 * composer at `/marketing/broadcasts`.
 */
import React from "react";
import { View, Text, StyleSheet, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { useAuth } from "@/src/auth";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";

export default function MassMessagingCard() {
  const { user } = useAuth() as any;
  const router = useRouter();
  const role = String(user?.role || "").toLowerCase();
  if (role !== "admin" && role !== "super_admin") return null;

  return (
    <View style={s.card} testID="mass-messaging-card">
      <View style={s.icon}>
        <Ionicons name="megaphone-outline" size={22} color={colors.brand} />
      </View>
      <View style={s.body}>
        <Text style={s.title} testID="mass-messaging-card-title">Mass Messaging</Text>
        <Text style={s.sub}>Send a broadcast to all active customers</Text>
        <View style={s.chips}>
          <Ionicons name="mail-outline" size={11} color={colors.muted} />
          <Text style={s.chip}>Email</Text>
          <Ionicons name="chatbox-ellipses-outline" size={11} color={colors.muted} />
          <Text style={s.chip}>SMS</Text>
        </View>
      </View>
      <Pressable
        onPress={() => router.push("/marketing/broadcasts" as any)}
        style={({ pressed }) => [s.btn, pressed && { opacity: 0.85 }]}
        testID="mass-messaging-compose-btn"
        accessibilityRole="button"
      >
        <Text style={s.btnText}>Compose</Text>
      </Pressable>
    </View>
  );
}

const s = StyleSheet.create({
  card: {
    flexDirection: "row", alignItems: "center", gap: spacing.md, padding: spacing.lg, marginBottom: spacing.lg,
    backgroundColor: colors.surface, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.border,
  },
  icon: { width: 44, height: 44, borderRadius: radius.md, backgroundColor: colors.brandTertiary, alignItems: "center", justifyContent: "center" },
  body: { flex: 1 },
  title: { fontFamily: font.bold, fontSize: fontSize.base, color: colors.onSurface },
  sub: { fontFamily: font.regular, fontSize: 12, color: colors.muted, marginTop: 2 },
  chips: { flexDirection: "row", alignItems: "center", gap: 4, marginTop: 4 },
  chip: { fontFamily: font.medium, fontSize: 11, color: colors.muted, marginRight: 8 },
  btn: { minHeight: 44, paddingHorizontal: spacing.lg, borderRadius: radius.md, backgroundColor: colors.brand, alignItems: "center", justifyContent: "center" },
  btnText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: "#fff" },
});
