// Phase 35 · Feb-2026 — Mobile Vendor Bills (P1.1 Finance Parity).
// Phase 41.2 · Feb-2026 — refactored onto the shared `<AdminListPage>`
// primitive; row + sheet body unchanged.
//
// Web parity: `frontend/src/pages/admin/VendorBills.jsx`.
// Backend: GET/POST/PATCH `/api/cfo/bills`.
// Admin / super-admin only.
import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, TextInput } from "react-native";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize, money } from "@/src/theme";
import { PrimaryButton, Sheet } from "@/src/components/ui";
import { AdminListPage } from "@/src/components/layout/AdminListPage";

type Bill = {
  id: string;
  vendor_name: string;
  bill_date?: string;
  due_date?: string;
  amount_cents?: number;
  paid_amount_cents?: number;
  status?: "open" | "paid" | "partial" | "void";
  notes?: string;
};

function _todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

export default function VendorBillsMobile() {
  const [rows, setRows] = useState<Bill[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [draft, setDraft] = useState<Partial<Bill> & { _amount?: string }>({});
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r: any = await api.get("/cfo/bills");
      setRows(Array.isArray(r?.items) ? r.items : Array.isArray(r) ? r : []);
    } catch {
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const openCreate = () => {
    setDraft({
      vendor_name: "", bill_date: _todayIso(), due_date: _todayIso(),
      _amount: "", status: "open", notes: "",
    });
    setAddOpen(true);
  };

  const save = useCallback(async () => {
    if (!draft.vendor_name || !(draft._amount)) return;
    setBusy(true);
    try {
      const payload = {
        vendor_name: draft.vendor_name,
        bill_date: draft.bill_date,
        due_date: draft.due_date,
        amount_cents: Math.round(Number(draft._amount) * 100),
        paid_amount_cents: 0,
        status: draft.status || "open",
        notes: draft.notes || "",
      };
      await api.post("/cfo/bills", payload);
      setAddOpen(false);
      await load();
    } catch { /* ignore */ } finally {
      setBusy(false);
    }
  }, [draft, load]);

  return (
    <AdminListPage
      title="Vendor Bills"
      testID="vendor-bills-page"
      loading={loading}
      isEmpty={rows.length === 0}
      refreshing={refreshing}
      onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }}
      emptyIcon="receipt-outline"
      emptyTitle="No vendor bills yet"
      emptySubtitle="Tap + to log an accounts-payable bill."
      emptyTestID="vendor-bills-empty"
      onCreate={openCreate}
      createTestID="vendor-bills-create"
      sheet={
        <Sheet
          visible={addOpen}
          onClose={() => setAddOpen(false)}
          title="New vendor bill"
          testID="vendor-bills-sheet"
        >
          <View style={{ gap: spacing.md, padding: spacing.lg }}>
            <Field label="Vendor name" testID="vendor-bills-field-vendor">
              <TextInput
                value={draft.vendor_name || ""}
                onChangeText={(t) => setDraft((d) => ({ ...d, vendor_name: t }))}
                style={styles.input}
                testID="vendor-bills-input-vendor"
              />
            </Field>
            <Field label="Amount (dollars)" testID="vendor-bills-field-amount">
              <TextInput
                value={draft._amount || ""}
                onChangeText={(t) => setDraft((d) => ({ ...d, _amount: t }))}
                keyboardType="decimal-pad"
                style={styles.input}
                testID="vendor-bills-input-amount"
              />
            </Field>
            <Field label="Due date (YYYY-MM-DD)" testID="vendor-bills-field-due">
              <TextInput
                value={draft.due_date || ""}
                onChangeText={(t) => setDraft((d) => ({ ...d, due_date: t }))}
                style={styles.input}
                testID="vendor-bills-input-due"
              />
            </Field>
            <Field label="Notes" testID="vendor-bills-field-notes">
              <TextInput
                value={draft.notes || ""}
                onChangeText={(t) => setDraft((d) => ({ ...d, notes: t }))}
                style={[styles.input, { minHeight: 60 }]}
                multiline
                testID="vendor-bills-input-notes"
              />
            </Field>
            <PrimaryButton
              label={busy ? "Saving…" : "Save"}
              onPress={save}
              disabled={busy || !draft.vendor_name || !draft._amount}
              testID="vendor-bills-save"
            />
          </View>
        </Sheet>
      }
    >
      {rows.map((r) => (
        <View key={r.id} style={styles.row} testID={`vendor-bill-row-${r.id}`}>
          <View style={styles.rowHead}>
            <Text style={styles.vendor}>{r.vendor_name}</Text>
            <Text style={[
              styles.status,
              r.status === "paid" ? { color: colors.success } :
              r.status === "partial" ? { color: colors.brand } :
              r.status === "void" ? { color: colors.muted } :
              { color: colors.warning || colors.brand },
            ]}>
              {(r.status || "open").toUpperCase()}
            </Text>
          </View>
          <View style={styles.metaRow}>
            <Text style={styles.meta}>Due {r.due_date || "—"}</Text>
            <Text style={styles.amt}>{money((r.amount_cents || 0) / 100)}</Text>
          </View>
          {r.notes ? <Text style={styles.notes} numberOfLines={2}>{r.notes}</Text> : null}
        </View>
      ))}
    </AdminListPage>
  );
}

function Field({ label, children, testID }: {
  label: string; children: React.ReactNode; testID?: string;
}) {
  return (
    <View testID={testID}>
      <Text style={styles.fieldLabel}>{label}</Text>
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    padding: spacing.md, borderRadius: radius.md, borderWidth: 1,
    borderColor: colors.border, backgroundColor: colors.surface, gap: spacing.xs,
  },
  rowHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  vendor: { fontFamily: font.semibold, fontSize: fontSize.md, color: colors.onSurface },
  status: { fontFamily: font.bold, fontSize: 10, letterSpacing: 0.5 },
  metaRow: { flexDirection: "row", justifyContent: "space-between" },
  meta: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  amt: { fontFamily: font.bold, fontSize: fontSize.md, color: colors.onSurface },
  notes: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
  fieldLabel: {
    fontFamily: font.medium, fontSize: 11, textTransform: "uppercase",
    letterSpacing: 0.5, color: colors.muted, marginBottom: 4,
  },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.sm,
    padding: spacing.sm, fontFamily: font.regular, fontSize: fontSize.md,
    backgroundColor: colors.surface,
  },
});
