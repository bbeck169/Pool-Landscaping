/**
 * InvoiceViewHistory — Phase K47 · Feb 2026 · Mobile parity for the
 * admin view-history card.
 *
 * Mirrors the web variant (``frontend/src/components/invoices/InvoiceViewHistory.jsx``):
 * fetches ``GET /api/invoices/{id}/views`` and renders a summary
 * line + collapsible event list. Hides itself when the endpoint
 * 403s (customer/technician roles) so it can be dropped into any
 * invoice detail screen without RBAC gating at the callsite.
 */
import React, { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, Pressable, ScrollView } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/api";
import { colors, font, fontSize, radius, spacing } from "@/src/theme";

type ViewEvent = {
  viewed_at: string;
  source: "email" | "sms" | "portal" | "link" | string;
  user_agent?: string | null;
  ip?: string | null;
};

type Summary = {
  invoice_id: string;
  first_viewed_at: string | null;
  last_viewed_at: string | null;
  view_count: number;
  events: ViewEvent[];
};

const SOURCE_META: Record<string, { label: string; bg: string; fg: string }> = {
  email:  { label: "Email",  bg: "#DBEAFE", fg: "#1E40AF" },
  sms:    { label: "SMS",    bg: "#D1FAE5", fg: "#065F46" },
  portal: { label: "Portal", bg: "#F3E8FF", fg: "#6B21A8" },
  link:   { label: "Link",   bg: "#F3F4F6", fg: "#374151" },
};

function relativeFromIso(iso: string): string {
  if (!iso) return "";
  const ts = Date.parse(iso);
  if (Number.isNaN(ts)) return "";
  const diffSec = Math.max(0, Math.floor((Date.now() - ts) / 1000));
  if (diffSec < 60)  return `${diffSec}s ago`;
  const m = Math.floor(diffSec / 60);
  if (m < 60)         return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24)         return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d < 30)         return `${d}d ago`;
  return `${Math.floor(d / 30)}mo ago`;
}

export default function InvoiceViewHistory({ invoiceId }: { invoiceId: string }) {
  const [data, setData] = useState<Summary | null>(null);
  const [err, setErr] = useState<string>("");
  const [open, setOpen] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await api.get(`/invoices/${invoiceId}/views`);
      setData(r as Summary);
    } catch (e: any) {
      // 403 → customer/technician — silently hide the card.
      const status = e?.status ?? e?.response?.status;
      if (status === 403) {
        setErr("hidden");
        return;
      }
      setErr(e?.message || "Failed to load view history");
    }
  }, [invoiceId]);

  useEffect(() => {
    if (invoiceId) load();
  }, [invoiceId, load]);

  if (err === "hidden") return null;
  if (err) {
    return (
      <View style={s.errCard} testID="invoice-view-history-error">
        <Text style={s.errText}>Couldn&apos;t load view history — {err}</Text>
      </View>
    );
  }
  if (!data) {
    return (
      <View style={s.loading} testID="invoice-view-history-loading">
        <Text style={s.loadingText}>Loading view history…</Text>
      </View>
    );
  }

  const { first_viewed_at, last_viewed_at, view_count, events } = data;

  return (
    <View style={s.card} testID="invoice-view-history-card">
      <View style={s.headerRow}>
        <View style={s.headerLeft}>
          <Ionicons name="eye-outline" size={18} color={colors.onSurface} />
          <Text style={s.headerText}>View History</Text>
        </View>
        {events.length > 0 && (
          <Pressable
            style={s.toggle}
            onPress={() => setOpen((v) => !v)}
            testID="invoice-view-history-toggle"
          >
            <Text style={s.toggleText}>
              {open ? "Collapse" : `Expand (${events.length})`}
            </Text>
            <Ionicons
              name={open ? "chevron-up" : "chevron-down"}
              size={14}
              color={colors.onSurfaceSecondary}
            />
          </Pressable>
        )}
      </View>

      {view_count === 0 ? (
        <Text style={s.empty} testID="invoice-view-history-empty">
          This invoice hasn&apos;t been opened yet.
        </Text>
      ) : (
        <Text style={s.summary} testID="invoice-view-history-summary">
          Viewed <Text style={s.summaryStrong} testID="invoice-view-count">{view_count}</Text>
          {view_count === 1 ? " time" : " times"}
          {first_viewed_at ? (
            <>
              {" · first "}
              <Text testID="invoice-view-first-at">{relativeFromIso(first_viewed_at)}</Text>
            </>
          ) : null}
          {last_viewed_at ? (
            <>
              {" · last "}
              <Text testID="invoice-view-last-at">{relativeFromIso(last_viewed_at)}</Text>
            </>
          ) : null}
        </Text>
      )}

      {open && events.length > 0 ? (
        <ScrollView style={s.eventsScroll} testID="invoice-view-history-events">
          {events.map((ev, idx) => {
            const meta = SOURCE_META[ev.source] || SOURCE_META.link;
            return (
              <View
                key={`${ev.viewed_at}-${idx}`}
                style={s.eventRow}
                testID={`invoice-view-history-event-${idx}`}
              >
                <View style={[s.badge, { backgroundColor: meta.bg }]}>
                  <Text style={[s.badgeText, { color: meta.fg }]} testID={`invoice-view-history-event-source-${idx}`}>
                    {meta.label}
                  </Text>
                </View>
                <Text style={s.eventMid} numberOfLines={1}>
                  {ev.user_agent || ev.ip || "—"}
                </Text>
                <Text style={s.eventTime}>{relativeFromIso(ev.viewed_at)}</Text>
              </View>
            );
          })}
        </ScrollView>
      ) : null}
    </View>
  );
}

const s = StyleSheet.create({
  card: {
    marginHorizontal: spacing.md, marginTop: spacing.md,
    padding: spacing.md, borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  headerRow: {
    flexDirection: "row", justifyContent: "space-between", alignItems: "center",
  },
  headerLeft: { flexDirection: "row", alignItems: "center", gap: 8 },
  headerText: { fontFamily: font.semibold, fontSize: fontSize.md, color: colors.onSurface },
  toggle: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: 8, paddingVertical: 4,
    borderRadius: radius.sm, borderWidth: 1, borderColor: colors.border,
  },
  toggleText: { fontFamily: font.medium, fontSize: fontSize.xs, color: colors.onSurfaceSecondary },
  empty: { marginTop: spacing.sm, fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  summary: { marginTop: spacing.sm, fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurface },
  summaryStrong: { fontFamily: font.bold, color: colors.onSurface },
  eventsScroll: { marginTop: spacing.sm, maxHeight: 220 },
  eventRow: {
    flexDirection: "row", alignItems: "center", gap: 8,
    paddingVertical: 6, borderBottomWidth: 1, borderBottomColor: colors.divider,
  },
  badge: { paddingHorizontal: 8, paddingVertical: 2, borderRadius: 999 },
  badgeText: { fontFamily: font.bold, fontSize: 10 },
  eventMid: { flex: 1, fontFamily: font.regular, fontSize: fontSize.xs, color: colors.onSurfaceSecondary },
  eventTime: { fontFamily: font.regular, fontSize: fontSize.xs, color: colors.onSurface },
  loading: { marginHorizontal: spacing.md, marginTop: spacing.md, padding: spacing.md },
  loadingText: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  errCard: {
    marginHorizontal: spacing.md, marginTop: spacing.md, padding: spacing.md,
    borderRadius: radius.md, borderWidth: 1, borderColor: colors.error,
    backgroundColor: "#FEF2F2",
  },
  errText: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.error },
});
