// Phase 16 · Feb-2026 — AEO landing tab (mobile parity).
//
// A hub screen linking to each AEO sub-screen. Also renders the current
// AEO score if a scan exists (fetched from the visibility dashboard).
import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { router, useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Card, Loading } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";
import { RoleGate } from "@/src/components/RoleGate";
import { OfflineGate } from "@/src/components/OfflineGate";

type Tile = {
  key: string;
  title: string;
  subtitle: string;
  icon: any;
  route: string;
  color: string;
};

const TILES: Tile[] = [
  { key: "auditor",   title: "AEO Auditor",         subtitle: "Scan a URL for AI-ranking signals",       icon: "compass-outline",         route: "/aeo/auditor",         color: "#0284C7" },
  { key: "visibility", title: "AI Visibility",       subtitle: "How AI answer engines see your brand",    icon: "eye-outline",             route: "/aeo/visibility",      color: "#16A34A" },
  { key: "mentions",  title: "Brand Mentions",       subtitle: "Recent citations across LLMs",            icon: "chatbubbles-outline",     route: "/aeo/mentions",        color: "#7C3AED" },
  { key: "library",   title: "Response Library",     subtitle: "Reusable reply templates by platform",    icon: "library-outline",         route: "/aeo/library",         color: "#B45309" },
  { key: "publish",   title: "LLMs.txt Publish",     subtitle: "Netlify / Vercel / Cloudflare configs",    icon: "cloud-upload-outline",    route: "/aeo/publish-config",  color: "#DB2777" },
];

export default function AeoIndex() {
  const [score, setScore] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const s: any = await api.get("/aeo/visibility/dashboard");
      const val =
        s?.summary?.avg_score ?? s?.avg_score ?? s?.score ?? null;
      setScore(typeof val === "number" ? Math.round(val) : null);
    } catch {
      setScore(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  return (
    <OfflineGate testID="aeo-offline-gate" message="AEO Suite requires an internet connection.">
    <RoleGate level="admin_plus">
      <View style={styles.container}>
        <Header title="AEO Suite" />
        <ScrollView contentContainerStyle={styles.body}>
          <Card style={styles.scoreCard}>
            <View style={{ flex: 1 }}>
              <Text style={styles.scoreLabel}>Current AEO score</Text>
              <Text style={styles.scoreValue} testID="aeo-score-value">
                {loading ? "…" : score == null ? "—" : `${score}`}
              </Text>
              <Text style={styles.scoreHint}>
                {score == null
                  ? "Run a scan to see your first score."
                  : "Updated from your latest visibility probe."}
              </Text>
            </View>
            <Ionicons name="stats-chart" size={44} color={colors.brand} />
          </Card>

          {TILES.map((t) => (
            <Pressable
              key={t.key}
              testID={`aeo-tile-${t.key}`}
              accessibilityLabel={t.title}
              onPress={() => router.push(t.route as any)}
              style={({ pressed }) => [
                styles.tile,
                pressed && { opacity: 0.7 },
              ]}
            >
              <View style={[styles.tileIcon, { backgroundColor: `${t.color}15` }]}>
                <Ionicons name={t.icon} size={22} color={t.color} />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.tileTitle}>{t.title}</Text>
                <Text style={styles.tileSub}>{t.subtitle}</Text>
              </View>
              <Ionicons name="chevron-forward" size={20} color={colors.muted} />
            </Pressable>
          ))}
        </ScrollView>
      </View>
    </RoleGate>
    </OfflineGate>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.surface },
  body: { padding: spacing.lg, gap: spacing.md, paddingBottom: spacing["3xl"] },
  scoreCard: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: spacing.md,
  },
  scoreLabel: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted, textTransform: "uppercase", letterSpacing: 0.5 },
  scoreValue: { fontFamily: font.bold, fontSize: 36, color: colors.onSurface, marginTop: 4 },
  scoreHint: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
  tile: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    padding: spacing.md,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
  },
  tileIcon: {
    width: 44, height: 44,
    borderRadius: radius.md,
    alignItems: "center", justifyContent: "center",
  },
  tileTitle: { fontFamily: font.semibold, fontSize: fontSize.lg, color: colors.onSurface },
  tileSub: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
});
