/**
 * Phase 12 · Public Add-Card page (WebView wrapper).
 * 
 * Opens the web version at /portal/add-card?token=<jwt> inside a WebView.
 * The web page is already mobile-responsive with Stripe Elements.
 * Token comes from the email/SMS magic-link.
 */
import React from "react";
import { View, Text, StyleSheet, ActivityIndicator, TouchableOpacity } from "react-native";
import { WebView } from "react-native-webview";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useLocalSearchParams, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";

import { colors, font, fontSize, spacing, radius } from "@/src/theme";

const WEB_BASE = process.env.EXPO_PUBLIC_BACKEND_URL || "";

export default function AddCardScreen() {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { token } = useLocalSearchParams<{ token?: string }>();

  if (!token) {
    return (
      <View style={[s.center, { paddingTop: insets.top + 60 }]} testID="add-card-no-token">
        <Ionicons name="card-outline" size={40} color={colors.muted} />
        <Text style={s.errTitle}>Invalid Link</Text>
        <Text style={s.errSub}>This add-card link is missing a token. Please use the link from your email or SMS.</Text>
        <TouchableOpacity onPress={() => router.back()} style={s.btn} testID="add-card-back">
          <Text style={s.btnText}>Go Back</Text>
        </TouchableOpacity>
      </View>
    );
  }

  const webUrl = `${WEB_BASE}/portal/add-card?token=${encodeURIComponent(token)}`;

  return (
    <View style={[s.root, { paddingTop: insets.top }]}>
      <View style={s.navBar}>
        <TouchableOpacity onPress={() => router.back()} hitSlop={12} testID="add-card-nav-back">
          <Ionicons name="close" size={22} color={colors.onSurface} />
        </TouchableOpacity>
        <Text style={s.navTitle}>Add Payment Method</Text>
        <View style={{ width: 22 }} />
      </View>
      <WebView
        source={{ uri: webUrl }}
        style={{ flex: 1 }}
        startInLoadingState
        renderLoading={() => (
          <View style={s.loading}>
            <ActivityIndicator size="large" color={colors.brand} />
            <Text style={s.loadingText}>Loading secure form…</Text>
          </View>
        )}
        testID="add-card-webview"
      />
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 32 },
  errTitle: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface, marginTop: 12 },
  errSub: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted, textAlign: "center", marginTop: 8 },
  btn: { marginTop: 24, paddingHorizontal: 24, paddingVertical: 12, borderRadius: radius.md, backgroundColor: colors.brand },
  btnText: { fontFamily: font.semibold, fontSize: fontSize.base, color: "#fff" },
  navBar: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.lg, paddingVertical: spacing.md, borderBottomWidth: 1, borderBottomColor: colors.border },
  navTitle: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  loading: { position: "absolute", top: 0, left: 0, right: 0, bottom: 0, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface },
  loadingText: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 8 },
});
