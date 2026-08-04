// Phase 35 · Feb-2026 — Mobile Recurring Jobs (P1.1 Finance Parity).
// Phase 41.2 · Feb-2026 — refactored onto the shared `<AdminListPage>`
// primitive; row + sheet-less shape unchanged.
//
// Web parity: `frontend/src/pages/admin/RecurringJobs.jsx`.
// Backend: canonical `/api/recurring-jobs` CRUD + POST /generate.
// Admin / super-admin / manager only.
import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, Switch } from "react-native";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize, money } from "@/src/theme";
import { PrimaryButton } from "@/src/components/ui";
import { showConfirm } from "@/src/components/ConfirmModal";
import { AdminListPage } from "@/src/components/layout/AdminListPage";

type RecurringJob = {
  id: string;
  customer_id?: string;
  customer_name?: string;
  frequency: "weekly" | "biweekly" | "monthly" | "custom";
  day_of_week?: number;
  day_of_month?: number;
  interval_days?: number;
  start_date?: string;
  price_cents?: number;
  active: boolean;
  notes?: string;
};

const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

function _cadenceLabel(r: RecurringJob): string {
  if (r.frequency === "weekly" || r.frequency === "biweekly") {
    return `${r.frequency} (${DOW[r.day_of_week ?? 0] || "?"})`;
  }
  if (r.frequency === "monthly") return `monthly (day ${r.day_of_month ?? "?"})`;
  if (r.frequency === "custom") return `custom (${r.interval_days ?? "?"}d)`;
  return r.frequency;
}

export default function RecurringJobsMobile() {
  const [rows, setRows] = useState<RecurringJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r: any = await api.get("/recurring-jobs");
      setRows(Array.isArray(r) ? r : r?.items || []);
    } catch {
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const toggleActive = useCallback(async (row: RecurringJob) => {
    setBusyId(row.id);
    try {
      await api.patch(`/recurring-jobs/${row.id}`, { active: !row.active });
      await load();
    } catch { /* ignore */ } finally {
      setBusyId(null);
    }
  }, [load]);

  const generateNow = useCallback((row: RecurringJob) => {
    showConfirm({
      title: `Generate jobs for "${row.customer_name || row.customer_id}"?`,
      description:
        "Creates the next ~2 weeks of scheduled jobs from this template. Safe to re-run.",
      confirmLabel: "Generate",
      testID: "recurring-generate-confirm",
      onConfirm: async () => {
        setBusyId(row.id);
        try {
          const through = new Date(Date.now() + 14 * 86400_000)
            .toISOString().slice(0, 10);
          await api.post(
            `/recurring-jobs/${row.id}/generate?through=${through}`, {},
          );
          await load();
        } catch { /* ignore */ } finally {
          setBusyId(null);
        }
      },
    });
  }, [load]);

  return (
    <AdminListPage
      title="Recurring Jobs"
      testID="recurring-jobs-page"
      loading={loading}
      isEmpty={rows.length === 0}
      refreshing={refreshing}
      onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }}
      emptyIcon="repeat-outline"
      emptyTitle="No recurring jobs yet"
      emptySubtitle="Create templates on the desktop admin page."
      emptyTestID="recurring-empty"
      headerExtra={
        <Text style={styles.hint} testID="recurring-hint">
          Auto-generates a rolling 2-week horizon of jobs (nightly at 02:00 UTC).
        </Text>
      }
    >
      {rows.map((r) => (
        <View key={r.id} style={styles.row} testID={`recurring-row-${r.id}`}>
          <View style={styles.rowHead}>
            <Text style={styles.customer}>{r.customer_name || r.customer_id || "—"}</Text>
            <Switch
              value={r.active}
              onValueChange={() => toggleActive(r)}
              disabled={busyId === r.id}
              testID={`recurring-toggle-${r.id}`}
            />
          </View>
          <View style={styles.metaRow}>
            <Text style={styles.meta}>{_cadenceLabel(r)}</Text>
            <Text style={styles.meta}>{money((r.price_cents || 0) / 100)}</Text>
          </View>
          {r.notes ? (
            <Text style={styles.notes} numberOfLines={2}>{r.notes}</Text>
          ) : null}
          <PrimaryButton
            label={busyId === r.id ? "Working…" : "Generate now"}
            onPress={() => generateNow(r)}
            disabled={busyId === r.id || !r.active}
            testID={`recurring-generate-${r.id}`}
          />
        </View>
      ))}
    </AdminListPage>
  );
}

const styles = StyleSheet.create({
  hint: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  row: {
    padding: spacing.md, borderRadius: radius.md, borderWidth: 1,
    borderColor: colors.border, backgroundColor: colors.surface, gap: spacing.sm,
  },
  rowHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  customer: { fontFamily: font.semibold, fontSize: fontSize.md, color: colors.onSurface },
  metaRow: { flexDirection: "row", justifyContent: "space-between" },
  meta: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  notes: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
});
