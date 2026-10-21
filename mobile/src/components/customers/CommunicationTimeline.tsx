/**
 * CommunicationTimeline — customer communication super-timeline.
 *
 * TD-98-be-cleanup mobile migration (web `CustomerFullTimeline.jsx` parity):
 *   variant="admin"  → GET /api/customers/{customer_id}/timeline
 *   variant="portal" → GET /api/customers/me/timeline
 * Page-mode "Load more" (portal endpoint has no cursor). Six kinds
 * (email, sms, invoice, estimate, call, note) with role-gated filter chips.
 * Rows with a `url` open the matching mobile screen. Any 403 (techs; the
 * `insufficient_role_for_full_timeline` case) renders the empty state
 * like web — this also removes the red error box techs saw on the
 * legacy endpoint.
 *
 * Mounts: customer profile (admin) + portal Messages (portal).
 */
import React, { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, Pressable, ActivityIndicator, ScrollView } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import {
  timelineChips, timelinePath, normaliseTimelineItem, mobileRouteFor, isTimelineForbidden,
  TIMELINE_BASE_CHIPS, TIMELINE_PAGE_SIZE, type TimelineItem, type TimelineScope,
} from "@/src/lib/customerTimeline";

function relTime(iso?: string) {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const diff = Date.now() - then;
  if (diff < 60_000) return "just now";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`;
  if (diff < 604_800_000) return `${Math.floor(diff / 86_400_000)}d ago`;
  return new Date(iso).toLocaleDateString();
}

const KIND_META: Record<string, { label: string; icon: any; bg: string; fg: string; dot: string }> = {
  sms:      { label: "Message",  icon: "chatbubble",    bg: "#FEE2E2", fg: "#991B1B", dot: "#DC2626" },
  email:    { label: "Email",    icon: "mail",          bg: "#DCFCE7", fg: "#166534", dot: "#16A34A" },
  invoice:  { label: "Invoice",  icon: "receipt",       bg: "#DBEAFE", fg: "#1E3A8A", dot: "#2563EB" },
  estimate: { label: "Estimate", icon: "document-text", bg: "#FEF3C7", fg: "#92400E", dot: "#D97706" },
  call:     { label: "Call",     icon: "call",          bg: "#EDE9FE", fg: "#5B21B6", dot: "#7C3AED" },
  note:     { label: "Note",     icon: "create",        bg: "#F1F5F9", fg: "#334155", dot: "#64748B" },
  payment:  { label: "Payment",  icon: "card",          bg: "#D1FAE5", fg: "#065F46", dot: "#059669" }, // web CreditCard
};
const metaFor = (k: string) => KIND_META[k] || { label: k || "Event", icon: "ellipse", bg: "#F1F5F9", fg: "#475569", dot: "#94A3B8" };
const chipLabel = (k: string) => (k === "all" ? "All" : `${metaFor(k).label}s`);

function TypePill({ kind }: { kind: string }) {
  const m = metaFor(kind);
  return (
    <View style={[tp.pill, { backgroundColor: m.bg }]} testID={`timeline-pill-${kind}`}>
      <Ionicons name={m.icon} size={10} color={m.fg} />
      <Text style={[tp.text, { color: m.fg }]}>{m.label}</Text>
    </View>
  );
}
const tp = StyleSheet.create({
  pill: { flexDirection: "row", alignItems: "center", gap: 3, borderRadius: 999, paddingHorizontal: 8, paddingVertical: 3 },
  text: { fontFamily: font.bold, fontSize: 10, textTransform: "uppercase", letterSpacing: 0.5 },
});

const STATUS_COLORS: Record<string, { bg: string; fg: string }> = {
  delivered: { bg: "#DCFCE7", fg: "#166534" }, paid: { bg: "#DCFCE7", fg: "#166534" }, accepted: { bg: "#DCFCE7", fg: "#166534" },
  sent: { bg: "#DBEAFE", fg: "#1E3A8A" },
  queued: { bg: "#FEF3C7", fg: "#92400E" }, reserved: { bg: "#FEF3C7", fg: "#92400E" }, draft: { bg: "#FEF3C7", fg: "#92400E" },
  failed: { bg: "#FEE2E2", fg: "#991B1B" }, declined: { bg: "#FEE2E2", fg: "#991B1B" },
};
function StatusPill({ status, testID: tid }: { status: string; testID: string }) {
  const c = STATUS_COLORS[status] || { bg: "#F1F5F9", fg: "#475569" };
  return (
    <View style={[sp.pill, { backgroundColor: c.bg }]} testID={tid}>
      <Text style={[sp.text, { color: c.fg }]}>{status.replace(/_/g, " ")}</Text>
    </View>
  );
}
const sp = StyleSheet.create({
  pill: { borderRadius: 999, paddingHorizontal: 8, paddingVertical: 2 },
  text: { fontFamily: font.semibold, fontSize: 10, textTransform: "uppercase", letterSpacing: 0.5 },
});

function Row({ item, isAdmin, route, onOpen }: { item: TimelineItem; isAdmin: boolean; route: string | null; onOpen: () => void }) {
  const [expanded, setExpanded] = useState(false);
  const body = item.body;
  const clamp = body.length > 220;
  const shown = expanded || !clamp ? body : `${body.slice(0, 220)}…`;
  const isMsg = item.kind === "sms" || item.kind === "email";
  // Delivery status is admin-only for messages (server strips it on portal); doc status is not sensitive.
  const showStatus = !!item.status && (isAdmin || !isMsg);
  const headline = item.kind === "email" && item.subject ? `Subject: ${item.subject}` : !isMsg ? item.summary : "";
  const money = item.total > 0 ? `$${item.total.toFixed(2)}` : ""; // web DefaultRow money chip
  return (
    <View style={r.row} testID={`timeline-row-${item.id}`}>
      <View style={[r.marker, { backgroundColor: metaFor(item.kind).dot }]} />
      <View style={r.content}>
        <View style={r.chipRow}>
          <TypePill kind={item.kind} />
          <View style={r.timeRow}>
            <Ionicons name="time-outline" size={10} color={colors.muted} />
            <Text style={r.time} testID={`timeline-time-${item.id}`}>{relTime(item.occurredAt)}</Text>
          </View>
          {money ? <Text style={r.money} testID={`timeline-money-${item.id}`}>{money}</Text> : null}
          {item.actor ? (
            <Text style={r.actor}>by <Text style={r.actorBold} testID={`timeline-actor-${item.id}`}>{item.actor}</Text></Text>
          ) : null}
          {showStatus ? <StatusPill status={item.status} testID={`timeline-status-${item.id}`} /> : null}
        </View>
        {headline ? (
          route ? (
            <Pressable onPress={onOpen} hitSlop={8} style={r.openRow} testID={`timeline-open-${item.id}`}>
              <Text style={[r.subject, r.link]} testID={`timeline-summary-${item.id}`}>{headline}</Text>
              <Ionicons name="chevron-forward" size={14} color={colors.brand} />
            </Pressable>
          ) : (
            <Text style={r.subject} testID={item.kind === "email" ? `timeline-subject-${item.id}` : `timeline-summary-${item.id}`}>{headline}</Text>
          )
        ) : null}
        {body ? (
          <View>
            <Text style={r.body} testID={`timeline-body-${item.id}`}>{shown}</Text>
            {clamp ? (
              <Pressable onPress={() => setExpanded((v) => !v)} testID={`timeline-expand-${item.id}`}>
                <Text style={r.toggle}>{expanded ? "show less" : "show more"}</Text>
              </Pressable>
            ) : null}
          </View>
        ) : null}
        {isAdmin && item.deliveryError ? (
          <View style={r.errorRow} testID={`timeline-error-${item.id}`}>
            <Ionicons name="alert-circle" size={12} color="#991B1B" />
            <Text style={r.errorText}>{item.deliveryError}</Text>
          </View>
        ) : null}
        {item.recipient ? <Text style={r.recipient} testID={`timeline-recipient-${item.id}`}>to {item.recipient}</Text> : null}
      </View>
    </View>
  );
}
const r = StyleSheet.create({
  row: { flexDirection: "row", paddingBottom: spacing.md },
  marker: { width: 14, height: 14, borderRadius: 7, marginTop: 4, marginRight: spacing.sm, borderWidth: 2, borderColor: colors.surface },
  content: { flex: 1, gap: 4 },
  chipRow: { flexDirection: "row", alignItems: "center", flexWrap: "wrap", gap: spacing.sm },
  timeRow: { flexDirection: "row", alignItems: "center", gap: 3 },
  time: { fontFamily: font.regular, fontSize: 11, color: colors.muted },
  money: { fontFamily: font.semibold, fontSize: 11, color: colors.onSurface },
  actor: { fontFamily: font.regular, fontSize: 11, color: colors.muted },
  actorBold: { fontFamily: font.bold, color: colors.onSurface },
  subject: { fontFamily: font.bold, fontSize: fontSize.sm, color: colors.onSurface },
  openRow: { flexDirection: "row", alignItems: "center", gap: 2, minHeight: 32 },
  link: { color: colors.brand },
  body: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurface, lineHeight: 18 },
  toggle: { fontFamily: font.semibold, fontSize: 12, color: colors.brand, textDecorationLine: "underline", marginTop: 2 },
  errorRow: { flexDirection: "row", alignItems: "center", gap: 4 },
  errorText: { fontFamily: font.regular, fontSize: 12, color: "#991B1B", flex: 1 },
  recipient: { fontFamily: font.regular, fontSize: 11, color: colors.muted },
});

type Props = { customerId: string; variant?: TimelineScope; limit?: number };

export default function CommunicationTimeline({ customerId, variant = "admin", limit = TIMELINE_PAGE_SIZE }: Props) {
  const router = useRouter();
  const { user } = useAuth() || ({} as any);
  const isAdmin = variant === "admin";
  const chips = isAdmin ? timelineChips((user as any)?.role) : TIMELINE_BASE_CHIPS;
  const [kind, setKind] = useState("all");
  const [items, setItems] = useState<TimelineItem[]>([]);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [err, setErr] = useState("");

  const fetchPage = useCallback(async (p: number) => {
    if (isAdmin && !customerId) return;
    if (p === 1) setLoading(true); else setLoadingMore(true);
    try {
      const res: any = await api.get(timelinePath(variant, customerId, p, kind, limit));
      const next = (res?.items || []).map(normaliseTimelineItem);
      setItems((prev) => (p === 1 ? next : [...prev, ...next]));
      setPage(p);
      setTotalPages(Number(res?.total_pages || 0));
      setErr("");
    } catch (e: any) {
      if (isTimelineForbidden(e)) { setItems([]); setTotalPages(0); setErr(""); }
      else setErr(e?.message || "Couldn't load timeline");
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  }, [customerId, variant, kind, limit, isAdmin]);

  useEffect(() => { fetchPage(1); }, [fetchPage]);

  const chipBar = chips.length > 1 ? (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.chips} testID="communication-timeline-chips">
      {chips.map((k) => (
        <Pressable
          key={k} onPress={() => setKind(k)} style={[s.chip, kind === k && s.chipOn]}
          accessibilityState={{ selected: kind === k }} testID={`communication-timeline-chip-${k}`}
        >
          <Text style={[s.chipText, kind === k && s.chipTextOn]}>{chipLabel(k)}</Text>
        </Pressable>
      ))}
    </ScrollView>
  ) : null;

  let body: React.ReactNode;
  if (loading) {
    body = (
      <View style={s.loadWrap} testID="communication-timeline-loading">
        <ActivityIndicator size="small" color={colors.brand} />
        <Text style={s.loadText}>Loading timeline…</Text>
      </View>
    );
  } else if (err) {
    body = <View style={s.errBox} testID="communication-timeline-error"><Text style={s.errText}>{err}</Text></View>;
  } else if (!items.length) {
    body = (
      <View style={s.emptyBox} testID="communication-timeline-empty">
        <Ionicons name="chatbubbles-outline" size={24} color={colors.muted} />
        <Text style={s.emptyText}>No communications yet.</Text>
      </View>
    );
  } else {
    body = (
      <>
        <View style={s.list} testID="communication-timeline-list">
          {items.map((it, i) => {
            const route = mobileRouteFor(it.url, variant);
            return <Row key={`${it.id}-${i}`} item={it} isAdmin={isAdmin} route={route} onOpen={() => route && router.push(route as any)} />;
          })}
        </View>
        {page < totalPages ? (
          <Pressable
            style={[s.loadMore, loadingMore && { opacity: 0.6 }]} onPress={() => fetchPage(page + 1)}
            disabled={loadingMore} testID="communication-timeline-load-more"
          >
            {loadingMore ? <ActivityIndicator size="small" color={colors.onSurface} /> : null}
            <Text style={s.loadMoreText}>{loadingMore ? "Loading…" : "Load more"}</Text>
          </Pressable>
        ) : null}
      </>
    );
  }

  return (
    <View testID={`communication-timeline-${variant}`}>
      {chipBar}
      {body}
    </View>
  );
}

const s = StyleSheet.create({
  chips: { gap: spacing.sm, paddingBottom: spacing.sm },
  chip: { minHeight: 32, paddingHorizontal: 12, justifyContent: "center", borderRadius: 999, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
  chipOn: { backgroundColor: colors.brand, borderColor: colors.brand },
  chipText: { fontFamily: font.semibold, fontSize: 12, color: colors.onSurfaceSecondary },
  chipTextOn: { color: "#fff" },
  loadWrap: { flexDirection: "row", alignItems: "center", gap: spacing.sm, padding: spacing.md },
  loadText: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  errBox: { borderRadius: radius.md, paddingHorizontal: 12, paddingVertical: 8, backgroundColor: "#FEE2E2" },
  errText: { fontFamily: font.medium, fontSize: fontSize.sm, color: "#991B1B" },
  emptyBox: { borderRadius: radius.lg, padding: spacing.lg, alignItems: "center", gap: spacing.sm, backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border, borderStyle: "dashed" },
  emptyText: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, textAlign: "center" },
  list: { borderLeftWidth: 2, borderLeftColor: "#D1D5DB", borderStyle: "dashed", marginLeft: 6, paddingLeft: 0 },
  loadMore: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: spacing.sm, minHeight: 44, paddingHorizontal: 16, borderRadius: radius.md, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, marginTop: spacing.sm },
  loadMoreText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface },
});
