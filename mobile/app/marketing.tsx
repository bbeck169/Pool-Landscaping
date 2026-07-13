import React from "react";
import { View, Text, StyleSheet, ScrollView, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";

const CARDS = [
  { icon: "documents-outline", label: "Form Builder", sub: "Lead-capture forms", route: "/forms", tint: colors.brand },
  { icon: "git-branch-outline", label: "Automation", sub: "Workflow rules", route: "/automations", tint: colors.brandSecondary },
  { icon: "megaphone-outline", label: "Communication", sub: "Email & SMS campaigns", route: "/campaigns", tint: "#C2410C" },
  { icon: "star-outline", label: "Reviews", sub: "Ratings & responses", route: "/reviews", tint: "#CA8A04" },
  { icon: "map-outline", label: "Map Check-ins", sub: "Field crew locations", route: "/checkins", tint: "#0369A1" },
  { icon: "grid-outline", label: "Rank Grid", sub: "Local SEO tracking", route: "/rank-grid", tint: "#7C3AED" },
];

export default function Marketing() {
  const router = useRouter();
  return (
    <View style={styles.root}>
      <Header title="Marketing" back subtitle="Grow your business" />
      <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}>
        <View style={styles.grid}>
          {CARDS.map((c) => (
            <Pressable key={c.label} style={styles.card} onPress={() => router.push(c.route as any)} testID={`marketing-${c.label.split(" ")[0].toLowerCase()}`}>
              <View style={[styles.icon, { backgroundColor: c.tint + "1A" }]}>
                <Ionicons name={c.icon as any} size={22} color={c.tint} />
              </View>
              <Text style={styles.label}>{c.label}</Text>
              <Text style={styles.sub}>{c.sub}</Text>
            </Pressable>
          ))}
        </View>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.md },
  card: { width: "47.5%", flexGrow: 1, backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.lg, borderWidth: 1, borderColor: colors.border },
  icon: { width: 44, height: 44, borderRadius: radius.md, alignItems: "center", justifyContent: "center", marginBottom: spacing.sm },
  label: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  sub: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
});
