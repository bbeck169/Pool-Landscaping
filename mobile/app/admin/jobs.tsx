/**
 * Dashboard parity · mobile mirror of web `pages/jobs/JobsList.jsx`
 * (`/admin/jobs`, AdminOnly). Target of the Active Jobs / Pending KPI
 * tiles for admin / super_admin — `/(app)/jobs` redirects admins to the
 * calendar, so the filtered list needs its own route.
 *
 * `?status=` seeds the filter (straight passthrough to `GET /jobs`),
 * row tap → `/job/<id>`.
 *
 * TD-82 (B-narrow) · web JobsList bulk toolkit: long-press a row or tap
 * "Select" → select mode → BulkActionBar: Change status (silent),
 * Reschedule to date (sheet Apply = confirm), Delete (showConfirm).
 * Hits web endpoints `POST /jobs/bulk-update` / `POST /jobs/bulk-delete`
 * so locked jobs come back in `failed[]` → "X updated · Y locked" toast.
 * Select-all = loaded rows (GET /jobs caps at 1,000; web parity).
 */
import React, { useCallback, useMemo, useState } from "react";
import { View, Text, StyleSheet, FlatList, Pressable, RefreshControl } from "react-native";
import { Redirect, useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Loading, StatusChip } from "@/src/components/ui";
import { Header, FilterRow } from "@/src/components/widgets";
import { formatCustomerName } from "@/src/utils/formatCustomerName";
import { useToast } from "@/src/components/ToastProvider";
import { showConfirm } from "@/src/components/ConfirmModal";
import { useBulkSelect, BulkCheckbox, BulkActionBar } from "@/src/components/bulk-select/BulkSelectToolkit";
import JobStatusPickerSheet from "@/src/components/jobs/JobStatusPickerSheet";
import JobRescheduleSheet, { friendlyDate } from "@/src/components/jobs/JobRescheduleSheet";

const plural = (n: number) => `${n} job${n === 1 ? "" : "s"}`;

/** Web toast parity: "<msg>" or "<msg> · N locked — reason · reason · reason". */
export function bulkResultMessage(msg: string, failed: any[] | undefined): { text: string; variant: "success" | "info" } {
  const f = Array.isArray(failed) ? failed : [];
  if (!f.length) return { text: msg, variant: "success" };
  const reasons = f.slice(0, 3).map((x) => x?.reason).filter(Boolean).join(" · ");
  return { text: `${msg} · ${f.length} locked${reasons ? ` — ${reasons}` : ""}`, variant: "info" };
}

// Web STATUS_OPTIONS + leading "All" ("" on web).
export const ADMIN_JOB_STATUS_OPTIONS = [
  { key: "all", label: "All" },
  { key: "active", label: "Active" },
  { key: "pending", label: "Pending" },
  { key: "scheduled", label: "Scheduled" },
  { key: "in_progress", label: "In progress" },
  { key: "completed", label: "Completed" },
  { key: "canceled", label: "Canceled" },
];

type RowProps = { job: any; onPress: () => void; onLongPress: () => void; selectMode: boolean; checked: boolean };
function JobRow({ job, onPress, onLongPress, selectMode, checked }: RowProps) {
  return (
    <Pressable style={[styles.row, checked && styles.rowChecked]} onPress={onPress} onLongPress={onLongPress} testID={`job-row-${job.id}`}>
      {selectMode ? <BulkCheckbox checked={checked} onPress={onPress} testID={`job-row-check-${job.id}`} /> : null}
      <View style={{ flex: 1, minWidth: 0 }}>
        <Text style={styles.title} numberOfLines={1}>
          {job.title || job.service_name || `Job ${String(job.id).slice(0, 8)}`}
        </Text>
        <Text style={styles.meta} numberOfLines={1} testID={`job-row-customer-${job.id}`}>
          {[formatCustomerName(job), job.scheduled_date || "—"].filter(Boolean).join(" · ")}
        </Text>
      </View>
      <StatusChip status={job.status || "scheduled"} testID={`job-row-status-${job.id}`} />
    </Pressable>
  );
}

