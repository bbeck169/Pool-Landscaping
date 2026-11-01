/**
 * TD-84 b1 · Customers by Service Category row (web
 * `components/dashboard/ServiceCategoryTileRow.jsx` parity).
 * GET /dashboard/service-category-breakdown (admin + manager) → 4 tiles
 * Pool / Landscaping / Both / Not set; tap → Customers list filtered by
 * `?service_category=`. Skeletons while loading, hidden on any error.
 */
import React, { useEffect, useState } from "react";
import { View, Text, Pressable, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api";
import { font, fontSize, money, radius, spacing } from "@/src/theme";

export type ServiceCategoryKey = "pool" | "landscaping" | "both" | "unset";
export const SERVICE_CATEGORY_LABELS: Record<ServiceCategoryKey, string> = {
  pool: "Pool", landscaping: "Landscaping", both: "Both", unset: "Not set",
};
/** Route-param guard — values outside the enum are ignored (backend parity). */
export const parseServiceCategory = (v: unknown): ServiceCategoryKey | null =>
  typeof v === "string" && Object.prototype.hasOwnProperty.call(SERVICE_CATEGORY_LABELS, v) ? (v as ServiceCategoryKey) : null;

type Bucket = { customers?: number; active_jobs?: number; mtd_revenue?: number };
const TILES: { key: ServiceCategoryKey; icon: any; bg: string; border: string; iconBg: string; stats: boolean }[] = [
  { key: "pool", icon: "water", bg: "#ECFEFF", border: "#06B6D4", iconBg: "#0891B2", stats: true },
  { key: "landscaping", icon: "leaf", bg: "#ECFDF5", border: "#10B981", iconBg: "#047857", stats: true },
  { key: "both", icon: "grid", bg: "#FEF3C7", border: "#D97706", iconBg: "#B45309", stats: true },
  { key: "unset", icon: "help-circle", bg: "#F3F4F6", border: "#64748B", iconBg: "#475569", stats: false },
];
const n = (v: unknown) => Number(v || 0).toLocaleString();

// Tile overflow fix — the row wraps, so a value that can't sit beside its
// label drops onto its own line (label stacked above value). A value wider
// than the whole row shrinks to fit (≥ 70%, same numberOfLines +
// adjustsFontSizeToFit pattern as the dashboard payment widget) instead of
// bleeding past the tile border.
export const STAT_VALUE_MIN_FONT_SCALE = 0.7;

function StatLine({ label, value, testID }: { label: string; value: string; testID: string }) {
  return (
    <View style={s.stat} testID={testID}>
      <Text style={s.statLabel} testID={`${testID}-label`}>{label}</Text>
      <Text
        style={s.statValue}
        numberOfLines={1}
        adjustsFontSizeToFit
        minimumFontScale={STAT_VALUE_MIN_FONT_SCALE}
        testID={`${testID}-value`}
      >
        {value}
      </Text>
    </View>
  );
}

export default function ServiceCategoryTileRow({ width }: { width: number }) {
  const router = useRouter();
  const [data, setData] = useState<Record<string, Bucket> | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let mounted = true;
    api.get("/dashboard/service-category-breakdown")
      .then((d: any) => { if (mounted) setData(d || {}); })
      .catch(() => { if (mounted) setError(true); });
    return () => { mounted = false; };
  }, []);

  if (error) return null;

  return (
    <View style={s.grid} testID="dashboard-service-category-row">
      {data ? TILES.map((t) => {
        const b = data[t.key] || {};
        const id = `kpi-service-category-${t.key}`;
        return (
          <Pressable
            key={t.key} testID={id} accessibilityRole="button"
            accessibilityLabel={`${SERVICE_CATEGORY_LABELS[t.key]}: ${n(b.customers)} customers`}
            onPress={() => router.push({ pathname: "/(app)/customers", params: { service_category: t.key } } as any)}
            style={({ pressed }) => [s.tile, { width, backgroundColor: t.bg, borderColor: t.border, borderLeftColor: t.border }, pressed && { opacity: 0.85 }]}
          >
            <View style={s.head}>
              <View style={[s.icon, { backgroundColor: t.iconBg }]}><Ionicons name={t.icon} size={18} color="#fff" /></View>
              <View style={{ flex: 1 }}>
                <Text style={s.title} numberOfLines={1}>{SERVICE_CATEGORY_LABELS[t.key]}</Text>
                <Text style={s.count} testID={`${id}-customers`}>{n(b.customers)}</Text>
                <Text style={s.caption}>customers</Text>
              </View>
            </View>
            {t.stats ? (
              <View style={{ gap: 2 }}>
                <StatLine label="Active jobs" value={n(b.active_jobs)} testID={`${id}-active-jobs`} />
                <StatLine label="MTD revenue" value={money(b.mtd_revenue || 0)} testID={`${id}-mtd`} />
              </View>
            ) : null}
          </Pressable>
        );
      }) : [0, 1, 2, 3].map((i) => (
        <View key={i} style={[s.skeleton, { width }]} testID={`service-category-skeleton-${i}`} />
      ))}
    </View>
  );
}

const s = StyleSheet.create({
  grid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.md, marginBottom: spacing.lg },
  tile: { borderRadius: radius.lg, borderWidth: 1, borderLeftWidth: 4, padding: spacing.md, gap: spacing.sm },
  head: { flexDirection: "row", alignItems: "flex-start", gap: spacing.sm },
  icon: { width: 34, height: 34, borderRadius: radius.md, alignItems: "center", justifyContent: "center" },
  title: { fontFamily: font.bold, fontSize: 11, letterSpacing: 0.5, textTransform: "uppercase", color: "#1F2937", opacity: 0.75 },
  count: { fontFamily: font.bold, fontSize: fontSize.xl, color: "#111827", marginTop: 2 },
  caption: { fontFamily: font.regular, fontSize: 11, color: "#111827", opacity: 0.6 },
  stat: { flexDirection: "row", flexWrap: "wrap", alignItems: "baseline", justifyContent: "space-between", columnGap: spacing.xs },
  statLabel: { flexShrink: 1, fontFamily: font.semibold, fontSize: 10, letterSpacing: 0.3, textTransform: "uppercase", color: "#1F2937", opacity: 0.7 },
  statValue: { flexShrink: 1, maxWidth: "100%", fontFamily: font.medium, fontSize: fontSize.sm, color: "#111827" },
  skeleton: { height: 132, borderRadius: radius.lg, backgroundColor: "#F3F4F6", borderWidth: 1, borderColor: "#E5E7EB" },
});
