import React, { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, TextInput, Modal, ActivityIndicator } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import { showConfirm } from "@/src/components/ConfirmModal";

const TYPES = ["sick", "vacation", "personal", "unpaid"] as const;

export default function TimeOffScreen() {
  const [bal, setBal] = useState<any>(null);
  const [rows, setRows] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [b, r] = await Promise.all([
        api.get("/time-off/balance/me"),
        api.get("/time-off/requests?scope=me"),
      ]);
      setBal(b); setRows(r);
    } finally { setLoading(false); }
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const onCancel = (id: string) => showConfirm({
    title: "Cancel request?",
    message: "This will withdraw your time-off request.",
    confirmLabel: "Withdraw",
    confirmStyle: "destructive",
    onConfirm: async () => { await api.post(`/time-off/requests/${id}/cancel`, {}); await load(); },
  });

  return (
    <View style={s.root} testID="time-off-page">
      <Header title="Time Off" back
              right={<Pressable onPress={() => setOpen(true)} testID="tof-open-request" style={s.newBtn}>
                       <Ionicons name="add" size={20} color="#fff" /></Pressable>} />

      {loading || !bal ? (
        <ActivityIndicator style={{ marginTop: 40 }} color={colors.brand} />
      ) : (
        <ScrollView contentContainerStyle={{ padding: spacing.lg }}>
          <View style={s.balCard} testID="tof-balance-card">
            <Stat label="AVAILABLE" value={`${bal.available_hours}h`} tint="brand" testid="tof-stat-available" />
            <Stat label="ACCRUED YTD" value={`${bal.accrued_hours_ytd}h`} testid="tof-stat-accrued" />
            <Stat label="USED YTD" value={`${bal.used_hours_ytd}h`} testid="tof-stat-used" />
            {bal.waiting_period_remaining_days > 0 ? (
              <Stat label="WAITING" value={`${bal.waiting_period_remaining_days}d`}
                    tint="warn" testid="tof-stat-waiting" />
            ) : (
              <Stat label="ANNUAL CAP" value={`${bal.annual_cap_hours}h`} testid="tof-stat-cap" />
            )}
          </View>

          <Text style={s.section}>Your requests</Text>
          {rows.length === 0 ? (
            <Text style={s.empty}>No requests yet.</Text>
          ) : rows.map((r) => (
            <View key={r.id} style={s.row} testID={`tof-row-${r.id}`}>
              <View style={{ flex: 1 }}>
                <Text style={s.rowTop}>{r.type.toUpperCase()} · {r.hours}h</Text>
                <Text style={s.rowSub}>{r.from_date === r.to_date ? r.from_date : `${r.from_date} → ${r.to_date}`}</Text>
                {r.reason ? <Text style={s.rowReason} numberOfLines={2}>{r.reason}</Text> : null}
              </View>
              <View style={[s.pill, pillTint(r.status)]}>
                <Text style={s.pillText}>{r.status}</Text>
              </View>
              {r.status === "pending" ? (
                <Pressable onPress={() => onCancel(r.id)} testID={`tof-cancel-${r.id}`} style={{ padding: 6 }}>
                  <Ionicons name="close-circle-outline" size={22} color={colors.error} />
                </Pressable>
              ) : null}
            </View>
          ))}
        </ScrollView>
      )}

      {open ? <RequestSheet onClose={() => setOpen(false)} onDone={() => { setOpen(false); load(); }} /> : null}
    </View>
  );
}

function Stat({ label, value, tint, testid }: any) {
  const bg = tint === "warn" ? "#FEF3C7" : tint === "brand" ? colors.brandTertiary : colors.surface;
  return (
    <View style={[s.stat, { backgroundColor: bg }]} testID={testid}>
      <Text style={s.statLabel}>{label}</Text>
      <Text style={s.statVal}>{value}</Text>
    </View>
  );
}

function pillTint(status: string) {
  if (status === "approved") return { backgroundColor: "#D1FAE5" };
  if (status === "rejected") return { backgroundColor: "#FEE2E2" };
  if (status === "cancelled") return { backgroundColor: "#E5E7EB" };
  return { backgroundColor: "#FEF3C7" };
}

