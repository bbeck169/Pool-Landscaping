import React from "react";
import { View, Text, StyleSheet, TouchableOpacity } from "react-native";
import { Stack, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useAuth } from "@/src/auth";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";

export default function SettingsLayout() {
  const { user } = useAuth();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const role = String((user as any)?.role || "");
  const allowed = role === "admin" || role === "super_admin";

  if (!allowed) {
    return (
      <View style={[styles.gate, { paddingTop: insets.top + 60 }]} testID="settings-role-gate">
        <Ionicons name="lock-closed" size={36} color={colors.muted} />
        <Text style={styles.gateTitle}>Not authorized</Text>
        <Text style={styles.gateSub}>Settings are available to admins only.</Text>
        <TouchableOpacity onPress={() => router.replace("/(app)")} style={styles.gateBtn} testID="settings-gate-home-btn">
          <Text style={styles.gateBtnText}>Go Home</Text>
        </TouchableOpacity>
      </View>
    );
  }

  return <Stack screenOptions={{ headerShown: false }} />;
}

const styles = StyleSheet.create({
  gate: {
    flex: 1,
    backgroundColor: colors.surfaceSecondary,
    alignItems: "center",
    justifyContent: "center",
    padding: spacing.xl,
  },
  gateTitle: {
    fontFamily: font.bold,
    fontSize: fontSize.xl,
    color: colors.onSurface,
    marginTop: spacing.md,
  },
  gateSub: {
    fontFamily: font.regular,
    fontSize: fontSize.base,
    color: colors.muted,
    marginTop: spacing.sm,
    textAlign: "center",
  },
  gateBtn: {
    marginTop: spacing.xl,
    backgroundColor: colors.brand,
    paddingHorizontal: spacing.xl,
    paddingVertical: spacing.md,
    borderRadius: radius.md,
  },
  gateBtnText: {
    fontFamily: font.bold,
    fontSize: fontSize.base,
    color: "#fff",
  },
});
