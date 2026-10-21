/**
 * TD-96-mobile-timeline · lead communication timeline.
 *
 * Web parity: `frontend/src/pages/leads/LeadDetail.jsx` "Communication Timeline"
 * card + inline `CommTimelineItem`.
 *   GET /api/leads/{id}/communications?limit=50[&cursor=<iso>|<id>]
 *   → { items, next_cursor, has_more }
 * BE merges 3 sources: lead_communications (sms/email) + sms_inbound matched to
 * the lead + leads.timeline[] status_change (first page only).
 *
 * Refresh triggers (strict web parity, D3b): mount, Refresh button, and the
 * parent bumping `refreshKey` after a compose `onSent`.
 * Out of scope: admin "View details" dialog (TD-96-mobile-comm-detail).
 * Body is cut at 400 chars with no expand toggle (web parity, D4).
 * Mounted inside the already role-gated lead screen (admin/super_admin/manager).
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { View, Text, Pressable, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { useToast } from "@/src/components/ToastProvider";

export const COMM_PAGE_SIZE = 50;
export const COMM_BODY_MAX = 400;

const TYPE_META: Record<string, { bg: string; fg: string; label: string }> = {
  sms: { bg: "#DCFCE7", fg: "#166534", label: "SMS" },
  email: { bg: "#DBEAFE", fg: "#1E3A8A", label: "Email" },
  status_change: { bg: "#F1F5F9", fg: "#475569", label: "Status change" },
};

export const truncateBody = (body: string) =>
  body.length > COMM_BODY_MAX ? body.slice(0, COMM_BODY_MAX) + "…" : body;

export function CommTimelineItem({ item }: { item: any }) {
  const type = item.type || "status_change";
  const m = TYPE_META[type] || { bg: "#F1F5F9", fg: "#475569", label: type };
  const when = item.created_at ? new Date(item.created_at).toLocaleString() : "";
  const pill = `${m.label}${item.direction === "inbound" ? " · inbound" : ""}`;
  return (
    <View style={[s.item, { borderLeftColor: m.fg + "55" }]} testID={`lead-comm-item-${type}`}>
      <View style={s.row}>
        <View style={[s.pill, { backgroundColor: m.bg }]}>
          <Text style={[s.pillText, { color: m.fg }]}>{pill}</Text>
        </View>
        {item.status ? <Text style={s.status}>{item.status}</Text> : null}
        <Text style={s.when}>{when}</Text>
      </View>
      {item.subject ? <Text style={s.subject}>{item.subject}</Text> : null}
      {item.body ? <Text style={s.body}>{truncateBody(item.body)}</Text> : null}
      {item.error ? <Text style={s.error}>Error: {item.error}</Text> : null}
    </View>
  );
}

type Props = { leadId: string; refreshKey?: unknown };

export default function LeadCommunicationTimeline({ leadId, refreshKey }: Props) {
  const { showToast } = useToast();
  const toastRef = useRef(showToast);
  toastRef.current = showToast;
  const [items, setItems] = useState<any[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const seq = useRef(0); // drop stale responses (refresh while a page is in flight)

  const load = useCallback(async (next?: string | null) => {
    const mine = ++seq.current;
    setLoading(true);
    try {
      const qs = `limit=${COMM_PAGE_SIZE}${next ? `&cursor=${encodeURIComponent(next)}` : ""}`;
      const res = await api.get(`/leads/${leadId}/communications?${qs}`);
      if (mine !== seq.current) return;
      const page = res?.items || [];
      setItems((prev) => (next ? [...prev, ...page] : page));
      setCursor(res?.next_cursor || null);
      setHasMore(!!res?.has_more);
    } catch (e: any) {
      if (mine === seq.current) toastRef.current(`Failed to load communications${e?.message ? ` — ${e.message}` : ""}`, "error");
    } finally {
      if (mine === seq.current) setLoading(false);
    }
  }, [leadId]);

  useEffect(() => { load(); }, [load, refreshKey]);

  return (
    <View style={s.card} testID="lead-communication-timeline">
      <View style={s.header}>
        <Text style={s.title}>Communication Timeline</Text>
        <Pressable onPress={() => load()} hitSlop={10} style={s.refresh} accessibilityLabel="Refresh communication timeline" testID="lead-communication-timeline-refresh">
          <Ionicons name="refresh" size={12} color={colors.muted} />
          <Text style={s.refreshText}>Refresh</Text>
        </Pressable>
      </View>
      {loading && items.length === 0 ? (
        <Text style={s.empty} testID="lead-communication-timeline-loading">Loading…</Text>
      ) : items.length === 0 ? (
        <Text style={s.empty} testID="lead-communication-timeline-empty">No communications yet.</Text>
      ) : (
        items.map((it, i) => <CommTimelineItem key={it.id || `${it.type}-${i}`} item={it} />)
      )}
      {hasMore ? (
        <Pressable onPress={() => load(cursor)} disabled={loading} accessibilityState={{ disabled: loading }} style={[s.more, loading && { opacity: 0.5 }]} testID="lead-communication-timeline-load-more">
          <Text style={s.moreText}>{loading ? "Loading…" : "Load more"}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

const s = StyleSheet.create({
  card: { backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.lg, marginBottom: spacing.md, borderWidth: 1, borderColor: colors.border },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: spacing.sm },
  title: { fontFamily: font.bold, fontSize: 10, color: colors.muted, letterSpacing: 1, textTransform: "uppercase" },
  refresh: { flexDirection: "row", alignItems: "center", gap: 4, minHeight: 32, paddingHorizontal: 4 },
  refreshText: { fontFamily: font.medium, fontSize: 12, color: colors.muted },
  empty: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  item: { borderLeftWidth: 2, paddingLeft: 12, paddingVertical: 8 },
  row: { flexDirection: "row", alignItems: "center", gap: 8 },
  pill: { paddingHorizontal: 8, paddingVertical: 2, borderRadius: 999 },
  pillText: { fontFamily: font.semibold, fontSize: 10, textTransform: "uppercase" },
  status: { fontFamily: font.regular, fontSize: 11, color: colors.muted },
  when: { fontFamily: font.regular, fontSize: 11, color: colors.muted, marginLeft: "auto" },
  subject: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurface, marginTop: 4 },
  body: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurfaceSecondary, marginTop: 4 },
  error: { fontFamily: font.regular, fontSize: 11, color: "#BE123C", marginTop: 4 },
  more: { alignSelf: "center", marginTop: spacing.md, minHeight: 36, justifyContent: "center", paddingHorizontal: 14, borderRadius: radius.sm, borderWidth: 1, borderColor: colors.border },
  moreText: { fontFamily: font.medium, fontSize: 12, color: colors.onSurface },
});
