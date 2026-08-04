// Phase 37 · Feb-2026 — Business OS Scorecards (P1.3).
// Phase 41.2 · Feb-2026 — refactored onto the shared `<AdminListPage>`.
// Web: BusinessOS.jsx Scorecards slice. Backend: GET/POST /kpi-scorecards.
import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, TextInput } from "react-native";
import { useFocusEffect } from "expo-router";
import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { PrimaryButton, Sheet } from "@/src/components/ui";
import { AdminListPage } from "@/src/components/layout/AdminListPage";

export default function OsScorecards() {
  const [rows, setRows] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [draft, setDraft] = useState({ label: "", target: "", unit: "" });
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r: any = await api.get("/kpi-scorecards");
      setRows(Array.isArray(r) ? r : r?.items || []);
    } catch { setRows([]); } finally { setLoading(false); }
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const save = useCallback(async () => {
    if (!draft.label.trim()) return;
    setBusy(true);
    try {
      await api.post("/kpi-scorecards", {
        label: draft.label,
        target: Number(draft.target) || 0,
        unit: draft.unit || "",
      });
      setAddOpen(false); setDraft({ label: "", target: "", unit: "" });
      await load();
    } catch { /* ignore */ } finally { setBusy(false); }
  }, [draft, load]);

  return (
    <AdminListPage
      title="Scorecards"
      testID="os-scorecards-page"
      loading={loading}
      isEmpty={rows.length === 0}
      refreshing={refreshing}
      onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }}
      emptyIcon="trophy-outline"
      emptyTitle="No scorecards yet"
      emptySubtitle="Tap + to define a KPI to track."
      emptyTestID="os-scorecards-empty"
      onCreate={() => setAddOpen(true)}
      createTestID="os-scorecards-create"
      sheet={
        <Sheet visible={addOpen} onClose={() => setAddOpen(false)} title="New scorecard" testID="os-scorecards-sheet">
          <View style={{ gap: spacing.md, padding: spacing.lg }}>
            <TextInput placeholder="Label (e.g. NPS)" value={draft.label} onChangeText={(t) => setDraft((d) => ({ ...d, label: t }))} style={styles.input} testID="os-scorecards-input-label" />
            <TextInput placeholder="Target" value={draft.target} onChangeText={(t) => setDraft((d) => ({ ...d, target: t }))} keyboardType="decimal-pad" style={styles.input} testID="os-scorecards-input-target" />
            <TextInput placeholder="Unit (%, $, count)" value={draft.unit} onChangeText={(t) => setDraft((d) => ({ ...d, unit: t }))} style={styles.input} testID="os-scorecards-input-unit" />
            <PrimaryButton label={busy ? "Saving…" : "Save"} onPress={save} disabled={busy || !draft.label.trim()} testID="os-scorecards-save" />
          </View>
        </Sheet>
      }
    >
      {rows.map((r) => (
        <View key={r.id} style={styles.row} testID={`os-scorecard-row-${r.id}`}>
          <View style={styles.head}>
            <Text style={styles.label}>{r.label || "—"}</Text>
            <Text style={styles.target}>Target {r.target ?? "—"} {r.unit || ""}</Text>
          </View>
          {typeof r.current_value === "number" ? (
            <Text style={[styles.current, r.current_value >= (r.target || 0) ? { color: colors.success } : { color: colors.error }]}>
              Current: {r.current_value} {r.unit || ""}
            </Text>
          ) : null}
        </View>
      ))}
    </AdminListPage>
  );
}

const styles = StyleSheet.create({
  row: { padding: spacing.md, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface, gap: 4 },
  head: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  label: { fontFamily: font.semibold, fontSize: fontSize.md, color: colors.onSurface },
  target: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted },
  current: { fontFamily: font.bold, fontSize: fontSize.sm },
  input: { borderWidth: 1, borderColor: colors.border, borderRadius: radius.sm, padding: spacing.sm, fontFamily: font.regular, fontSize: fontSize.md, backgroundColor: colors.surface },
});
