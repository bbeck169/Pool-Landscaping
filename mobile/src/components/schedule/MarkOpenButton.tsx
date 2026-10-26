/**
 * M3b · Mark as Open on MISSED job cards (web Ticket X `MarkOpenAction` parity).
 * Visible only when job.status === "missed". Optimistic flip to "scheduled" →
 * POST /jobs/{id}/mark-open → reconcile with the server row + success toast with
 * Undo (5 s). Undo → PUT /jobs/{id} {status:"missed", missed_at}. Any error
 * (409 / 403 / 404 / network) rolls back to the original job + error toast.
 */
import React, { useCallback, useState } from "react";
import { Pressable, Text, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api";
import { useToast } from "@/src/components/ToastProvider";
import { font } from "@/src/theme";

export const UNDO_WINDOW_MS = 5000;
export const isMissedJob = (job: any) => String(job?.status || "").toLowerCase() === "missed";

export function formatMarkOpenError(err: any): string {
  const d = err?.data?.detail ?? err?.detail;
  if (typeof d === "string" && d) return d;
  if (d && typeof d === "object" && typeof d.detail === "string" && d.detail) return d.detail;
  if (err?.message) return err.message;
  return "Failed to mark job open";
}

type Props = { job: any; onPatch: (j: any) => void; size?: "sm" | "xs" };

export default function MarkOpenButton({ job, onPatch, size = "sm" }: Props) {
  const { showToast } = useToast();
  const [busy, setBusy] = useState(false);

  const undo = useCallback(async (original: any) => {
    onPatch({ ...original });
    try {
      await api.put(`/jobs/${encodeURIComponent(original.id)}`, { status: "missed", missed_at: original.missed_at || null });
      showToast("Mark-open undone");
    } catch (err) {
      showToast(`Undo failed: ${formatMarkOpenError(err)}`, "error");
      try { const fresh = await api.get(`/jobs/${encodeURIComponent(original.id)}`); if (fresh?.id) onPatch(fresh); } catch { /* best effort */ }
    }
  }, [onPatch, showToast]);

  const press = useCallback(async () => {
    if (busy || !isMissedJob(job)) return;
    setBusy(true);
    const original = { ...job };
    onPatch({ ...job, status: "scheduled" });
    try {
      const updated = await api.post(`/jobs/${encodeURIComponent(job.id)}/mark-open`, {});
      if (updated?.id) onPatch(updated);
      showToast(`Marked as Open · ${job.customer_name || "Job"}`, "success", UNDO_WINDOW_MS, { label: "Undo", onPress: () => { undo(original); } });
    } catch (err) {
      onPatch(original);
      showToast(formatMarkOpenError(err), "error");
    } finally {
      setBusy(false);
    }
  }, [busy, job, onPatch, showToast, undo]);

  if (!isMissedJob(job)) return null;
  const xs = size === "xs";
  return (
    <Pressable
      onPress={press}
      disabled={busy}
      hitSlop={xs ? 6 : 4}
      style={[st.btn, xs ? st.btnXs : st.btnSm, busy && { opacity: 0.6 }]}
      accessibilityRole="button"
      accessibilityLabel="Mark job as open"
      testID={`mark-open-btn-${job.id}`}
    >
      <Ionicons name="checkmark-circle-outline" size={xs ? 11 : 14} color="#FFFFFF" />
      <Text style={[st.text, { fontSize: xs ? 10 : 12 }]}>Mark as Open</Text>
    </Pressable>
  );
}

const st = StyleSheet.create({
  btn: { flexDirection: "row", alignItems: "center", alignSelf: "flex-start", gap: 4, borderRadius: 6, backgroundColor: "#059669", borderWidth: 1, borderColor: "#047857" },
  btnSm: { minHeight: 36, paddingHorizontal: 10 },
  btnXs: { minHeight: 24, paddingHorizontal: 6, marginTop: 4 },
  text: { fontFamily: font.semibold, color: "#FFFFFF" },
});
