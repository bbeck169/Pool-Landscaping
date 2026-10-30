import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, FlatList, RefreshControl, Pressable, ScrollView, Alert, Platform, Modal, KeyboardAvoidingView } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Loading, EmptyState } from "@/src/components/ui";
import { Header, IconButton } from "@/src/components/widgets";
import { exportCsv, toCsvRow } from "@/src/utils/exportCsv";
import { useToast } from "@/src/components/ToastProvider";
import { showConfirm } from "@/src/components/ConfirmModal";
import AppTextInput from "@/src/components/ui/AppTextInput";

const DELETE_TITLE = "Delete timecard?";
const DELETE_MESSAGE = "This cannot be undone. The row will be removed permanently.";
const errMsg = (e: any): string => {
  const d = e?.detail;
  if (typeof d === "string") return d;
  if (d && typeof d === "object" && typeof d.msg === "string") return d.msg;
  if (Array.isArray(d) && d[0]?.msg) return String(d[0].msg);
  return e?.message || "Delete failed";
};

const fmtTime = (iso?: string | null) => {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }); } catch { return "—"; }
};
const fmtDate = (d?: string) => {
  if (!d) return "";
  try { return new Date(d + "T00:00:00").toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" }); } catch { return d; }
};
const gps = (lat?: number | null, lng?: number | null) => (lat != null && lng != null ? `${lat.toFixed(5)}, ${lng.toFixed(5)}` : "no GPS");

export default function Timesheets() {
  const [rows, setRows] = useState<any[]>([]);
  const [totalHours, setTotalHours] = useState(0);
  const [techs, setTechs] = useState<any[]>([]);
  const [techId, setTechId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const { user } = useAuth();
  const isAdmin = user?.role === "admin" || user?.role === "super_admin";
  const { showToast } = useToast();
  const [reasonFor, setReasonFor] = useState<any | null>(null);

  const load = useCallback(async (tid: string | null) => {
    try {
      const [rep, ts] = await Promise.all([
        api.get(`/attendance/report${tid ? `?technician_id=${tid}` : ""}`),
        techs.length ? Promise.resolve(techs) : api.get("/technicians"),
      ]);
      setRows(rep.rows || []);
      setTotalHours(rep.total_hours || 0);
      if (!techs.length) setTechs(ts);
    } catch {
      setRows([]);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [techs]);

  useFocusEffect(useCallback(() => { load(techId); }, [load, techId]));

  const pickTech = (id: string | null) => { setTechId(id); setLoading(true); load(id); };

  // Ticket 2 · step 1 — destructive confirm (native Alert; web → showConfirm,
  // since react-native-web Alert.alert is a no-op).
  const askDelete = (row: any) => {
    if (Platform.OS === "web") {
      showConfirm({ title: DELETE_TITLE, message: DELETE_MESSAGE, confirmLabel: "Delete", confirmStyle: "destructive", onConfirm: () => setReasonFor(row) });
      return;
    }
    Alert.alert(DELETE_TITLE, DELETE_MESSAGE, [
      { text: "Cancel", style: "cancel" },
      { text: "Delete", style: "destructive", onPress: () => setReasonFor(row) },
    ]);
  };

  // Ticket 2 · step 2 — hard delete (BE f16ffc940). Throws so the reason
  // modal can keep itself open with the error.
  const doDelete = async (row: any, reason: string) => {
    try {
      await api.del(`/attendance/timesheets/${row.id}?reason=${encodeURIComponent(reason)}`);
    } catch (e: any) {
      const msg = errMsg(e);
      showToast(msg, "error");
      throw new Error(msg);
    }
    setRows((prev) => prev.filter((r) => r.id !== row.id));
    setTotalHours((h) => Math.max(0, Math.round((h - (Number(row.hours) || 0)) * 100) / 100));
    setReasonFor(null);
    showToast("Timecard deleted", "success");
    load(techId);
  };

  const doExport = () => {
    const header = toCsvRow(["Date", "Technician", "Clock In", "Clock In GPS", "Clock Out", "Clock Out GPS", "Hours"]);
    const body = rows.map((r) => toCsvRow([
      r.date, r.technician_name, fmtTime(r.clock_in_at), gps(r.clock_in_lat, r.clock_in_lng),
      fmtTime(r.clock_out_at), gps(r.clock_out_lat, r.clock_out_lng), r.hours ?? 0,
    ]));
    exportCsv(`timesheets_${new Date().toISOString().slice(0, 10)}.csv`, [header, ...body].join("\n"));
  };

  if (loading) return <Loading testID="timesheets-loading" />;

  return (
    <View style={styles.root}>
      <Header title="Timesheets" back subtitle="Daily clock in/out + GPS" right={<IconButton icon="download-outline" onPress={doExport} testID="timesheets-export" />} />

      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chipRow}>
        <Chip label="All techs" active={!techId} onPress={() => pickTech(null)} testID="timesheets-tech-all" />
        {techs.map((t) => (
          <Chip key={t.id} label={t.name} active={techId === t.id} onPress={() => pickTech(t.id)} testID={`timesheets-tech-${t.id}`} />
        ))}
      </ScrollView>

      <View style={styles.summary}>
        <Text style={styles.sumVal}>{totalHours} h</Text>
        <Text style={styles.sumLabel}>{rows.length} day{rows.length === 1 ? "" : "s"} logged</Text>
      </View>

      {rows.length === 0 ? (
        <EmptyState icon="time-outline" title="No timesheets yet" subtitle="Entries appear when technicians clock in and out." testID="timesheets-empty" />
      ) : (
        <FlatList
          testID="timesheets-list"
          data={rows}
          keyExtractor={(r) => r.id}
          contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(techId); }} />}
          renderItem={({ item }) => (
            <View style={styles.card} testID={`timesheet-${item.id}`}>
              <View style={styles.cardHead}>
                <Text style={styles.cardDate}>{fmtDate(item.date)}</Text>
                <View style={styles.cardHeadRight}>
                  <Text style={styles.cardHours}>{item.hours ?? 0} h</Text>
                  {isAdmin ? (
                    <Pressable
                      style={styles.trashBtn} onPress={() => askDelete(item)} hitSlop={6}
                      accessibilityRole="button" accessibilityLabel="Delete timecard" testID={`timesheet-delete-${item.id}`}
                    >
                      <Ionicons name="trash-outline" size={18} color={colors.danger || "#DC2626"} />
                    </Pressable>
                  ) : null}
                </View>
              </View>
              <Text style={styles.cardTech}>{item.technician_name}</Text>
              <View style={styles.punchRow}>
                <Ionicons name="log-in-outline" size={14} color="#16A34A" />
                <Text style={styles.punchText}>In {fmtTime(item.clock_in_at)} · {gps(item.clock_in_lat, item.clock_in_lng)}</Text>
              </View>
              <View style={styles.punchRow}>
                <Ionicons name="log-out-outline" size={14} color="#0EA5E9" />
                <Text style={styles.punchText}>Out {fmtTime(item.clock_out_at)} · {gps(item.clock_out_lat, item.clock_out_lng)}</Text>
              </View>
            </View>
          )}
        />
      )}
      {reasonFor ? <DeleteReasonModal row={reasonFor} onCancel={() => setReasonFor(null)} onSubmit={(r) => doDelete(reasonFor, r)} /> : null}
    </View>
  );
}

