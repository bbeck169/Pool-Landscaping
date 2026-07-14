/**
 * Phase 17A/B/C · Mobile SEO Suite — shared helpers.
 * Admin gate + score chip + severity dot + brand pill. Kept minimal so each
 * screen file stays focused on its module.
 */
import React from "react";
import { View, Text, StyleSheet, ActivityIndicator } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useAuth } from "@/src/auth";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";

export function isSeoAdmin(user: any): boolean {
  const r = user?.role || "";
  return r === "admin" || r === "super_admin";
}

export function AdminOnlyGate({
  title, children,
}: { title: string; children: React.ReactNode }) {
  const { user } = useAuth();
  if (!isSeoAdmin(user)) {
    return (
      <View style={styles.root}>
        <Header title={title} />
        <View style={styles.forbidWrap}>
          <Ionicons name="lock-closed-outline" size={28} color={colors.muted} />
          <Text style={styles.forbidTitle}>Admins only</Text>
          <Text style={styles.forbidBody}>
            This screen is available to Admins and Super Admins.
          </Text>
        </View>
      </View>
    );
  }
  return <>{children}</>;
}

export function ScoreChip({ value, size = "sm" }: { value: number | null | undefined;
                                                     size?: "sm" | "lg" }) {
  const v = value ?? null;
  const color =
    v == null ? colors.muted :
    v >= 80 ? "#059669" :
    v >= 60 ? "#D97706" : "#DC2626";
  const fs = size === "lg" ? 32 : 18;
  const label = size === "lg" ? "/ 100" : "";
  return (
    <View style={{ alignItems: "center" }}>
      <Text style={{ fontFamily: font.bold, fontSize: fs, color }}>
        {v ?? "—"}
      </Text>
      {label ? (
        <Text style={{ fontFamily: font.regular, fontSize: 10,
                        color: colors.muted }}>{label}</Text>
      ) : null}
    </View>
  );
}

export function SeverityDot({ severity }: { severity: string }) {
  const c = severity === "critical" ? "#DC2626" :
             severity === "warning" ? "#D97706" : "#2563EB";
  return (
    <View style={{ width: 8, height: 8, borderRadius: 4,
                    backgroundColor: c, marginRight: 8 }} />
  );
}

export function BrandPill({ text, tone = "brand" }: {
  text: string; tone?: "brand" | "green" | "amber" | "red" | "grey";
}) {
  const map: Record<string, { bg: string; fg: string }> = {
    brand:  { bg: colors.brandTertiary, fg: colors.brand },
    green:  { bg: "#DCFCE7", fg: "#166534" },
    amber:  { bg: "#FEF3C7", fg: "#92400E" },
    red:    { bg: "#FEE2E2", fg: "#991B1B" },
    grey:   { bg: "#F1F5F9", fg: "#475569" },
  };
  const m = map[tone] || map.brand;
  return (
    <View style={{ backgroundColor: m.bg, paddingHorizontal: 8,
                    paddingVertical: 3, borderRadius: 999 }}>
      <Text style={{ color: m.fg, fontFamily: font.bold, fontSize: 10 }}>
        {text}
      </Text>
    </View>
  );
}

export function CenterLoader() {
  return (
    <View style={{ padding: spacing.xl, alignItems: "center" }}>
      <ActivityIndicator color={colors.brand} />
    </View>
  );
}

export function DesktopHint({ text }: { text: string }) {
  return (
    <View style={styles.hintWrap}>
      <Ionicons name="desktop-outline" size={16} color={colors.brand} />
      <Text style={styles.hintText}>{text}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  forbidWrap: {
    padding: spacing["2xl"],
    alignItems: "center",
    gap: spacing.sm,
  },
  forbidTitle: {
    fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface,
    marginTop: spacing.sm,
  },
  forbidBody: {
    fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted,
    textAlign: "center",
  },
  hintWrap: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    backgroundColor: colors.brandTertiary,
    padding: spacing.md,
    borderRadius: radius.md,
    marginBottom: spacing.md,
  },
  hintText: {
    fontFamily: font.semibold, fontSize: fontSize.sm,
    color: colors.brand, flex: 1,
  },
});
