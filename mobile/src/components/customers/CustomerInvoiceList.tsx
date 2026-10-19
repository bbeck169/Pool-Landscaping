/**
 * TD-79 (web db3ef6d2f) — customer profile Overview · invoice list
 * section (last 10 + "View all"). Mobile port of web
 * `components/customers/CustomerInvoiceList.jsx`.
 *
 * Data: GET /api/quotes?doc_type=invoice&customer_id=<cid>&limit=10&offset=0
 *   → `{rows, total_count, has_more}` (bare-array fallback kept, like web).
 * Sort: created_at DESC, id lex DESC tiebreak. Cap 10 rows.
 * Row: number · title (shared `resolvePortalInvoiceTitle`) · due · amount
 *   · status badge. Tap → admin invoice detail `/quote/<id>`.
 * "View all" only when total_count > 10 → `/invoices?customer_id=<cid>`.
 */
import React, { useEffect, useState } from "react";
import { View, Text, Pressable, ActivityIndicator, StyleSheet } from "react-native";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize, money, statusMeta } from "@/src/theme";
import { resolvePortalInvoiceTitle } from "@/src/lib/portalInvoiceTitle";

export const OVERVIEW_INVOICE_CAP = 10;

export function sortByCreatedDesc(rows: any[]): any[] {
  return [...(rows || [])].sort((a, b) => {
    const t = String(b?.created_at || "").localeCompare(String(a?.created_at || ""));
    return t !== 0 ? t : String(b?.id || "").localeCompare(String(a?.id || ""));
  });
}

function badge(status: string) {
  const s = String(status || "unpaid").toLowerCase();
  if (s === "overdue") return { label: "Overdue", bg: "#FEE2E2", fg: colors.error };
  const label = (s.charAt(0).toUpperCase() + s.slice(1)).replace(/_/g, " ");
  return statusMeta[s] || { label, bg: "#FEF9C3", fg: "#A16207" };
}

export default function CustomerInvoiceList({ customerId }: { customerId: string }) {
  const router = useRouter();
  const [rows, setRows] = useState<any[] | null>(null);
  const [total, setTotal] = useState(0);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!customerId) return;
    let alive = true;
    setRows(null); setErr(null);
    const q = `?doc_type=invoice&customer_id=${encodeURIComponent(customerId)}&limit=${OVERVIEW_INVOICE_CAP}&offset=0`;
    api.get(`/quotes${q}`)
      .then((d: any) => {
        if (!alive) return;
        const list = Array.isArray(d) ? d : Array.isArray(d?.rows) ? d.rows : [];
        setRows(sortByCreatedDesc(list).slice(0, OVERVIEW_INVOICE_CAP));
        setTotal(Array.isArray(d) ? d.length : Number(d?.total_count || list.length));
      })
      .catch((e: any) => { if (alive) { setErr(e?.message || "Failed to load invoices."); setRows([]); } });
    return () => { alive = false; };
  }, [customerId]);

  return (
    <View style={s.section} testID="cd-overview-invoices-section">
      <View style={s.header}>
        <Text style={s.title} testID="cd-overview-invoices-header">
          Invoices{total > 0 ? <Text style={s.count} testID="cd-overview-invoices-count">{`  (${total})`}</Text> : null}
        </Text>
        {total > OVERVIEW_INVOICE_CAP ? (
          <Pressable
            onPress={() => router.push(`/invoices?customer_id=${encodeURIComponent(customerId)}` as any)}
            hitSlop={12} style={s.viewAll} testID="cd-overview-invoices-view-all" accessibilityRole="link"
          >
            <Text style={s.viewAllText}>View all</Text>
            <Ionicons name="chevron-forward" size={14} color={colors.brand} />
          </Pressable>
        ) : null}
      </View>
      {rows === null ? (
        <ActivityIndicator color={colors.brand} style={{ marginVertical: spacing.md }} testID="cd-overview-invoices-loading" />
      ) : err ? (
        <View style={s.errorPill} testID="cd-overview-invoices-error">
          <Ionicons name="alert-circle-outline" size={16} color={colors.error} />
          <Text style={s.errorText}>{err}</Text>
        </View>
      ) : rows.length === 0 ? (
        <Text style={s.empty} testID="cd-overview-invoices-empty">No invoices yet.</Text>
      ) : (
        rows.map((r) => {
          const b = badge(r.payment_status);
          return (
            <Pressable
              key={r.id}
              onPress={() => router.push(`/quote/${r.id}` as any)}
              style={({ pressed }) => [s.row, pressed && { opacity: 0.7 }]}
              testID={`cd-overview-invoice-row-${r.id}`}
            >
              <View style={{ flex: 1, minWidth: 0 }}>
                <Text style={s.rowTitle} numberOfLines={1}>{resolvePortalInvoiceTitle(r)}</Text>
                <Text style={s.rowMeta} numberOfLines={1}>{`${r.invoice_number || "—"} · Due ${r.due_date || "—"}`}</Text>
              </View>
              <View style={{ alignItems: "flex-end", gap: 4 }}>
                <Text style={s.amount}>{money(r.total)}</Text>
                <View style={[s.chip, { backgroundColor: b.bg }]} testID={`cd-overview-invoice-status-${r.id}`}>
                  <Text style={[s.chipText, { color: b.fg }]}>{b.label}</Text>
                </View>
              </View>
            </Pressable>
          );
        })
      )}
    </View>
  );
}

const s = StyleSheet.create({
  section: { gap: spacing.xs },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: spacing.xs },
  title: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  count: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  viewAll: { flexDirection: "row", alignItems: "center", gap: 2, minHeight: 44, paddingLeft: spacing.sm },
  viewAllText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.brand },
  row: {
    flexDirection: "row", alignItems: "center", gap: spacing.md, minHeight: 56,
    paddingVertical: spacing.sm, borderTopWidth: 1, borderTopColor: colors.border,
  },
  rowTitle: { fontFamily: font.medium, fontSize: fontSize.base, color: colors.onSurface },
  rowMeta: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
  amount: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  chip: { paddingHorizontal: spacing.sm, paddingVertical: 2, borderRadius: radius.pill },
  chipText: { fontFamily: font.semibold, fontSize: 11 },
  empty: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, paddingVertical: spacing.sm },
  errorPill: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm, backgroundColor: "#FEE2E2",
    borderRadius: radius.md, paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
  },
  errorText: { flex: 1, fontFamily: font.medium, fontSize: fontSize.sm, color: colors.error },
});
