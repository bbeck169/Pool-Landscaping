/**
 * Server-rendered email preview — P2 #11 mobile parity.
 *
 * Renders the HTML from POST /comms/email-templates/{code}/preview in a
 * sandboxed WebView (react-native-webview, already installed):
 *   - JS disabled (email HTML never needs it).
 *   - Only the initial inline document loads in-frame; tapped links
 *     open in the system browser instead of navigating the preview.
 * Expo-web bundle: WebView is native-only, so we fall back to a
 * plain-text rendering of the HTML (previous mobile behaviour).
 */
import React, { useState } from "react";
import { View, Text, StyleSheet, ActivityIndicator, Linking, Platform } from "react-native";
import { WebView } from "react-native-webview";

import { colors, font, fontSize, radius, spacing } from "@/src/theme";

export function isInlineDocUrl(url?: string | null): boolean {
  return !url || url === "about:blank" || url.startsWith("about:") || url.startsWith("data:");
}

export default function EmailPreviewWebView({ html }: { html: string }) {
  const [failed, setFailed] = useState(false);

  if (Platform.OS === "web") {
    return (
      <View style={s.textBox} testID="comms-email-preview-text">
        <Text style={s.text}>{html.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim()}</Text>
      </View>
    );
  }
  if (failed) {
    return (
      <View style={s.center} testID="comms-email-preview-render-error">
        <Text style={s.err}>Couldn&apos;t render the preview.</Text>
      </View>
    );
  }
  return (
    <WebView
      testID="comms-email-preview-webview"
      style={s.web}
      originWhitelist={["*"]}
      source={{ html }}
      javaScriptEnabled={false}
      startInLoadingState
      renderLoading={() => (
        <View style={s.center}>
          <ActivityIndicator color={colors.brand} />
        </View>
      )}
      onError={() => setFailed(true)}
      onShouldStartLoadWithRequest={(req) => {
        if (isInlineDocUrl(req.url)) return true;
        Linking.openURL(req.url).catch(() => {});
        return false;
      }}
    />
  );
}

const s = StyleSheet.create({
  web: { flex: 1, backgroundColor: "#FFFFFF", borderRadius: radius.sm },
  center: { ...StyleSheet.absoluteFillObject, alignItems: "center", justifyContent: "center" },
  err: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.error },
  textBox: {
    backgroundColor: "#FFFFFF", borderRadius: radius.sm, padding: spacing.md,
    borderWidth: 1, borderColor: colors.border,
  },
  text: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurface, lineHeight: 20 },
});