function DeleteReasonModal({ row, onCancel, onSubmit }: { row: any; onCancel: () => void; onSubmit: (reason: string) => Promise<void> }) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ok = reason.trim().length >= 3 && !busy;
  const submit = async () => {
    if (!ok) return;
    setBusy(true); setError(null);
    try { await onSubmit(reason.trim()); } catch (e: any) { setError(e?.message || "Delete failed"); setBusy(false); }
  };
  return (
    <Modal visible transparent animationType="fade" onRequestClose={onCancel}>
      <KeyboardAvoidingView style={styles.overlay} behavior={Platform.OS === "ios" ? "padding" : "height"}>
        <View style={styles.modalCard} testID="timesheet-delete-reason-modal">
          <Text style={styles.modalTitle}>Reason for deleting</Text>
          <Text style={styles.modalSub}>{`${fmtDate(row.date)} · ${row.technician_name || ""}`}</Text>
          <AppTextInput
            style={styles.modalInput} value={reason} onChangeText={(v: string) => { setReason(v); setError(null); }}
            placeholder="At least 3 characters" placeholderTextColor={colors.muted} autoFocus maxLength={500}
            testID="timesheet-delete-reason-input"
          />
          {error ? <Text style={styles.modalError} testID="timesheet-delete-reason-error">{error}</Text> : null}
          <View style={styles.modalBtns}>
            <Pressable style={styles.modalGhost} onPress={onCancel} testID="timesheet-delete-reason-cancel">
              <Text style={styles.modalGhostText}>Cancel</Text>
            </Pressable>
            <Pressable
              style={[styles.modalDanger, !ok && { opacity: 0.5 }]} onPress={submit} disabled={!ok}
              accessibilityState={{ disabled: !ok }} testID="timesheet-delete-reason-submit"
            >
              <Text style={styles.modalDangerText}>{busy ? "Deleting…" : "Delete"}</Text>
            </Pressable>
          </View>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

function Chip({ label, active, onPress, testID }: any) {
  return (
    <Pressable style={[styles.chip, active && styles.chipActive]} onPress={onPress} testID={testID}>
      <Text style={[styles.chipText, active && { color: "#fff" }]} numberOfLines={1}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  chipRow: { paddingHorizontal: spacing.lg, paddingVertical: spacing.md, gap: spacing.sm },
  chip: { paddingHorizontal: spacing.md, height: 36, borderRadius: radius.pill, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, marginRight: spacing.sm },
  chipActive: { backgroundColor: colors.brand, borderColor: colors.brand },
  chipText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
  summary: { backgroundColor: colors.surface, marginHorizontal: spacing.lg, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, padding: spacing.md, alignItems: "center" },
  sumVal: { fontFamily: font.bold, fontSize: fontSize["2xl"], color: colors.brand },
  sumLabel: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted },
  card: { backgroundColor: colors.surface, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, padding: spacing.md, marginBottom: spacing.sm, gap: 4 },
  cardHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  cardDate: { fontFamily: font.bold, fontSize: fontSize.base, color: colors.onSurface },
  cardHours: { fontFamily: font.bold, fontSize: fontSize.base, color: colors.brand },
  cardHeadRight: { flexDirection: "row", alignItems: "center", gap: spacing.xs },
  trashBtn: { width: 44, height: 44, alignItems: "center", justifyContent: "center", marginRight: -spacing.sm, marginVertical: -spacing.sm },
  overlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.5)", justifyContent: "center", padding: spacing.lg },
  modalCard: { backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.xl },
  modalTitle: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  modalSub: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted, marginTop: 2, marginBottom: spacing.md },
  modalInput: { backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, padding: spacing.md, fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface },
  modalError: { fontFamily: font.medium, fontSize: fontSize.sm, color: "#DC2626", marginTop: spacing.sm },
  modalBtns: { flexDirection: "row", justifyContent: "flex-end", gap: spacing.sm, marginTop: spacing.lg },
  modalGhost: { paddingHorizontal: 16, minHeight: 44, justifyContent: "center", borderRadius: radius.md, borderWidth: 1, borderColor: colors.border },
  modalGhostText: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurface },
  modalDanger: { paddingHorizontal: 16, minHeight: 44, justifyContent: "center", borderRadius: radius.md, backgroundColor: "#DC2626" },
  modalDangerText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: "#fff" },
  cardTech: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
  punchRow: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: 2 },
  punchText: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
});
