/**
 * Dashboard parity · read-only mobile port of web
 * `DashboardDrillDownModal variant="income-by-category"` (Revenue by
 * Category legend drill-down). GET /dashboard/income/by-category/rows
 * ?category&from&to&limit=100[&cursor] → `{rows,total,next_cursor}`.
 * Row tap → invoice (`/quote/<invoice_id>`). Web's inline recategorise /
 * line-item audit editing is NOT ported (web-only).
 */
import React, { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, Pressable, ActivityIndicator } from "react-native";
import { useRouter } from "expo-router";
import { api } from "@/src/api";
import { Sheet } from "@/src/components/ui";
import { colors, spacing, radius, font, fontSize, money } from "@/src/theme";

type Props = { category: string | null; range?: { start: string; end: string } | null; onClose: () => void };

function Row({ r, onPress }: { r: any; onPress: () => void }) {
  const meta = [(r.date || "").slice(0, 10), r.customer_name || String(r.customer_id || "").slice(0, 8),
    r.invoice_number || String(r.invoice_id || "").slice(0, 8)].filter(Boolean).join(" · ");
  return (
    <Pressable style={({ pressed }) => [s.row, pressed && { opacity: 0.7 }]} onPress={onPress}
      testID={`income-row-${r.invoice_id}-${r.line_index ?? "x"}`}>
      <View style={{ flex: 1, minWidth: 0 }}>
        <Text style={s.desc} numberOfLines={2}>{r.description || "—"}</Text>
        <Text style={s.meta} numberOfLines={1}>{meta}</Text>
      </View>
      <Text style={s.amt}>{money(Number(r.extended || 0))}</Text>
    </Pressable>
  );
}

export default function IncomeDrillDownSheet({ category, range, onClose }: Props) {
  const router = useRouter();
  const [rows, setRows] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  const fetchPage = useCallback(async (cur: string | null) => {
    if (!category || !range?.start || !range?.end) return;
    setLoading(true); setErr("");
    try {
      const r: any = await api.get(`/dashboard/income/by-category/rows?category=${encodeURIComponent(category)}&from=${range.start}&to=${range.end}&limit=100${cur ? `&cursor=${cur}` : ""}`);
      setRows((prev) => (cur ? [...prev, ...(r?.rows || [])] : r?.rows || []));
      setTotal(Number(r?.total || 0));
      setCursor(r?.next_cursor || null);
    } catch (e: any) {
      setErr(e?.message || "Failed to load line items.");
    } finally {
      setLoading(false);
    }
  }, [category, range?.start, range?.end]);

  useEffect(() => { setRows([]); setTotal(0); setCursor(null); fetchPage(null); }, [fetchPage]);

  return (
    <Sheet visible={!!category} onClose={onClose} title={`${category || ""} · line items`} testID="drilldown-income-by-category">
      <View testID="drilldown-body-income-by-category">
        {rows.length ? <Text style={s.count} testID="drilldown-count">{`${total} line item${total === 1 ? "" : "s"}`}</Text> : null}
        {rows.map((r) => (
          <Row key={`${r.invoice_id}-${r.line_index ?? "x"}`} r={r} onPress={() => { onClose(); router.push(`/quote/${r.invoice_id}` as any); }} />
        ))}
        {loading ? <ActivityIndicator style={{ margin: spacing.md }} color={colors.brand} testID="drilldown-loading" /> : null}
        {err ? <Text style={s.err} testID="drilldown-error">{err}</Text> : null}
        {!loading && !err && rows.length === 0 ? (
          <Text style={s.empty} testID="drilldown-empty">No line items in this bucket for the selected range.</Text>
        ) : null}
        {cursor && !loading ? (
          <Pressable style={s.more} onPress={() => fetchPage(cursor)} testID="drilldown-load-more">
            <Text style={s.moreText}>{`Load more (${Math.max(0, total - rows.length)} remaining)`}</Text>
          </Pressable>
        ) : null}
      </View>
    </Sheet>
  );
}

const s = StyleSheet.create({
  count: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted, paddingHorizontal: spacing.lg, paddingBottom: spacing.sm },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.md, minHeight: 56, paddingHorizontal: spacing.lg, paddingVertical: spacing.sm, borderTopWidth: 1, borderTopColor: colors.divider },
  desc: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface },
  meta: { fontFamily: font.regular, fontSize: 12, color: colors.muted, marginTop: 2 },
  amt: { fontFamily: font.bold, fontSize: fontSize.sm, color: colors.onSurface },
  err: { padding: spacing.md, fontFamily: font.medium, fontSize: fontSize.sm, color: colors.error },
  empty: { padding: spacing.xl, textAlign: "center", fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  more: { margin: spacing.lg, minHeight: 44, alignItems: "center", justifyContent: "center", borderRadius: radius.pill, borderWidth: 1, borderColor: colors.border },
  moreText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.brand },
});
