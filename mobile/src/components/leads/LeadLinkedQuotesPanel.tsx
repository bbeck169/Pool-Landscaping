/**
 * TD-96-mobile · Linked Quotes mini-list (admin-only; caller gates).
 * Port of web `LeadDetail.jsx` `lead-linked-quotes-panel`.
 *
 * Data: GET /api/leads/{id}/quotes?limit=10 → {items, total, limit}
 * Rows: title · $total · "reparented" marker · status pill → /quote/<id>.
 *
 * Deliberate deviations from web (operator D2):
 * - ALWAYS fetched for admins. Web gates the fetch on `quotes_count > 0`,
 *   but `quotes_count` ignores reparented (post-conversion) quotes, so the
 *   panel vanishes after close-won. TODO(TD-96-g2): once the backend
 *   count includes reparented quotes, gate on it again to skip the GET.
 * - No "View all" link: web's `/quotes?lead=<id>` is a dead filter
 *   (TD-96-g1). A non-link "+N more" hint is shown instead.
 *   → Resolved by TD-96-g1-mobile: "View all {total} →" (web label/testid)
 *   opens the Quotes tab with `lead` + `view:"all"` (web omits view, so
 *   its link lands on "open" and can be empty — TD-96-g1-web-view).
 *
 * Fail-open: fetch error or empty list → renders nothing (web parity).
 */
import React, { useEffect, useState } from "react";
import { View, Text, Pressable, StyleSheet } from "react-native";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize, money, statusMeta } from "@/src/theme";

export const LINKED_QUOTES_LIMIT = 10;

function pill(status: string) {
  const s = String(status || "").toLowerCase();
  const label = s ? (s.charAt(0).toUpperCase() + s.slice(1)).replace(/_/g, " ") : "—";
  return statusMeta[s] || { label, bg: colors.surfaceTertiary, fg: colors.onSurfaceSecondary };
}

type Props = { leadId: string; refreshKey?: unknown };

export default function LeadLinkedQuotesPanel({ leadId, refreshKey }: Props) {
  const router = useRouter();
  const [data, setData] = useState<{ items: any[]; total: number } | null>(null);

  useEffect(() => {
    if (!leadId) return;
    let alive = true;
    api.get(`/leads/${encodeURIComponent(leadId)}/quotes?limit=${LINKED_QUOTES_LIMIT}`)
      .then((res: any) => {
        if (!alive) return;
        const items = Array.isArray(res?.items) ? res.items : [];
        setData({ items, total: Number(res?.total ?? items.length) });
      })
      .catch(() => { if (alive) setData(null); });
    return () => { alive = false; };
  }, [leadId, refreshKey]);

  if (!data || data.items.length === 0) return null;
  const more = data.total - data.items.length;

  return (
    <View style={s.card} testID="lead-linked-quotes-panel">
      <View style={s.header}>
        <Text style={s.title}>{`Linked Quote${data.total === 1 ? "" : "s"}`}</Text>
        <Text style={s.count} testID="lead-linked-quotes-count">{String(data.total)}</Text>
      </View>
      {data.items.map((q) => {
        const p = pill(q.status);
        return (
          <Pressable
            key={q.id}
            onPress={() => router.push(`/quote/${q.id}` as any)}
            style={({ pressed }) => [s.row, pressed && { opacity: 0.7 }]}
            testID={`lead-linked-quote-row-${q.id}`}
          >
            <View style={{ flex: 1, minWidth: 0 }}>
              <Text style={s.rowTitle} numberOfLines={1}>{q.title || "(untitled)"}</Text>
              <Text style={s.rowMeta} testID={`lead-linked-quote-meta-${q.id}`}>
                {`${money(Number(q.total || 0))}${q.reparented ? " · reparented" : ""}`}
              </Text>
            </View>
            <View style={[s.chip, { backgroundColor: p.bg }]} testID={`lead-linked-quote-status-${q.id}`}>
              <Text style={[s.chipText, { color: p.fg }]}>{p.label}</Text>
            </View>
            <Ionicons name="chevron-forward" size={16} color={colors.muted} />
          </Pressable>
        );
      })}
      {more > 0 ? (
        <Pressable
          onPress={() => router.push({ pathname: "/(app)/quotes", params: { lead: leadId, view: "all" } } as any)}
          style={({ pressed }) => [s.viewAll, pressed && { opacity: 0.7 }]}
          testID="lead-linked-quotes-view-all" accessibilityRole="button"
        >
          <Text style={s.viewAllText}>{`View all ${data.total} →`}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

const s = StyleSheet.create({
  card: { backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.lg, marginBottom: spacing.md, borderWidth: 1, borderColor: colors.border },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: spacing.sm },
  title: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  count: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.sm, minHeight: 56, paddingVertical: spacing.sm, borderTopWidth: 1, borderTopColor: colors.border },
  rowTitle: { fontFamily: font.medium, fontSize: fontSize.base, color: colors.onSurface },
  rowMeta: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
  chip: { paddingHorizontal: spacing.sm, paddingVertical: 2, borderRadius: radius.pill },
  chipText: { fontFamily: font.semibold, fontSize: 11 },
  viewAll: { minHeight: 44, alignItems: "center", justifyContent: "center", marginTop: spacing.xs, borderTopWidth: 1, borderTopColor: colors.border },
  viewAllText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.brand },
});