export default function AdminJobsList() {
  const { user } = useAuth();
  const router = useRouter();
  const params = useLocalSearchParams<{ status?: string }>();
  const initial = ADMIN_JOB_STATUS_OPTIONS.some((o) => o.key === params.status) ? String(params.status) : "all";
  const [status, setStatus] = useState(initial);
  const [rows, setRows] = useState<any[] | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const { showToast } = useToast();
  const visibleIds = useMemo(() => (rows || []).map((r) => String(r.id)), [rows]);
  const bulk = useBulkSelect(visibleIds);
  const [selectMode, setSelectMode] = useState(false);
  const [statusOpen, setStatusOpen] = useState(false);
  const [reschedOpen, setReschedOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  const exitSelect = () => { bulk.clear(); setSelectMode(false); };
  const ids = () => Array.from(bulk.selected);
  const report = (msg: string, failed?: any[]) => { const r = bulkResultMessage(msg, failed); showToast(r.text, r.variant); };

  const load = useCallback(async () => {
    const qs = status !== "all" ? `?status=${encodeURIComponent(status)}` : "";
    try {
      const r = await api.get(`/jobs${qs}`);
      setRows(Array.isArray(r) ? r : []);
    } catch {
      setRows([]);
    } finally {
      setRefreshing(false);
    }
  }, [status]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const onChange = (k: string) => {
    setRows(null);
    bulk.clear();
    setStatus(k);
    router.setParams({ status: k === "all" ? undefined : k } as any);
  };

  const doStatus = async (next: string) => {
    setStatusOpen(false);
    setBusy(true);
    try {
      const res: any = await api.post("/jobs/bulk-update", { ids: ids(), patch: { status: next } });
      report(`${plural(res?.updated_count || 0)} → ${next}`, res?.failed);
      exitSelect(); load();
    } catch (e: any) { showToast(e?.message || "Bulk update failed", "error"); }
    finally { setBusy(false); }
  };

  const doReschedule = async (date: string) => {
    setBusy(true);
    try {
      const res: any = await api.post("/jobs/bulk-update", { ids: ids(), patch: { scheduled_date: date } });
      report(`Rescheduled ${plural(res?.updated_count || 0)} to ${friendlyDate(date)}`, res?.failed);
      setReschedOpen(false); exitSelect(); load();
    } catch (e: any) { showToast(e?.message || "Bulk reschedule failed", "error"); }
    finally { setBusy(false); }
  };

  const askDelete = () => {
    const n = bulk.count;
    showConfirm({
      title: `Delete ${plural(n)}?`,
      message: "Locked jobs (active timers or completed with an invoice) will be skipped.",
      confirmLabel: `Delete ${n}`,
      confirmStyle: "destructive",
      onConfirm: async () => {
        setBusy(true);
        try {
          const res: any = await api.post("/jobs/bulk-delete", { ids: ids() });
          const gone = new Set((res?.deleted || []).map(String));
          setRows((prev) => (prev || []).filter((r) => !gone.has(String(r.id))));
          report(`${plural(res?.deleted_count || 0)} deleted`, res?.failed);
          exitSelect();
        } catch (e: any) { showToast(e?.message || "Bulk delete failed", "error"); }
        finally { setBusy(false); }
      },
    });
  };

  const onRowPress = (id: string) => (selectMode ? bulk.toggleOne(id) : router.push(`/job/${id}` as any));
  const onRowLongPress = (id: string) => { if (!selectMode) { setSelectMode(true); bulk.toggleOne(id); } };

  if (user && !["admin", "super_admin"].includes(String(user.role))) return <Redirect href="/(app)" />;

  const headerRight = selectMode ? (
    <Pressable onPress={exitSelect} style={styles.headerBtn} testID="jobs-select-cancel"><Text style={styles.headerBtnText}>Cancel</Text></Pressable>
  ) : (
    <Pressable onPress={() => setSelectMode(true)} style={styles.headerBtn} disabled={!rows?.length} testID="jobs-select-toggle">
      <Text style={[styles.headerBtnText, !rows?.length && { color: colors.muted }]}>Select</Text>
    </Pressable>
  );

  return (
    <View style={styles.root} testID="jobs-page">
      <Header title="Jobs (admin)" subtitle="Work orders by status" back right={headerRight} />
      <FilterRow options={ADMIN_JOB_STATUS_OPTIONS} value={status} onChange={onChange} testID="jobs-filter-status" />
      {selectMode && rows?.length ? (
        <Pressable style={styles.selectAll} onPress={bulk.toggleAll} testID="jobs-select-all">
          <BulkCheckbox checked={bulk.allSelected} indeterminate={bulk.indeterminate} onPress={bulk.toggleAll} />
          <Text style={styles.selectAllText}>{bulk.count ? `${bulk.count} of ${rows.length} selected` : `Select all (${rows.length})`}</Text>
        </Pressable>
      ) : null}
      {rows === null ? (
        <Loading testID="jobs-loading" />
      ) : (
        <FlatList
          testID="jobs-table"
          data={rows}
          keyExtractor={(j) => String(j.id)}
          contentContainerStyle={{ padding: spacing.lg, paddingBottom: bulk.count ? 120 : spacing["3xl"] }}
          renderItem={({ item }) => (
            <JobRow
              job={item} selectMode={selectMode} checked={bulk.selected.has(String(item.id))}
              onPress={() => onRowPress(String(item.id))} onLongPress={() => onRowLongPress(String(item.id))}
            />
          )}
          ListEmptyComponent={<Text style={styles.empty} testID="jobs-empty">No jobs match this filter.</Text>}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
        />
      )}
      {selectMode ? (
        <BulkActionBar
          count={busy ? 0 : bulk.count} onClear={bulk.clear}
          actions={[
            { key: "bulk-action-status", label: "Status", icon: "swap-vertical-outline", onPress: () => setStatusOpen(true) },
            { key: "bulk-action-reschedule", label: "Reschedule", icon: "calendar-outline", onPress: () => setReschedOpen(true) },
            { key: "bulk-action-delete", label: "Delete", icon: "trash-outline", tone: "danger", onPress: askDelete },
          ]}
        />
      ) : null}
      <JobStatusPickerSheet visible={statusOpen} count={bulk.count} onSelect={doStatus} onClose={() => setStatusOpen(false)} />
      <JobRescheduleSheet visible={reschedOpen} count={bulk.count} busy={busy} onApply={doReschedule} onClose={() => setReschedOpen(false)} />
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  row: {
    flexDirection: "row", alignItems: "center", gap: spacing.md, minHeight: 56,
    backgroundColor: colors.surface, borderRadius: radius.lg, borderWidth: 1,
    borderColor: colors.border, padding: spacing.md, marginBottom: spacing.sm,
  },
  rowChecked: { borderColor: colors.brand, backgroundColor: colors.brandTertiary },
  headerBtn: { minHeight: 44, minWidth: 64, alignItems: "center", justifyContent: "center", paddingHorizontal: spacing.sm },
  headerBtnText: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.brand },
  selectAll: { flexDirection: "row", alignItems: "center", gap: spacing.sm, minHeight: 44, paddingHorizontal: spacing.lg },
  selectAllText: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
  title: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  meta: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
  empty: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, textAlign: "center", marginTop: spacing.xl },
});
