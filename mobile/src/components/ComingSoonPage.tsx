import React from "react";
import { View, Text, StyleSheet, Pressable, Linking } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter, usePathname } from "expo-router";

import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";

/**
 * Phase (Feb-2026) — shared "Coming soon on mobile" stub for admin
 * nav entries that don't have a dedicated mobile screen yet (Tier 2
 * in ``mobile/src/nav/adminNav.ts``). Route files under
 * ``mobile/app/**`` re-export this component so ~25 stubs each stay
 * a single line.
 *
 * The route ALSO accepts ``?title=...&webPath=...`` search params so
 * ad-hoc callers (e.g., other admin surfaces linking to a still-
 * missing screen) can control the header text without spinning up a
 * new stub file.
 */
export default function ComingSoonPage() {
  const params = useLocalSearchParams<{ title?: string; webPath?: string }>();
  const pathname = usePathname() || "";
  const router = useRouter();

  const title = (params.title as string) || prettyFromPath(pathname);
  const webPath = (params.webPath as string) || pathname;
  const webBase = process.env.EXPO_PUBLIC_WEB_URL || "";

  const openOnWeb = () => {
    if (!webBase) return;
    const url = `${webBase.replace(/\/$/, "")}${webPath}`;
    Linking.openURL(url);
  };

  return (
    <View style={s.root} testID="coming-soon-page">
      <Header title={title} back subtitle="Coming soon on mobile" />
      <View style={s.body}>
        <View style={s.iconBox}>
          <Ionicons name="hourglass-outline" size={40} color={colors.brand} />
        </View>
        <Text style={s.title}>{title}</Text>
        <Text style={s.copy}>
          This page is fully wired on the web admin console. Mobile parity
          is on the roadmap — the drawer entry is here today so you can
          see the full navigation tree.
        </Text>
        {webBase ? (
          <Pressable
            onPress={openOnWeb}
            style={({ pressed }) => [s.cta, pressed && { opacity: 0.85 }]}
            testID="coming-soon-open-on-web"
          >
            <Ionicons name="open-outline" size={16} color="#fff" />
            <Text style={s.ctaText}>Open on the web app</Text>
          </Pressable>
        ) : null}
        <Pressable onPress={() => router.back()} testID="coming-soon-back" style={s.linkBtn}>
          <Text style={s.linkText}>← Back</Text>
        </Pressable>
      </View>
    </View>
  );
}

function prettyFromPath(p: string): string {
  const seg = (p || "").split("/").filter(Boolean).pop() || "Coming soon";
  return seg.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  body: { flex: 1, alignItems: "center", justifyContent: "center", padding: spacing.xl, gap: spacing.md },
  iconBox: {
    width: 80, height: 80, borderRadius: 40,
    backgroundColor: colors.brandTertiary,
    alignItems: "center", justifyContent: "center",
  },
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