function RequestSheet({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const today = new Date().toISOString().slice(0, 10);
  const [type, setType] = useState<(typeof TYPES)[number]>("sick");
  const [from, setFrom] = useState(today);
  const [to, setTo] = useState(today);
  const [hours, setHours] = useState("8");
  const [reason, setReason] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true); setErr("");
    try {
      await api.post("/time-off/requests", {
        type, from_date: from, to_date: to, hours: Number(hours), reason,
      });
      onDone();
    } catch (e: any) {
      const code = e?.response?.data?.detail?.code;
      if (code === "waiting_period") setErr(`Inside 90-day waiting period (${e.response.data.detail.remaining_days}d left).`);
      else if (code === "insufficient_balance") setErr(`Not enough balance — ${e.response.data.detail.available}h available.`);
      else setErr(code || e?.message || "Submit failed");
    } finally { setBusy(false); }
  };

  return (
    <Modal transparent animationType="slide" onRequestClose={onClose} testID="tof-modal">
      <View style={s.sheetBackdrop}>
        <View style={s.sheet}>
          <Text style={s.sheetTitle}>Request Time Off</Text>
          <Text style={s.lbl}>Type</Text>
          <View style={s.chipRow}>
            {TYPES.map((t) => (
              <Pressable key={t} onPress={() => setType(t)}
                         style={[s.chip, type === t && s.chipActive]}
                         testID={`tof-type-${t}`}>
                <Text style={[s.chipText, type === t && { color: "#fff" }]}>{t}</Text>
              </Pressable>
            ))}
          </View>
          <Text style={s.lbl}>From (YYYY-MM-DD)</Text>
          <TextInput value={from} onChangeText={setFrom} style={s.input} testID="tof-from" />
          <Text style={s.lbl}>To (YYYY-MM-DD)</Text>
          <TextInput value={to} onChangeText={setTo} style={s.input} testID="tof-to" />
          <Text style={s.lbl}>Hours</Text>
          <TextInput value={hours} onChangeText={setHours} keyboardType="numeric" style={s.input} testID="tof-hours" />
          <Text style={s.lbl}>Reason</Text>
          <TextInput value={reason} onChangeText={setReason} multiline style={[s.input, { height: 70 }]} testID="tof-reason" />

          {err ? <View style={s.errBox} testID="tof-error-banner"><Text style={s.errText}>{err}</Text></View> : null}

          <View style={{ flexDirection: "row", gap: 8, justifyContent: "flex-end", marginTop: 10 }}>
            <Pressable onPress={onClose} style={s.btnCancel} testID="tof-cancel"><Text>Cancel</Text></Pressable>
            <Pressable onPress={submit} disabled={busy} style={s.btnPrimary} testID="tof-submit">
              <Text style={{ color: "#fff", fontFamily: font.bold }}>{busy ? "Submitting…" : "Submit"}</Text>
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  newBtn: { backgroundColor: colors.brand, paddingHorizontal: 10, paddingVertical: 8, borderRadius: 999, alignItems: "center", justifyContent: "center" },
  balCard: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginBottom: spacing.lg },
  stat: { flexBasis: "48%", flexGrow: 1, borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: colors.border },
  statLabel: { fontFamily: font.semibold, fontSize: 11, color: colors.muted, letterSpacing: 1 },
  statVal: { fontFamily: font.bold, fontSize: fontSize["2xl"], color: colors.onSurface, marginTop: 4 },
  section: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface, marginBottom: 6 },
  empty: { fontFamily: font.regular, color: colors.muted, textAlign: "center", padding: spacing.xl },
  row: { flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: colors.border, marginBottom: 8 },
  rowTop: { fontFamily: font.bold, fontSize: fontSize.base, color: colors.onSurface },
  rowSub: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
  rowReason: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurfaceSecondary, marginTop: 2 },
  pill: { paddingHorizontal: 8, paddingVertical: 4, borderRadius: 999 },
  pillText: { fontFamily: font.semibold, fontSize: 11 },

  sheetBackdrop: { flex: 1, backgroundColor: "rgba(15,23,42,0.55)", justifyContent: "flex-end" },
  sheet: { backgroundColor: colors.surface, borderTopLeftRadius: 16, borderTopRightRadius: 16, padding: spacing.lg },
  sheetTitle: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface, marginBottom: 10 },
  lbl: { fontFamily: font.semibold, fontSize: 11, color: colors.muted, marginTop: 8, marginBottom: 4, letterSpacing: 1 },
  input: { borderWidth: 1, borderColor: colors.border, borderRadius: 8, padding: 10, fontFamily: font.regular, color: colors.onSurface },
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  chip: { paddingHorizontal: 12, paddingVertical: 8, borderRadius: 999, backgroundColor: colors.surfaceTertiary },
  chipActive: { backgroundColor: colors.brand },
  chipText: { fontFamily: font.semibold, fontSize: 13, color: colors.onSurface },
  errBox: { backgroundColor: "#FEE2E2", borderColor: "#FECACA", borderWidth: 1, borderRadius: 8, padding: 10, marginTop: 10 },
  errText: { color: "#991B1B", fontFamily: font.regular, fontSize: 13 },
  btnCancel: { paddingHorizontal: 14, paddingVertical: 10, borderRadius: 8, backgroundColor: colors.surfaceTertiary },
  btnPrimary: { paddingHorizontal: 14, paddingVertical: 10, borderRadius: 8, backgroundColor: colors.brand },
});
