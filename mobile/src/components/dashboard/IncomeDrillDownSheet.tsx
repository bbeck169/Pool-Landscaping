/**
 * Mobile port of web `DashboardDrillDownModal variant="income-by-category"`
 * (Revenue by Category legend drill-down). GET /dashboard/income/by-category/rows
 * ?category&from&to&limit=100[&cursor] → `{rows,total,next_cursor}`.
 * Row tap → invoice (`/quote/<invoice_id>`).
 *
 * TD-81 (B-narrow) · per-row "Re-classify" → Business Unit picker →
 * minimal `PATCH /quotes/{invoice_id}` (`buildBusinessUnitPatch`, K48/A2) +
 * best-effort `POST /dashboard/drilldown/line-item-audit`. Optimistic with
 * rollback; "Moved to X" chip when the new bucket differs (web parity, stays
 * until the sheet is reopened). `onEdited` fires on close after any save so
 * the tile refetches. Service Unit / description / qty / price edits are
 * NOT ported (web-only).
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { View, Text, StyleSheet, Pressable, ActivityIndicator } from "react-native";
import { useRouter } from "expo-router";
import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { Sheet } from "@/src/components/ui";
import { useToast } from "@/src/components/ToastProvider";
import BusinessUnitPickerSheet from "@/src/components/dashboard/BusinessUnitPickerSheet";
import { buildBusinessUnitPatch, k48StatusFlags, resolveBusinessUnitId, type IncomeCategory } from "@/src/lib/k48";
import { colors, spacing, radius, font, fontSize, money } from "@/src/theme";

type Props = { category: string | null; range?: { start: string; end: string } | null; onClose: () => void; onEdited?: () => void };
type RowEdit = { buId?: string; movedTo?: string | null; err?: string; saving?: boolean };

const rowKey = (r: any) => `${r.invoice_id}-${r.line_index ?? "x"}`;

function errMsg(e: any): string {
  const d = e?.detail;
  if (typeof d === "string" && d) return d;
  return d?.error || d?.message || e?.message || "Save failed";
}

function Row({ r, edit, onPress, onReclassify }: { r: any; edit?: RowEdit; onPress: () => void; onReclassify: () => void }) {
  const k = rowKey(r);
  const terminal = k48StatusFlags(r).isTerminal;
  const meta = [(r.date || "").slice(0, 10), r.customer_name || String(r.customer_id || "").slice(0, 8),
    r.invoice_number || String(r.invoice_id || "").slice(0, 8)].filter(Boolean).join(" · ");
  return (
    <View style={s.row}>
      <Pressable style={({ pressed }) => [s.main, pressed && { opacity: 0.7 }]} onPress={onPress} testID={`income-row-${k}`}>
        <View style={{ flex: 1, minWidth: 0 }}>
          <Text style={s.desc} numberOfLines={2}>{r.description || "—"}</Text>
          <Text style={s.meta} numberOfLines={1}>{meta}</Text>
          {edit?.movedTo ? <Text style={s.moved} testID={`income-row-${k}-bu-moved`}>{`Moved to ${edit.movedTo}`}</Text> : null}
          {terminal ? <Text style={s.note} testID={`income-row-${k}-bu-locked`}>Void/cancelled — cannot re-classify</Text> : null}
          {edit?.err ? <Text style={s.rowErr} testID={`income-row-${k}-error`}>{edit.err}</Text> : null}
        </View>
        <Text style={s.amt}>{money(Number(r.extended || 0))}</Text>
      </Pressable>
      <Pressable
        style={[s.reBtn, (terminal || edit?.saving) && { opacity: 0.4 }]} onPress={onReclassify}
        disabled={terminal || !!edit?.saving} accessibilityState={{ disabled: terminal || !!edit?.saving }}
        testID={`income-row-${k}-bu-trigger`}
      >
        {edit?.saving ? <ActivityIndicator size="small" color={colors.brand} /> : <Text style={s.reText}>Re-classify</Text>}
      </Pressable>
    </View>
  );
}

export default function IncomeDrillDownSheet({ category, range, onClose, onEdited }: Props) {
  const router = useRouter();
  const { user } = useAuth() || ({} as any);
  const { showToast } = useToast();
  const [rows, setRows] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [cats, setCats] = useState<IncomeCategory[]>([]);
  const [edits, setEdits] = useState<Record<string, RowEdit>>({});
  const [pickRow, setPickRow] = useState<any>(null);
  const editedRef = useRef(false);

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

  useEffect(() => {
    setRows([]); setTotal(0); setCursor(null); setEdits({}); editedRef.current = false;
    fetchPage(null);
  }, [fetchPage]);

  // BU options — once per sheet open (web: once per modal lifetime). Failure → empty picker.
  useEffect(() => {
    if (!category) return;
    let alive = true;
    api.get("/income-categories?include_archived=false")
      .then((r: any) => { if (alive) setCats(Array.isArray(r?.items) ? r.items : []); })
      .catch(() => { if (alive) setCats([]); });
    return () => { alive = false; };
  }, [category]);

  const close = () => {
    if (editedRef.current) { editedRef.current = false; onEdited?.(); }
    onClose();
  };

  const setEdit = (k: string, patch: RowEdit) => setEdits((m) => ({ ...m, [k]: { ...m[k], ...patch } }));
  const currentBuId = (r: any) => edits[rowKey(r)]?.buId ?? resolveBusinessUnitId(r, cats);

  const commit = async (r: any, next: IncomeCategory) => {
    setPickRow(null);
    const k = rowKey(r);
    if (k48StatusFlags(r).isTerminal) { setEdit(k, { err: "Invoice is void/cancelled — cannot re-classify." }); return; }
    const beforeId = currentBuId(r);
    if (next.id === beforeId) return;
    setEdit(k, { buId: next.id, saving: true, err: "" });
    try {
      await api.patch(`/quotes/${r.invoice_id}`, buildBusinessUnitPatch((user as any)?.role, r, next));
      try {
        await api.post("/dashboard/drilldown/line-item-audit", {
          tile: "income-by-category", invoice_id: r.invoice_id, line_index: r.line_index ?? null,
          field: "business_unit", before: beforeId || (r.category || "").trim() || null, after: next.name,
        });
      } catch (auditErr) {
        console.warn("[k48] audit companion failed", auditErr);
      }
      const moved = String(category || "").trim().toLowerCase() !== next.name.trim().toLowerCase() ? next.name : null;
      setEdit(k, { saving: false, movedTo: moved });
      editedRef.current = true;
    } catch (e: any) {
      const msg = errMsg(e);
      setEdit(k, { buId: beforeId, saving: false, err: msg });
      showToast(msg, "error");
    }
  };

  return (
    <Sheet visible={!!category} onClose={close} title={`${category || ""} · line items`} testID="drilldown-income-by-category">
      <View testID="drilldown-body-income-by-category">
        {rows.length ? <Text style={s.count} testID="drilldown-count">{`${total} line item${total === 1 ? "" : "s"}`}</Text> : null}
        {rows.map((r) => (
          <Row key={rowKey(r)} r={r} edit={edits[rowKey(r)]} onReclassify={() => setPickRow(r)}
            onPress={() => { close(); router.push(`/quote/${r.invoice_id}` as any); }} />
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
      <BusinessUnitPickerSheet
        visible={!!pickRow} categories={cats} selectedId={pickRow ? currentBuId(pickRow) : undefined}
        onSelect={(c) => pickRow && commit(pickRow, c)} onClose={() => setPickRow(null)}
      />
    </Sheet>
  );
}

const s = StyleSheet.create({
  count: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted, paddingHorizontal: spacing.lg, paddingBottom: spacing.sm },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.sm, paddingRight: spacing.lg, borderTopWidth: 1, borderTopColor: colors.divider },
  main: { flex: 1, flexDirection: "row", alignItems: "center", gap: spacing.md, minHeight: 56, paddingLeft: spacing.lg, paddingVertical: spacing.sm },
  desc: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface },
  meta: { fontFamily: font.regular, fontSize: 12, color: colors.muted, marginTop: 2 },
  moved: { alignSelf: "flex-start", marginTop: 4, paddingHorizontal: 8, paddingVertical: 2, borderRadius: radius.pill, backgroundColor: "#DCFCE7", color: colors.success, fontFamily: font.semibold, fontSize: 11, overflow: "hidden" },
  note: { marginTop: 4, fontFamily: font.regular, fontSize: 11, color: colors.muted },
  rowErr: { marginTop: 4, fontFamily: font.medium, fontSize: 11, color: colors.error },
  amt: { fontFamily: font.bold, fontSize: fontSize.sm, color: colors.onSurface },
  reBtn: { minHeight: 44, minWidth: 88, paddingHorizontal: spacing.sm, alignItems: "center", justifyContent: "center", borderRadius: radius.pill, borderWidth: 1, borderColor: colors.border },
  reText: { fontFamily: font.semibold, fontSize: 12, color: colors.brand },
  err: { padding: spacing.md, fontFamily: font.medium, fontSize: fontSize.sm, color: colors.error },
  empty: { padding: spacing.xl, textAlign: "center", fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  more: { margin: spacing.lg, minHeight: 44, alignItems: "center", justifyContent: "center", borderRadius: radius.pill, borderWidth: 1, borderColor: colors.border },
  moreText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.brand },
});
