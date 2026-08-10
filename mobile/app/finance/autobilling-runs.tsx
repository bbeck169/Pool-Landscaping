// Phase 35 · Feb-2026 — Mobile Autobilling Runs (P1.1 Finance Parity).
//
// Web parity: `frontend/src/pages/finance/AutobillingRuns.jsx`.
// Backend: GET /api/autobilling-runs, POST /api/autobilling/runs/bulk-cancel.
// Admin / super-admin only. Filter by status; bulk-cancel queued runs.
import React, { useCallback, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, RefreshControl,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize, money } from "@/src/theme";
import { Card, Loading, EmptyState, PrimaryButton } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";
import { RoleGate } from "@/src/components/RoleGate";
import { showConfirm } from "@/src/components/ConfirmModal";

type Run = {
  id: string;
  plan_id?: string;
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
  started_at?: string;
  completed_at?: string;
  invoice_count?: number;
  total_amount_cents?: number;
};

const FILTERS: { key: string; label: string }[] = [
  { key: "", label: "All" },
  { key: "queued", label: "Queued" },
  { key: "running", label: "Running" },
  { key: "completed", label: "Done" },
  { key: "failed", label: "Failed" },
  { key: "cancelled", label: "Cancelled" },
];

function _statusColor(s: string): string {
  if (s === "completed") return colors.success;
  if (s === "failed") return colors.error;
  if (s === "cancelled") return colors.muted;
  return colors.brand;
}

export default function AutobillingRunsMobile() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const qs = statusFilter ? `?status=${encodeURIComponent(statusFilter)}` : "";
      const r: any = await api.get(`/autobilling-runs${qs}`);
      setRuns(Array.isArray(r) ? r : r?.items || []);
    } catch {
      setRuns([]);
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const cancellable = useMemo(
    () => runs.filter((r) => r.status === "queued" && selected.has(r.id)),
    [runs, selected],
  );

  const toggle = (id: string) => setSelected((s) => {
    const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n;
  });

  const bulkCancel = useCallback(() => {
    if (cancellable.length === 0) return;
    showConfirm({
      title: `Cancel ${cancellable.length} queued run(s)?`,
      description: "This stops future execution — already-completed rows are untouched.",
      confirmLabel: "Cancel runs",
      destructive: true,
      testID: "autobilling-runs-bulk-cancel-confirm",
      onConfirm: async () => {
        setBusy(true);
        try {
          await api.post("/autobilling/runs/bulk-cancel", {
            ids: cancellable.map((r) => r.id),
          });
          setSelected(new Set());
          await load();
        } catch { /* ignore */ } finally {
          setBusy(false);
        }
      },
    });
  }, [cancellable, load]);

  return (
    <RoleGate level="strict_admin">
      <View style={styles.container} testID="autobilling-runs-page">
        <Header title="Autobilling Runs" />
        <ScrollView
          contentContainerStyle={styles.body}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={async () => {
              setRefreshing(true); await load(); setRefreshing(false);
            }} />
          }
        >
          {/* Filter row */}
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={styles.filterRow}
            testID="autobilling-runs-filters"
          >
            {FILTERS.map((f) => (
              <Pressable
                key={f.key || "all"}
                onPress={() => setStatusFilter(f.key)}
                style={[styles.chip, statusFilter === f.key && styles.chipActive]}
                testID={`autobilling-runs-filter-${f.key || "all"}`}
              >
                <Text style={[styles.chipText, statusFilter === f.key && styles.chipTextActive]}>
                  {f.label}
                </Text>
              </Pressable>
            ))}
          </ScrollView>

          {cancellable.length > 0 && (
            <PrimaryButton
              label={busy ? "Cancelling…" : `Cancel ${cancellable.length} queued`}
              onPress={bulkCancel}
              disabled={busy}
              testID="autobilling-runs-bulk-cancel"
            />
          )}

          {loading ? (
            <Loading />
          ) : runs.length === 0 ? (
            <EmptyState
              icon="sync-outline"
              title="No runs yet"
              subtitle="Autobilling runs will appear here once plans are active."
              testID="autobilling-runs-empty"
            />
          ) : (
            runs.map((r) => {
              const isChecked = selected.has(r.id);
              return (
                <Pressable
                  key={r.id}
                  onPress={() => r.status === "queued" && toggle(r.id)}
                  style={[styles.row, isChecked && styles.rowSelected]}
                  testID={`autobilling-run-row-${r.id}`}
                >
                  <View style={styles.rowHead}>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.runDate}>
                        {r.started_at ? new Date(r.started_at).toLocaleString() : "—"}
                      </Text>
                      <Text style={[styles.statusTag, { color: _statusColor(r.status) }]}>
                        {r.status.toUpperCase()}
                      </Text>
                    </View>
                    {r.status === "queued" && (
                      <Ionicons
                        name={isChecked ? "checkbox" : "square-outline"}
                        size={22}
                        color={isChecked ? colors.brand : colors.muted}
                      />
                    )}
                  </View>
                  <View style={styles.metaRow}>
                    <Text style={styles.meta}>{r.invoice_count ?? 0} invoices</Text>
                    <Text style={styles.meta}>{money((r.total_amount_cents || 0) / 100)}</Text>
                  </View>
                </Pressable>
              );
            })
          )}
        </ScrollView>
      </View>
    </RoleGate>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.surface },
  body: { padding: spacing.lg, gap: spacing.md, paddingBottom: spacing["3xl"] },
  filterRow: { flexDirection: "row", gap: spacing.xs, paddingRight: spacing.lg },
  chip: {
    paddingHorizontal: 12, paddingVertical: 6, borderRadius: radius.pill,
    borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface,
  },
  chipActive: { backgroundColor: colors.brandTertiary, borderColor: colors.brand },
  chipText: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted },
  chipTextActive: { color: colors.brand },
  row: {
    padding: spacing.md, borderRadius: radius.md, borderWidth: 1,
    borderColor: colors.border, backgroundColor: colors.surface, gap: spacing.sm,
  },
  rowSelected: { borderColor: colors.brand, backgroundColor: colors.brandTertiary },
  rowHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  runDate: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurface },
  statusTag: { fontFamily: font.bold, fontSize: 10, letterSpacing: 0.6, marginTop: 2 },
  metaRow: { flexDirection: "row", justifyContent: "space-between" },
  meta: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
});
