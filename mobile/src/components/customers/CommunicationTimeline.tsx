/**
 * CommunicationTimeline — Phase J2 / I7 parity.
 *
 * Vertical timeline of customer SMS + email events.
 * GET /api/customers/{customer_id}/communication-timeline
 * Cursor pagination via `before` parameter.
 *
 * Mounts:
 * - Admin: bottom of customer profile (variant="admin")
 * - Portal: bottom of portal Messages screen (variant="portal")
 *
 * Portal variant hides delivery_status, delivery_error, actor_user_id
 * (server strips those anyway).
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, ActivityIndicator,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";

/* ── Relative time ──────────────────────────────────────────── */
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

/* ── Type pill ──────────────────────────────────────────────── */
function TypePill({ kind }: { kind: string }) {
  const isSms = kind === "sms";
  return (
    <View style={[tp.pill, { backgroundColor: isSms ? "#FEE2E2" : "#DCFCE7" }]} testID={`timeline-pill-${kind}`}>
      <Ionicons name={isSms ? "chatbubble" : "mail"} size={10} color={isSms ? "#991B1B" : "#166534"} />
      <Text style={[tp.text, { color: isSms ? "#991B1B" : "#166534" }]}>
        {isSms ? "Message" : "Email"}
      </Text>
    </View>
  );
}
const tp = StyleSheet.create({
  pill: { flexDirection: "row", alignItems: "center", gap: 3, borderRadius: 999, paddingHorizontal: 8, paddingVertical: 3 },
  text: { fontFamily: font.bold, fontSize: 10, textTransform: "uppercase", letterSpacing: 0.5 },
});

/* ── Delivery status pill ───────────────────────────────────── */
function StatusPill({ status, testID: tid }: { status: string; testID: string }) {
  const map: Record<string, { bg: string; fg: string }> = {
    delivered: { bg: "#DCFCE7", fg: "#166534" },
    sent:      { bg: "#DBEAFE", fg: "#1E3A8A" },
    queued:    { bg: "#FEF3C7", fg: "#92400E" },
    reserved:  { bg: "#FEF3C7", fg: "#92400E" },
    failed:    { bg: "#FEE2E2", fg: "#991B1B" },
  };
  const s = map[status] || { bg: "#F1F5F9", fg: "#475569" };
  return (
    <View style={[sp.pill, { backgroundColor: s.bg }]} testID={tid}>
      <Text style={[sp.text, { color: s.fg }]}>{status}</Text>
    </View>
  );
}
const sp = StyleSheet.create({
  pill: { borderRadius: 999, paddingHorizontal: 8, paddingVertical: 2 },
  text: { fontFamily: font.semibold, fontSize: 10, textTransform: "uppercase", letterSpacing: 0.5 },
});

