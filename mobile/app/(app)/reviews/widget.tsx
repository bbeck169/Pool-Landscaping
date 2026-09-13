/** Widget & embed — Phase 3 mobile (read-only). */
import React, { useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, Alert, Linking } from "react-native";
import * as Clipboard from "expo-clipboard";
import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Header } from "@/src/components/widgets";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";
import { api } from "@/src/api";
import { useToast } from "@/src/components/ToastProvider";

export default function ReviewsWidgetScreen() {
  const { showToast } = useToast();
  const insets = useSafeAreaInsets();
  const [slug, setSlug] = useState("");

  useEffect(() => {
    api.get("/tenants/current").then((t: any) => setSlug(t?.slug || "")).catch(() => setSlug(""));
  }, []);

  const backendOrigin = (process.env.EXPO_PUBLIC_BACKEND_URL || "").replace(/\/$/, "");
  const embedUrl = slug ? `${backendOrigin}/api/reviews/public/widget/${encodeURIComponent(slug)}.js` : "";
  const publicPage = slug ? `${backendOrigin.replace(/\/api\/?$/, "")}/reviews/${encodeURIComponent(slug)}` : "";
  const embedSnippet = slug ? `<div id="pool-crm-reviews"></div>\n<script src="${embedUrl}" defer></script>` : "";

  const copy = async (t: string, label: string) => {
    if (!t) return;
    await Clipboard.setStringAsync(t);
    showToast(`${label} copied to clipboard.`);
  };

  return (
    <View testID="reviews-widget-screen" style={styles.root}>
      <Header title="Widget & Embed" subtitle="Copy the snippet to your marketing site" back />
      <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: insets.bottom + 24 }}>
        <View style={styles.card}>
          <Text style={styles.sectionTitle}>Embed snippet</Text>
          <View style={styles.snippet}>
            <Text style={styles.snippetText} selectable>{embedSnippet || "(loading…)"}</Text>
          </View>
          <TouchableOpacity testID="reviews-widget-copy-embed" style={styles.primaryBtn} onPress={() => copy(embedSnippet, "Embed snippet")}>
            <Ionicons name="copy-outline" size={14} color="#fff" />
            <Text style={styles.primaryBtnLabel}>Copy embed</Text>
          </TouchableOpacity>
        </View>

        <View style={styles.card}>
          <Text style={styles.sectionTitle}>Public widget URL</Text>
          <Text style={styles.link} numberOfLines={2}>{publicPage || "(loading…)"}</Text>
          <View style={{ flexDirection: "row", gap: spacing.sm, marginTop: spacing.sm }}>
            <TouchableOpacity testID="reviews-widget-copy-url" style={styles.secondaryBtn} onPress={() => copy(publicPage, "Public URL")}>
              <Ionicons name="copy-outline" size={13} color={colors.onSurface} />
              <Text style={styles.secondaryBtnLabel}>Copy</Text>
            </TouchableOpacity>
            <TouchableOpacity testID="reviews-widget-open-url" style={styles.secondaryBtn} onPress={() => publicPage && Linking.openURL(publicPage)}>
              <Ionicons name="open-outline" size={13} color={colors.onSurface} />
              <Text style={styles.secondaryBtnLabel}>Open</Text>
            </TouchableOpacity>
          </View>
        </View>

        <View style={styles.hint}>
          <Ionicons name="information-circle-outline" size={16} color={colors.muted} />
          <Text style={styles.hintText}>Widget layout / config edits stay on the web admin — this mobile screen is read-only by design.</Text>
        </View>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  card: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, padding: spacing.lg, marginBottom: spacing.md },
  sectionTitle: { fontFamily: font.bold, fontSize: 10, color: colors.muted, letterSpacing: 0.5, textTransform: "uppercase", marginBottom: 8 },
  snippet: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radius.sm, padding: 10 },
  snippetText: { fontFamily: "Courier", fontSize: 10, color: colors.onSurface, lineHeight: 16 },
  link: { fontFamily: font.regular, fontSize: 12, color: colors.brand, marginTop: 2 },
  primaryBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, backgroundColor: colors.brand, padding: 10, borderRadius: radius.sm, marginTop: spacing.md },
  primaryBtnLabel: { fontFamily: font.bold, fontSize: fontSize.sm, color: "#fff" },
  secondaryBtn: { flexDirection: "row", alignItems: "center", gap: 6, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface, borderRadius: radius.sm, paddingHorizontal: 12, paddingVertical: 6 },
  secondaryBtnLabel: { fontFamily: font.medium, fontSize: 11, color: colors.onSurface },
  hint: { flexDirection: "row", alignItems: "flex-start", gap: 8, padding: spacing.md, backgroundColor: colors.surfaceSecondary, borderRadius: radius.sm, borderWidth: 1, borderColor: colors.border },
  hintText: { flex: 1, fontFamily: font.regular, fontSize: 11, color: colors.muted, lineHeight: 16 },
});
