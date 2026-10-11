/**
 * Phase 39C · mobile port of web `admin/RecommendationsQueueWidget.jsx`.
 *
 * Read:  GET  /recommendations-queue?older_than_days=7 → {rows}
 * Write: POST /recommendations-queue/{id}/send     (200 → status sent |
 *             not_sent_missing_key | failed; 409 if no longer a draft)
 *        POST /recommendations-queue/{id}/discard  (after confirm)
 *
 * Optimistic: the row leaves the queue (and the count drops)
 * immediately; a "Syncing…" spinner shows while in flight. On error the
 * row is restored at its original index + error toast. On success a
 * silent reload (web reloads after every action).
 *
 * Gate: backend is admin / super_admin only; parent mounts accordingly.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { View, Text, StyleSheet, Pressable, ActivityIndicator } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api";
import { Sheet } from "@/src/components/ui";
import { useToast } from "@/src/components/ToastProvider";
import { showConfirm } from "@/src/components/ConfirmModal";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";

const usd = (n: any) => (typeof n === "number" ? `$${n.toFixed(2)}` : "$—");

export function sendResultMessage(r: any): { text: string; ok: boolean } {
  if (r?.status === "sent") return { text: `Sent ✓${r.resend_id ? ` (${r.resend_id})` : ""}`, ok: true };
  if (r?.status === "not_sent_missing_key") return { text: "Saved as not_sent_missing_key — no RESEND_API_KEY.", ok: true };
  if (r?.status === "failed") return { text: `Send failed: ${r.error || "unknown"}`, ok: false };
  return { text: `Status: ${r?.status ?? "unknown"}`, ok: true };
}

function RecRow({ r, onOpen, onView, onSend, onDiscard }: any) {
  return (
    <View style={s.row} testID={`recs-queue-row-${r.id}`}>
      <Pressable onPress={onOpen} style={{ flex: 1 }} testID={`recs-queue-customer-${r.id}`}>
        <Text style={s.name} numberOfLines={1}>{r.customer_name || "(no name)"}</Text>
        <Text style={s.meta} numberOfLines={1}>{r.customer_email || "no email"} · {r.age_days}d old</Text>
        <Text style={s.prices}>{usd(r.current_price)} → {usd(r.recommended_price)} <Text style={s.gap}>+{r.gap_pct}%</Text></Text>
      </Pressable>
      <View style={s.btns}>
        <Pressable onPress={onView} style={[s.iconBtn, s.viewBtn]} hitSlop={4} testID={`recs-queue-view-${r.id}`} accessibilityLabel="View">
          <Ionicons name="eye-outline" size={15} color={colors.muted} />
        </Pressable>
        <Pressable onPress={onSend} style={[s.iconBtn, { backgroundColor: colors.brand }]} hitSlop={4} testID={`recs-queue-send-${r.id}`} accessibilityLabel="Send">
          <Ionicons name="send" size={14} color="#fff" />
        </Pressable>
        <Pressable onPress={onDiscard} style={[s.iconBtn, { backgroundColor: "#FEE2E2" }]} hitSlop={4} testID={`recs-queue-discard-${r.id}`} accessibilityLabel="Discard">
          <Ionicons name="trash-outline" size={14} color="#991B1B" />
        </Pressable>
      </View>
    </View>
  );
}

export default function RecommendationsQueueWidget() {
  const router = useRouter();
  const { showToast } = useToast();
  const [expand, setExpand] = useState(true);
  const [state, setState] = useState<{ loading: boolean; err: string; rows: any[] }>({ loading: true, err: "", rows: [] });
  const [preview, setPreview] = useState<any>(null);
  const [inflight, setInflight] = useState(0);
  const inflightRef = useRef(0);

  const load = useCallback(async (silent = false) => {
    if (!silent) setState({ loading: true, err: "", rows: [] });
    try {
      const r = await api.get("/recommendations-queue?older_than_days=7");
      setState({ loading: false, err: "", rows: Array.isArray(r?.rows) ? r.rows : [] });
    } catch (e: any) {
      if (!silent) setState({ loading: false, err: e?.message || "Failed to load", rows: [] });
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  const track = (d: number) => { inflightRef.current += d; setInflight(inflightRef.current); };

  const mutate = async (row: any, kind: "send" | "discard") => {
    let index = -1;
    setPreview(null);
    setState((st) => { index = st.rows.findIndex((x) => x.id === row.id); return { ...st, rows: st.rows.filter((x) => x.id !== row.id) }; }); // optimistic
    track(1);
    try {
      const r = await api.post(`/recommendations-queue/${row.id}/${kind}`, {});
      if (kind === "send") { const m = sendResultMessage(r); showToast(m.text, m.ok ? "success" : "error"); }
      else showToast(`Discarded draft for ${row.customer_name || "customer"}.`, "success");
      if (inflightRef.current === 1) load(true);
    } catch (e: any) {
      setState((st) => { // rollback at original position
        if (st.rows.some((x) => x.id === row.id)) return st;
        const rows = [...st.rows];
        rows.splice(index < 0 ? rows.length : Math.min(index, rows.length), 0, row);
        return { ...st, rows };
      });
      showToast(e?.message || `Could not ${kind} draft.`, "error");
    } finally {
      track(-1);
    }
  };

  const discard = (row: any) => showConfirm({
    title: "Discard draft?",
    message: `Discard draft for ${row.customer_name || "this customer"}? Row is preserved for audit but hidden from this queue.`,
    confirmLabel: "Discard",
    confirmStyle: "destructive",
    onConfirm: () => mutate(row, "discard"),
  });

  const count = state.rows.length;
  const p = preview;
  return (
    <View style={s.card} testID="recs-queue-widget">
      <Pressable onPress={() => setExpand((v) => !v)} style={s.head} testID="recs-queue-toggle">
        <Ionicons name="trending-up" size={18} color={colors.brand} />
        <View style={{ flex: 1 }}>
          <Text style={s.title}>Stale price-increase drafts</Text>
          {state.loading ? <Text style={s.sub}>Loading…</Text>
            : state.err ? <Text style={[s.sub, { color: colors.error }]} testID="recs-queue-error">{state.err}</Text>
            : count === 0 ? <Text style={s.sub} testID="recs-queue-empty">No stale price-increase drafts. Nice hygiene.</Text>
            : <Text style={s.sub} testID="recs-queue-summary">{count} draft{count === 1 ? "" : "s"} older than 7 days · tap to review</Text>}
        </View>
        {inflight > 0 ? <View style={s.sync} testID="recs-queue-syncing"><ActivityIndicator size="small" color={colors.brand} /><Text style={s.syncText}>Syncing…</Text></View> : null}
        <Ionicons name={expand ? "chevron-down" : "chevron-forward"} size={16} color={colors.muted} />
      </Pressable>

      {expand && count > 0 ? (
        <View style={s.table} testID="recs-queue-table">
          {state.rows.map((r) => (
            <RecRow key={r.id} r={r} onOpen={() => r.customer_id && router.push(`/customer/${r.customer_id}` as any)}
              onView={() => setPreview(r)} onSend={() => mutate(r, "send")} onDiscard={() => discard(r)} />
          ))}
          <Pressable onPress={() => router.push("/cfo/price-increase" as any)} style={s.footer} testID="recs-queue-manage-link">
            <Text style={s.footerText}>Drafts older than 7 days · discarded rows are kept for audit. </Text>
            <Text style={s.link}>Manage all drafts →</Text>
          </Pressable>
        </View>
      ) : null}

      <Sheet visible={!!p} onClose={() => setPreview(null)} title={p?.customer_name || "(no name)"} testID="recs-queue-preview">
        {p ? (
          <View>
            <Text style={s.sub}>{p.customer_email || "no email"} · draft aged {p.age_days} days</Text>
            <View style={s.stats}>
              <View style={s.stat}><Text style={s.statLabel}>Current</Text><Text style={s.statValue}>{usd(p.current_price)}</Text></View>
              <View style={s.stat}><Text style={s.statLabel}>Recommended</Text><Text style={s.statValue}>{usd(p.recommended_price)}</Text></View>
              <View style={s.stat}><Text style={s.statLabel}>Gap</Text><Text style={[s.statValue, { color: "#166534" }]}>+{p.gap_pct}%</Text></View>
            </View>
            <Text style={s.statLabel}>Subject</Text>
            <Text style={s.body}>{p.subject}</Text>
            {p.effective_date ? <><Text style={s.statLabel}>Effective date</Text><Text style={s.body}>{p.effective_date}</Text></> : null}
            {p.reason ? <><Text style={s.statLabel}>Reason</Text><Text style={s.body}>{p.reason}</Text></> : null}
            <View style={s.actions}>
              <Pressable onPress={() => setPreview(null)} style={s.cancel} testID="recs-queue-preview-cancel"><Text style={s.cancelText}>Close</Text></Pressable>
              <Pressable onPress={() => mutate(p, "send")} style={s.sendBtn} testID="recs-queue-preview-send"><Ionicons name="send" size={13} color="#fff" /><Text style={s.sendText}>Send Now</Text></Pressable>
              <Pressable onPress={() => discard(p)} style={s.discardBtn} testID="recs-queue-preview-discard"><Ionicons name="trash-outline" size={13} color="#991B1B" /><Text style={s.discardText}>Discard</Text></Pressable>
            </View>
          </View>
        ) : null}
      </Sheet>
    </View>
  );
}

const s = StyleSheet.create({
  card: { backgroundColor: colors.surface, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.border, padding: spacing.lg, marginTop: spacing.lg },
  head: { flexDirection: "row", alignItems: "center", gap: spacing.sm, minHeight: 44 },
  title: { fontFamily: font.bold, fontSize: fontSize.base, color: colors.onSurface },
  sub: { fontFamily: font.regular, fontSize: 12, color: colors.muted, marginTop: 2 },
  sync: { flexDirection: "row", alignItems: "center", gap: 4 },
  syncText: { fontFamily: font.medium, fontSize: 11, color: colors.brand },
  table: { marginTop: spacing.md, borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, overflow: "hidden" },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.sm, paddingHorizontal: spacing.md, paddingVertical: spacing.sm, borderBottomWidth: 1, borderBottomColor: colors.border },
  name: { fontFamily: font.bold, fontSize: fontSize.sm, color: colors.onSurface },
  meta: { fontFamily: font.regular, fontSize: 10, color: colors.muted, marginTop: 1 },
  prices: { fontFamily: font.medium, fontSize: 12, color: colors.onSurface, marginTop: 2 },
  gap: { fontFamily: font.bold, color: "#166534" },
  btns: { flexDirection: "row", gap: 6 },
  iconBtn: { width: 36, height: 36, borderRadius: radius.sm, alignItems: "center", justifyContent: "center" },
  viewBtn: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  footer: { flexDirection: "row", flexWrap: "wrap", padding: spacing.md, backgroundColor: colors.surfaceSecondary },
  footerText: { fontFamily: font.regular, fontStyle: "italic", fontSize: 10, color: colors.muted },
  link: { fontFamily: font.semibold, fontSize: 10, color: colors.brand, textDecorationLine: "underline" },
  stats: { flexDirection: "row", gap: spacing.md, marginVertical: spacing.md },
  stat: { flex: 1 },
  statLabel: { fontFamily: font.regular, fontSize: 11, color: colors.muted, marginTop: spacing.sm },
  statValue: { fontFamily: font.bold, fontSize: fontSize.base, color: colors.onSurface },
  body: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurface, marginTop: 2 },
  actions: { flexDirection: "row", justifyContent: "flex-end", flexWrap: "wrap", gap: spacing.sm, marginTop: spacing.lg },
  cancel: { minHeight: 44, paddingHorizontal: spacing.lg, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, alignItems: "center", justifyContent: "center" },
  cancelText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface },
  sendBtn: { minHeight: 44, flexDirection: "row", gap: 6, paddingHorizontal: spacing.lg, borderRadius: radius.md, backgroundColor: colors.brand, alignItems: "center", justifyContent: "center" },
  sendText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: "#fff" },
  discardBtn: { minHeight: 44, flexDirection: "row", gap: 6, paddingHorizontal: spacing.lg, borderRadius: radius.md, backgroundColor: "#FEE2E2", alignItems: "center", justifyContent: "center" },
  discardText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: "#991B1B" },
});
