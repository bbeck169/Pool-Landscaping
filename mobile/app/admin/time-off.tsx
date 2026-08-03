import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, Modal, TextInput } from "react-native";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";

export default function AdminTimeOffScreen() {
  const [rows, setRows] = useState<any[]>([]);
  const [balances, setBalances] = useState<any[]>([]);
  const [policy, setPolicy] = useState<any>(null);
  const [reject, setReject] = useState<any>(null);
  const [notes, setNotes] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [r, b, p] = await Promise.all([
        api.get("/time-off/requests?scope=all&status=pending"),
        api.get("/time-off/balances/all"),
        api.get("/time-off/policy"),
      ]);
      setRows(r); setBalances(b); setPolicy(p);
    } finally { setLoading(false); }
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const approve = async (id: string) => {
    await api.post(`/time-off/requests/${id}/approve`, { decision_notes: "" });
    setRows((prev) => prev.filter((r) => r.id !== id));
  };
  const doReject = async () => {
    if (!reject) return;
    await api.post(`/time-off/requests/${reject.id}/reject`, { decision_notes: notes });
    setRows((prev) => prev.filter((r) => r.id !== reject.id));
    setReject(null); setNotes("");
  };

  const savePolicy = async () => {
    const p = await api.put("/time-off/policy", policy);
    setPolicy(p);
  };

  return (
    <View style={s.root} testID="admin-time-off-page">
      <Header title="Time Off Approvals" back />
      {loading ? <ActivityIndicator style={{ marginTop: 40 }} color={colors.brand} /> : (
        <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: 40 }}>
          <Text style={s.h2}>Pending ({rows.length})</Text>
          {rows.length === 0 ? (
            <Text style={s.empty}>Nothing to review.</Text>
          ) : rows.map((r) => {
            const emp = balances.find((b: any) => b.user_id === r.user_id);
            return (
              <View key={r.id} style={s.row} testID={`admin-tof-row-${r.id}`}>
                <View style={{ flex: 1 }}>
                  <Text style={s.rowTop}>{emp?.user_name || "—"}</Text>
                  <Text style={s.rowSub}>{r.type.toUpperCase()} · {r.hours}h · {r.from_date === r.to_date ? r.from_date : `${r.from_date} → ${r.to_date}`}</Text>
                  {r.reason ? <Text style={s.rowSub} numberOfLines={2}>{r.reason}</Text> : null}
                </View>
                <Pressable style={s.approveBtn} onPress={() => approve(r.id)} testID={`admin-tof-approve-${r.id}`}>
                  <Text style={s.approveText}>Approve</Text>
                </Pressable>
                <Pressable style={s.rejectBtn} onPress={() => { setReject(r); setNotes(""); }} testID={`admin-tof-reject-${r.id}`}>
                  <Text style={s.rejectText}>Reject</Text>
                </Pressable>
              </View>
            );
          })}

          <Text style={[s.h2, { marginTop: spacing.lg }]}>Employee balances</Text>
          {balances.map((b: any) => (
            <View key={b.user_id} style={s.balRow} testID={`admin-tof-bal-${b.user_id}`}>
              <Text style={s.balName}>{b.user_name}</Text>
              <Text style={s.balNum}>{b.available_hours}h avail · {b.accrued_hours_ytd}h accrued · {b.used_hours_ytd}h used</Text>
            </View>
          ))}

          {policy ? (
            <View style={s.policyCard} testID="admin-tof-policy">
              <Text style={s.h2}>Policy</Text>
              <PolicyField label="Accrue" value={policy.accrual_numerator}
                           set={(v: number) => setPolicy({ ...policy, accrual_numerator: v })} testid="policy-num" />
              <PolicyField label="per hours worked" value={policy.accrual_denominator}
                           set={(v: number) => setPolicy({ ...policy, accrual_denominator: v })} testid="policy-den" />
              <PolicyField label="Annual cap (hrs)" value={policy.annual_cap_hours}
                           set={(v: number) => setPolicy({ ...policy, annual_cap_hours: v })} testid="policy-cap" />
              <PolicyField label="Waiting period (days)" value={policy.waiting_period_days}
                           set={(v: number) => setPolicy({ ...policy, waiting_period_days: v })} testid="policy-wait" />
              <Pressable style={s.saveBtn} onPress={savePolicy} testID="policy-save">
                <Text style={{ color: "#fff", fontFamily: font.bold }}>Save policy</Text>
              </Pressable>
            </View>
          ) : null}
        </ScrollView>
      )}

      {reject ? (
        <Modal transparent animationType="fade" onRequestClose={() => setReject(null)} testID="admin-tof-reject-modal">
          <View style={s.modalBackdrop}>
            <View style={s.modalCard}>
              <Text style={s.h2}>Reject request?</Text>
              <TextInput multiline value={notes} onChangeText={setNotes}
                         placeholder="Notes (optional)"
                         style={s.notesInput}
                         testID="admin-tof-reject-notes" />
              <View style={{ flexDirection: "row", gap: 8, justifyContent: "flex-end" }}>
                <Pressable onPress={() => setReject(null)} style={s.btnCancel} testID="admin-tof-reject-cancel"><Text>Cancel</Text></Pressable>
                <Pressable onPress={doReject} style={s.rejectBtn} testID="admin-tof-reject-confirm"><Text style={s.rejectText}>Reject</Text></Pressable>
              </View>
            </View>
          </View>
        </Modal>
      ) : null}
    </View>
  );
}

