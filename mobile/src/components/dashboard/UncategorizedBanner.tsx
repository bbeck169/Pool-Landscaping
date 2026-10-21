/**
 * TD-84 b2 · Dashboard "Revenue insights" uncategorized banner (web
 * Dashboard.jsx `uncategorized-banner`). GET /reports/uncategorized-count
 * (admin/super_admin); renders only when count > 0; tap → report screen.
 */
import React, { useCallback, useState } from "react";
import { Text, Pressable, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";

import { api } from "@/src/api";
import { font, fontSize, radius, spacing } from "@/src/theme";
import { bannerText } from "@/src/lib/uncategorized";

export default function UncategorizedBanner() {
  const router = useRouter();
  const [count, setCount] = useState(0);

  // Refetch on focus so the count drops after assigning in the report.
  useFocusEffect(useCallback(() => {
    let live = true;
    api.get("/reports/uncategorized-count")
      .then((r: any) => { if (live) setCount(Number(r?.count || 0)); })
      .catch(() => { if (live) setCount(0); });
    return () => { live = false; };
  }, []));

  if (count <= 0) return null;
  return (
    <Pressable
      onPress={() => router.push("/reports/uncategorized-items" as any)}
      style={({ pressed }) => [s.banner, pressed && { opacity: 0.85 }]}
      testID="uncategorized-banner" accessibilityRole="button"
    >
      <Ionicons name="warning" size={18} color="#B45309" />
      <Text style={s.text} testID="uncategorized-banner-text">{bannerText(count)}</Text>
      <Text style={s.cta}>Review →</Text>
    </Pressable>
  );
}

const s = StyleSheet.create({
  banner: { flexDirection: "row", alignItems: "center", gap: spacing.sm, minHeight: 48, padding: spacing.md, marginBottom: spacing.md, borderRadius: radius.md, backgroundColor: "#FEF3C7", borderWidth: 1, borderColor: "#FCD34D" },
  text: { flex: 1, fontFamily: font.semibold, fontSize: fontSize.base, color: "#78350F" },
  cta: { fontFamily: font.bold, fontSize: fontSize.sm, color: "#78350F", textDecorationLine: "underline" },
});
