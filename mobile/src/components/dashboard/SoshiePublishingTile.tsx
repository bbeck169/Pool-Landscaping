/**
 * Phase 39B · mobile port of web `admin/SoshiePublishingTile.jsx`.
 * GET /soshie/publishing/today-summary on mount + every 60 s. Five
 * counts, "Attention" badge when flagged/blocked/failed > 0, next 3
 * posts, refresh + "Moderation queue" (→ `/(app)/soshie-moderation`).
 * Parent gate: super_admin / admin / owner.
 */
import React, { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";

const PLATFORM_ICON: Record<string, any> = {
  facebook: "logo-facebook", instagram: "logo-instagram", tiktok: "videocam-outline",
  gbp: "globe-outline", wordpress: "globe-outline", reddit: "chatbubble-outline",
};
const fmtTime = (iso?: string) => {
  if (!iso) return "—";
  const d = new Date(iso);
  return isNaN(d.getTime()) ? "—" : d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
};
const TONE = { danger: colors.error, warn: "#B45309", ok: colors.success } as const;

function CountCell({ label, value, tone, testID }: { label: string; value: any; tone?: keyof typeof TONE; testID: string }) {
  return (
    <View style={s.cell} testID={testID}>
      <Text style={s.cellLabel}>{label}</Text>
      <Text style={[s.cellValue, tone && { color: TONE[tone] }]} testID={`${testID}-value`}>{value ?? 0}</Text>
    </View>
  );
}

export default function SoshiePublishingTile() {
  const router = useRouter();
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    setLoading(true); setErr("");
    try { setData((await api.get("/soshie/publishing/today-summary")) || null); }
    catch (e: any) { setErr(e?.message || "Failed to load"); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 60_000);
    return () => clearInterval(t);
  }, [load]);

  const flagged = data?.flagged || 0;
  const blocked = data?.blocked || 0;
  const failed = data?.failed || 0;
  const attention = flagged > 0 || blocked > 0 || failed > 0;
  const next = Array.isArray(data?.next_up) ? data.next_up.slice(0, 3) : [];

  return (
    <View style={s.tile} testID="soshie-publishing-tile">
      <View style={s.head}>
        <View style={s.titleRow}>
          <Ionicons name="sparkles-outline" size={16} color={colors.brand} />
          <Text style={s.title} testID="soshie-publishing-tile-title">Soshie Publishing (Today)</Text>
          {attention ? <View style={s.badge} testID="soshie-publishing-tile-attention"><Text style={s.badgeText}>Attention</Text></View> : null}
        </View>
        <Pressable onPress={load} hitSlop={10} style={s.iconBtn} testID="soshie-publishing-tile-refresh" accessibilityLabel="Refresh">
          <Ionicons name="refresh" size={14} color={colors.muted} style={{ opacity: loading ? 0.4 : 1 }} />
        </Pressable>
      </View>
      <Pressable onPress={() => router.push("/(app)/soshie-moderation" as any)} style={s.link} testID="soshie-publishing-tile-link">
        <Text style={s.linkText}>Moderation queue</Text>
        <Ionicons name="arrow-forward" size={12} color={colors.brand} />
      </Pressable>
      {err ? <View style={s.errBox} testID="soshie-publishing-tile-error"><Text style={s.errText}>{err}</Text></View> : null}
      <View style={s.grid} testID="soshie-publishing-tile-counts">
        <CountCell label="Scheduled" value={data?.scheduled} testID="soshie-publishing-tile-scheduled" />
        <CountCell label="Published" value={data?.published} tone="ok" testID="soshie-publishing-tile-published" />
        <CountCell label="Flagged" value={flagged} tone={flagged ? "warn" : undefined} testID="soshie-publishing-tile-flagged" />
        <CountCell label="Blocked" value={blocked} tone={blocked ? "danger" : undefined} testID="soshie-publishing-tile-blocked" />
        <CountCell label="Failed" value={failed} tone={failed ? "danger" : undefined} testID="soshie-publishing-tile-failed" />
      </View>
      {next.length ? (
        <View style={{ marginTop: spacing.md }} testID="soshie-publishing-tile-next">
          <Text style={s.cellLabel}>Next up</Text>
          {next.map((n: any) => (
            <View key={n.post_id} style={s.nextRow} testID={`soshie-publishing-tile-next-${n.post_id}`}>
              <Ionicons name={PLATFORM_ICON[String(n.platform || "").toLowerCase()] || "sparkles-outline"} size={12} color={colors.muted} />
              <Text style={s.nextTime}>{fmtTime(n.scheduled_at)}</Text>
              <Text style={s.nextPlat}>{n.platform || "?"}</Text>
              <Text style={s.nextPreview} numberOfLines={1}>{n.preview || "(no preview)"}</Text>
            </View>
          ))}
        </View>
      ) : null}
    </View>
  );
}

const s = StyleSheet.create({
  tile: { backgroundColor: colors.surface, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.border, padding: spacing.lg, marginBottom: spacing.lg },
  head: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  titleRow: { flexDirection: "row", alignItems: "center", gap: 6, flexShrink: 1, flexWrap: "wrap" },
  title: { fontFamily: font.bold, fontSize: fontSize.base, color: colors.onSurface },
  badge: { paddingHorizontal: 6, paddingVertical: 2, borderRadius: 6, backgroundColor: "#FEF3C7", borderWidth: 1, borderColor: "#FDE68A" },
  badgeText: { fontFamily: font.bold, fontSize: 10, color: "#78350F", textTransform: "uppercase" },
  iconBtn: { width: 36, height: 36, alignItems: "center", justifyContent: "center" },
  link: { flexDirection: "row", alignItems: "center", gap: 4, alignSelf: "flex-start", minHeight: 32, marginBottom: spacing.sm },
  linkText: { fontFamily: font.semibold, fontSize: 12, color: colors.brand },
  errBox: { padding: spacing.md, borderRadius: radius.md, backgroundColor: "#FEE2E2", borderWidth: 1, borderColor: "#FCA5A5", marginBottom: spacing.sm },
  errText: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.error },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  cell: { width: "30%", flexGrow: 1, borderRadius: radius.md, paddingHorizontal: spacing.md, paddingVertical: spacing.sm, backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border },
  cellLabel: { fontFamily: font.bold, fontSize: 10, color: colors.muted, letterSpacing: 0.8, textTransform: "uppercase" },
  cellValue: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface, marginTop: 2 },
  nextRow: { flexDirection: "row", alignItems: "center", gap: 8, marginTop: 6 },
  nextTime: { width: 64, fontFamily: font.semibold, fontSize: 12, color: colors.onSurface },
  nextPlat: { width: 60, fontFamily: font.bold, fontSize: 10, color: colors.muted, textTransform: "uppercase" },
  nextPreview: { flex: 1, fontFamily: font.regular, fontSize: 12, color: colors.onSurface },
});