function PolicyField({ label, value, set, testid }: any) {
  return (
    <View style={{ marginBottom: 8 }}>
      <Text style={{ fontFamily: font.semibold, fontSize: 11, color: colors.muted, letterSpacing: 1 }}>{label.toUpperCase()}</Text>
      <TextInput value={String(value)} keyboardType="numeric"
                 onChangeText={(t) => set(Number(t) || 0)}
                 style={{ borderWidth: 1, borderColor: colors.border, borderRadius: 8, padding: 8, marginTop: 4, fontFamily: font.regular }}
                 testID={testid} />
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  h2: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface, marginBottom: 8 },
  empty: { fontFamily: font.regular, color: colors.muted, padding: spacing.lg, textAlign: "center" },
  row: { flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: colors.border, marginBottom: 8 },
  rowTop: { fontFamily: font.bold, fontSize: fontSize.base, color: colors.onSurface },
  rowSub: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
  approveBtn: { backgroundColor: "#10B981", paddingHorizontal: 10, paddingVertical: 6, borderRadius: 6 },
  approveText: { color: "#fff", fontFamily: font.bold, fontSize: 12 },
  rejectBtn: { backgroundColor: colors.error, paddingHorizontal: 10, paddingVertical: 6, borderRadius: 6 },
  rejectText: { color: "#fff", fontFamily: font.bold, fontSize: 12 },
  balRow: { flexDirection: "row", justifyContent: "space-between", padding: 10, borderBottomWidth: 1, borderBottomColor: colors.border },
  balName: { fontFamily: font.semibold, color: colors.onSurface },
  balNum: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  policyCard: { marginTop: spacing.lg, backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.md, borderWidth: 1, borderColor: colors.border },
  saveBtn: { backgroundColor: colors.brand, paddingHorizontal: 14, paddingVertical: 10, borderRadius: 8, alignItems: "center", marginTop: 8 },
  modalBackdrop: { flex: 1, backgroundColor: "rgba(15,23,42,0.55)", alignItems: "center", justifyContent: "center", padding: 16 },
  modalCard: { backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.lg, width: "100%", maxWidth: 400 },
  notesInput: { borderWidth: 1, borderColor: colors.border, borderRadius: 8, padding: 10, minHeight: 70, marginVertical: 10 },
  btnCancel: { paddingHorizontal: 14, paddingVertical: 8, borderRadius: 8, backgroundColor: colors.surfaceTertiary },
});
