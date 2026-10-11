/**
 * Phase 39B · mobile port of web `admin/WarrantiesExpiringTile.jsx`.
 * GET /warranties/expiring-soon?days=30 → top 5. Row + "Renew" both open
 * the customer profile (mobile has no `?tab=warranties` deep link).
 * Parent gate: super_admin / admin / owner.
 */
import React, { useEffect, useState } from "react";
import { View, Text, StyleSheet, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";

export function daysBadgeColor(days: number | null | undefined) {
  if (days == null) return colors.muted;
  if (days <= 7) return "#DC2626";
  if (days <= 14) return "#CA8A04";
  return colors.brand;
}
const daysLabel = (d: any) => (d == null ? "—" : d === 0 ? "today" : `${d}d`);

export default function WarrantiesExpiringTile() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [items, setItems] = useState<any[]>([]);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.get("/warranties/expiring-soon?days=30")
      .then((r: any) => { if (!cancelled) setItems((r?.items || []).slice(0, 5)); })
      .catch((e: any) => { if (!cancelled) setErr(e?.message || "Failed to load"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  const go = (cid?: string) => { if (cid) router.push(`/customer/${cid}` as any); };

  return (
    <View style={s.tile} testID="warranties-expiring-tile">
      <View style={s.head}>
        <Ionicons name="shield-checkmark-outline" size={16} color={colors.brand} />
        <Text style={s.title}>Warranties nearing expiration</Text>
      </View>
      {loading ? (
        <Text style={s.muted} testID="warranties-expiring-loading">Loading…</Text>
      ) : err ? (
        <Text style={s.err} testID="warranties-expiring-error">{String(err)}</Text>
      ) : items.length === 0 ? (
        <Text style={s.muted} testID="warranties-expiring-empty">No warranties expiring in the next 30 days.</Text>
      ) : (
        items.map((it, i) => (
          <Pressable key={it.id || i} onPress={() => go(it.customer_id)} style={({ pressed }) => [s.row, pressed && { opacity: 0.85 }]} testID={`warranties-expiring-row-${i}`}>
            <View style={s.rowBody}>
              <Text style={s.name} numberOfLines={1}>{it.contract_name}</Text>
              <Text style={s.sub} numberOfLines={1}>{it.customer_name || "—"}{it.linked_summary ? ` · ${it.linked_summary}` : ""}</Text>
            </View>
            <View style={s.right}>
              <Text style={[s.days, { color: daysBadgeColor(it.days_remaining) }]} testID={`warranties-expiring-row-${i}-days`}>{daysLabel(it.days_remaining)}</Text>
              <Pressable onPress={() => go(it.customer_id)} style={s.renew} hitSlop={6} testID={`warranties-expiring-row-${i}-renew`}>
                <Text style={s.renewText}>Renew</Text>
              </Pressable>
            </View>
          </Pressable>
        ))
      )}
    </View>
  );
}

const s = StyleSheet.create({
  tile: { backgroundColor: colors.surface, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.border, padding: spacing.lg, marginBottom: spacing.lg },
  head: { flexDirection: "row", alignItems: "center", gap: 6, marginBottom: spacing.md },
  title: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  row: { flexDirection: "row", alignItems: "flex-start", gap: spacing.md, padding: spacing.sm, borderRadius: radius.md, backgroundColor: colors.surfaceSecondary, marginBottom: spacing.sm },
  rowBody: { flex: 1, minWidth: 0 },
  name: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurface },
  sub: { fontFamily: font.regular, fontSize: 11, color: colors.muted, marginTop: 2 },
  right: { alignItems: "flex-end", gap: 4 },
  days: { fontFamily: font.semibold, fontSize: 12 },
  renew: { paddingHorizontal: 10, minHeight: 28, justifyContent: "center", borderRadius: radius.sm, backgroundColor: colors.brandTertiary },
  renewText: { fontFamily: font.semibold, fontSize: 11, color: colors.onBrandTertiary },
  muted: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  err: { fontFamily: font.regular, fontSize: 12, color: colors.error },
});