/* ── Timeline row ───────────────────────────────────────────── */
function Row({ item, isAdmin }: { item: any; isAdmin: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const body: string = item.body_preview || "";
  const clamp = body.length > 220;
  const shown = expanded || !clamp ? body : `${body.slice(0, 220)}…`;
  const isSms = item.type === "sms";

  return (
    <View style={r.row} testID={`timeline-row-${item.id}`}>
      {/* Marker */}
      <View style={[r.marker, { backgroundColor: isSms ? "#DC2626" : "#16A34A" }]} />

      {/* Content */}
      <View style={r.content}>
        <View style={r.chipRow}>
          <TypePill kind={item.type} />
          <View style={r.timeRow}>
            <Ionicons name="time-outline" size={10} color={colors.muted} />
            <Text style={r.time} testID={`timeline-time-${item.id}`}>{relTime(item.occurred_at)}</Text>
          </View>
          {item.actor_label ? (
            <Text style={r.actor}>
              by <Text style={r.actorBold} testID={`timeline-actor-${item.id}`}>{item.actor_label}</Text>
            </Text>
          ) : null}
          {isAdmin && item.delivery_status ? (
            <StatusPill status={item.delivery_status} testID={`timeline-status-${item.id}`} />
          ) : null}
        </View>

        {item.type === "email" && item.subject ? (
          <Text style={r.subject} testID={`timeline-subject-${item.id}`}>Subject: {item.subject}</Text>
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

        {isAdmin && item.delivery_error ? (
          <View style={r.errorRow} testID={`timeline-error-${item.id}`}>
            <Ionicons name="alert-triangle" size={12} color="#991B1B" />
            <Text style={r.errorText}>{item.delivery_error}</Text>
          </View>
        ) : null}

        {item.recipient ? (
          <Text style={r.recipient} testID={`timeline-recipient-${item.id}`}>to {item.recipient}</Text>
        ) : null}
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
  actor: { fontFamily: font.regular, fontSize: 11, color: colors.muted },
  actorBold: { fontFamily: font.bold, color: colors.onSurface },
  subject: { fontFamily: font.bold, fontSize: fontSize.sm, color: colors.onSurface },
  body: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurface, lineHeight: 18 },
  toggle: { fontFamily: font.semibold, fontSize: 12, color: colors.brand, textDecorationLine: "underline", marginTop: 2 },
  errorRow: { flexDirection: "row", alignItems: "center", gap: 4 },
  errorText: { fontFamily: font.regular, fontSize: 12, color: "#991B1B", flex: 1 },
  recipient: { fontFamily: font.regular, fontSize: 11, color: colors.muted },
});

/* ── Main ───────────────────────────────────────────────────── */
export default function CommunicationTimeline({
  customerId,
  variant = "admin",
  limit = 50,
}: {
  customerId: string;
  variant?: "admin" | "portal";
  limit?: number;
}) {
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [items, setItems] = useState<any[]>([]);
  const [nextBefore, setNextBefore] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const isAdmin = variant === "admin";

  const fetchPage = useCallback(async (before: string | null = null) => {
    if (!customerId) return;
    if (!before) setLoading(true);
    else setLoadingMore(true);
    try {
      const qs = new URLSearchParams({ limit: String(limit) });
      if (before) qs.set("before", before);
      const res: any = await api.get(`/customers/${customerId}/communication-timeline?${qs}`);
      const next = res?.items || [];
      setItems((prev) => before ? [...prev, ...next] : next);
      setHasMore(Boolean(res?.has_more));
      setNextBefore(res?.next_before || null);
      setErr("");
    } catch (e: any) {
      setErr(e?.message || "Couldn't load timeline");
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  }, [customerId, limit]);

  useEffect(() => { fetchPage(null); }, [fetchPage]);

  if (loading) {
    return (
      <View style={s.loadWrap} testID="communication-timeline-loading">
        <ActivityIndicator size="small" color={colors.brand} />
        <Text style={s.loadText}>Loading timeline…</Text>
      </View>
    );
  }

  if (err) {
    return (
      <View style={s.errBox} testID="communication-timeline-error">
        <Text style={s.errText}>{err}</Text>
      </View>
    );
  }

  if (!items.length) {
    return (
      <View style={s.emptyBox} testID="communication-timeline-empty">
        <Ionicons name="chatbubbles-outline" size={24} color={colors.muted} />
        <Text style={s.emptyText}>No email or SMS communications yet.</Text>
      </View>
    );
  }

  return (
    <View testID={`communication-timeline-${variant}`}>
      <View style={s.list} testID="communication-timeline-list">
        {items.map((it) => (
          <Row key={it.id} item={it} isAdmin={isAdmin} />
        ))}
      </View>
      {hasMore ? (
        <Pressable
          style={[s.loadMore, loadingMore && { opacity: 0.6 }]}
          onPress={() => fetchPage(nextBefore)}
          disabled={loadingMore}
          testID="communication-timeline-load-more"
        >
          {loadingMore ? (
            <ActivityIndicator size="small" color={colors.onSurface} />
          ) : null}
          <Text style={s.loadMoreText}>{loadingMore ? "Loading…" : "Load more"}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

const s = StyleSheet.create({
  loadWrap: { flexDirection: "row", alignItems: "center", gap: spacing.sm, padding: spacing.md },
  loadText: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  errBox: { borderRadius: radius.md, paddingHorizontal: 12, paddingVertical: 8, backgroundColor: "#FEE2E2" },
  errText: { fontFamily: font.medium, fontSize: fontSize.sm, color: "#991B1B" },
  emptyBox: { borderRadius: radius.lg, padding: spacing.lg, alignItems: "center", gap: spacing.sm, backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border, borderStyle: "dashed" },
  emptyText: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, textAlign: "center" },
  list: {
    borderLeftWidth: 2,
    borderLeftColor: "#D1D5DB",
    borderStyle: "dashed",
    marginLeft: 6,
    paddingLeft: 0,
  },
  loadMore: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: spacing.sm, paddingVertical: 8, paddingHorizontal: 16, borderRadius: radius.md, backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border, alignSelf: "flex-start", marginTop: spacing.sm },
  loadMoreText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface },
});
