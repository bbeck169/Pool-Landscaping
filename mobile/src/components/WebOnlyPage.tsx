import React from "react";
import { View, Text, StyleSheet, Pressable, Linking, Platform, ActivityIndicator } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter, usePathname } from "expo-router";
import { WebView } from "react-native-webview";

import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";

/**
 * Phase (Feb-2026) — shared "Web app only" fallback for Tier-3 admin
 * nav entries. Primary strategy: in-app ``<WebView>`` pointing at the
 * web app URL. On the Expo web bundle (where WebView is native-only
 * and throws), we degrade to a "Open in a new tab" CTA that calls
 * ``Linking.openURL``.
 */
export default function WebOnlyPage() {
  const params = useLocalSearchParams<{ title?: string; webPath?: string }>();
  const pathname = usePathname() || "";
  const router = useRouter();

  const title = (params.title as string) || "Web-only feature";
  const webPath = (params.webPath as string) || pathname;
  const webBase = process.env.EXPO_PUBLIC_WEB_URL || "";
  const url = webBase ? `${webBase.replace(/\/$/, "")}${webPath}` : "";

  const openExternally = () => { if (url) Linking.openURL(url); };

  if (!url) {
    return (
      <View style={s.root} testID="web-only-page">
        <Header title={title} back subtitle="Available on the web app" />
        <View style={s.body}>
          <Ionicons name="cloud-offline-outline" size={40} color={colors.muted} />
          <Text style={s.title}>{title}</Text>
          <Text style={s.copy}>
            This feature lives on the web admin console. The mobile bundle
            hasn't been given a ``EXPO_PUBLIC_WEB_URL`` yet, so we can't
            open it here directly — ask an admin for the URL.
          </Text>
        </View>
      </View>
    );
  }

  return (
    <View style={s.root} testID="web-only-page">
      <Header
        title={title}
        back
        subtitle="Web-only · shown inside the mobile app"
      />
      {Platform.OS === "web" ? (
        // On the Expo web bundle the ``react-native-webview`` module is
        // native-only. Render the direct-launch CTA instead.
        <View style={s.body} testID="web-only-web-fallback">
          <Ionicons name="open-outline" size={40} color={colors.brand} />
          <Text style={s.title}>{title}</Text>
          <Text style={s.copy}>
            Full experience on the web admin console:
          </Text>
          <Pressable
            onPress={openExternally}
            style={({ pressed }) => [s.cta, pressed && { opacity: 0.85 }]}
            testID="web-only-open"
          >
            <Ionicons name="arrow-forward-outline" size={16} color="#fff" />
            <Text style={s.ctaText}>Open on the web app</Text>
          </Pressable>
          <Pressable onPress={() => router.back()} style={s.linkBtn} testID="web-only-back">
            <Text style={s.linkText}>← Back</Text>
          </Pressable>
        </View>
      ) : (
        <WebView
          source={{ uri: url }}
          style={{ flex: 1 }}
          startInLoadingState
          renderLoading={() => (
            <View style={s.loadingBox}>
              <ActivityIndicator color={colors.brand} size="large" />
            </View>
          )}
          testID="web-only-webview"
        />
      )}
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  body: { flex: 1, alignItems: "center", justifyContent: "center", padding: spacing.xl, gap: spacing.md },
  loadingBox: { flex: 1, alignItems: "center", justifyContent: "center" },
  title: { fontFamily: font.bold, fontSize: fontSize["2xl"], color: colors.onSurface, textAlign: "center" },
  copy: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted, textAlign: "center", maxWidth: 340, lineHeight: 22 },
  cta: {
    flexDirection: "row", alignItems: "center", gap: 8,
    backgroundColor: colors.brand,
    paddingHorizontal: spacing.lg, paddingVertical: 12,
    borderRadius: radius.md,
    marginTop: spacing.md,
  },
  ctaText: { fontFamily: font.bold, color: "#fff", fontSize: fontSize.base },
  linkBtn: { padding: 8 },
  linkText: { fontFamily: font.semibold, color: colors.brand, fontSize: fontSize.base },
});
