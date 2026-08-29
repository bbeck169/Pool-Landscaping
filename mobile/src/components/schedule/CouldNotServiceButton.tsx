/**
 * Feb-2026 · Phase 1 mobile parity — "Could Not Service" modal + button.
 *
 * Web parity target: ``frontend/src/components/schedule/CouldNotServiceModal.jsx``.
 *
 * Contract:
 *   • Fetches ``GET /api/settings/job-outcome-reasons`` on mount and
 *     caches the list per component instance.
 *   • Reason picker + notes textarea (required when reason.key === "other").
 *   • Photo uploader (reuses ``FileUpload`` with purpose="job_could_not_service").
 *   • Submit only enabled when reason chosen, notes present when required,
 *     and ≥1 photo uploaded.
 *   • POSTs ``{reason_id, reason_notes, photo_file_ids}`` to
 *     ``POST /api/jobs/{jobId}/could-not-service``.
 *
 * Toast surfaces use ``Alert.alert``; success + guard-hit map mirrors OMW.
 * Role gating & terminal-status hiding live on the trigger button.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator, Alert, Modal, Pressable, ScrollView, StyleSheet, Text,
  TextInput, View,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api";
import { offlineWrite } from "@/src/services/offlineWrite";
import { colors, font, fontSize, radius, spacing } from "@/src/theme";
import { FileUpload } from "@/src/components/files/FileUpload";


const ALLOWED_ROLES = new Set(["technician", "manager", "admin", "super_admin"]);
const TERMINAL_STATUSES = new Set([
  "completed", "canceled", "cancelled", "skipped", "could_not_service",
]);
const AMBER = "#D97706";


function humanizeSmsReason(reason?: string | null): string | null {
  switch (reason) {
    case "sms_opt_in_false":  return "Customer opted out of SMS — not notified.";
    case "customer_blocked":  return "Customer blocked/demo — SMS suppressed.";
    case "no_phone":          return "No phone on file — SMS not sent.";
    case "outbound_disabled": return "Outbound SMS is disabled by config.";
    case "send_failed":       return "SMS provider rejected the send.";
    default:                  return null;
  }
}


type Reason = { id: string; key: string; label: string };

type ModalProps = {
  visible: boolean;
  jobId: string;
  onClose: () => void;
  onDone?: (resp: any) => void;
};


export function CouldNotServiceModal({ visible, jobId, onClose, onDone }: ModalProps) {
  const [reasons, setReasons] = useState<Reason[]>([]);
  const [reasonId, setReasonId] = useState("");
  const [notes, setNotes] = useState("");
  const [photoIds, setPhotoIds] = useState<string[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [loadingReasons, setLoadingReasons] = useState(false);

  // Load reasons once per open. Reset local state each time modal opens.
  useEffect(() => {
    if (!visible) return;
    setReasonId("");
    setNotes("");
    setPhotoIds([]);
    setLoadingReasons(true);
    api.get("/settings/job-outcome-reasons")
      .then((r: any) => setReasons(Array.isArray(r?.reasons) ? r.reasons : []))
      .catch(() => setReasons([]))
      .finally(() => setLoadingReasons(false));
  }, [visible]);

  const selected = reasons.find((r) => r.id === reasonId);
  const isOther = (selected?.key || "") === "other";
  const canSubmit = !!reasonId
    && photoIds.length >= 1
    && (!isOther || notes.trim().length > 0)
    && !submitting;

  const submit = useCallback(async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    try {
      const body = {
        reason_id: reasonId,
        reason_notes: notes,
        photo_file_ids: photoIds,
      };
      const { data: resp, queued } = await offlineWrite({
        op_type: "job.could_not_service",
        entity_id: jobId,
        endpoint: `/jobs/${jobId}/could-not-service`,
        method: "POST",
        payload: body,
        onlineFn: () => api.post(`/jobs/${jobId}/could-not-service`, body),
      });
      if (queued) {
        Alert.alert("Queued", "Will sync when you're back online.");
        onClose();
        return;
      }
      const sr = resp?.sms_result;
      const secondary = sr?.sent ? "Customer notified" : humanizeSmsReason(sr?.reason);
      const body = secondary
        ? `Job marked 'Could Not Service'\n\n${secondary}`
        : "Job marked 'Could Not Service'";
      Alert.alert("Marked", body);
      onDone?.(resp);
      onClose();
    } catch (e: any) {
      const msg = e?.message || "";
      if (/409/.test(msg) || /already closed|terminal/i.test(msg)) {
        Alert.alert("Job is already closed", "This job is already in a terminal state.");
      } else if (/422/.test(msg)) {
        Alert.alert("Invalid submission", msg);
      } else {
        Alert.alert("Couldn't save", msg || "Try again in a moment.");
      }
    } finally {
      setSubmitting(false);
    }
  }, [canSubmit, jobId, reasonId, notes, photoIds, onDone, onClose]);

  return (
    <Modal
      visible={visible}
      transparent
      animationType="slide"
      onRequestClose={onClose}
    >
      <Pressable
        style={styles.backdrop}
        onPress={onClose}
        testID="cns-modal-backdrop"
      />
      <View style={styles.sheet} testID="could-not-service-modal">
        <View style={styles.handle} />
        <View style={styles.header}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm }}>
            <Ionicons name="warning-outline" size={18} color={AMBER} />
            <Text style={styles.title}>Mark 'Could Not Service'</Text>
          </View>
          <Pressable onPress={onClose} hitSlop={10} testID="cns-close">
            <Ionicons name="close" size={22} color={colors.muted} />
          </Pressable>
        </View>

        <Text style={styles.helper}>
          Requires a reason and at least one photo. The customer will be
          notified via SMS.
        </Text>

        <ScrollView contentContainerStyle={{ paddingBottom: spacing.xl }}>
          <Text style={styles.label}>Reason</Text>
          {loadingReasons ? (
            <ActivityIndicator size="small" color={colors.brand} style={{ marginVertical: spacing.md }} />
          ) : (
            <View style={styles.reasonList} testID="cns-reason-list">
              {reasons.length === 0 ? (
                <Text style={styles.muted}>No reasons configured. Ask an admin to add some.</Text>
              ) : reasons.map((r) => (
                <Pressable
                  key={r.id}
                  onPress={() => setReasonId(r.id)}
                  style={[
                    styles.reasonRow,
                    reasonId === r.id && styles.reasonRowActive,
                  ]}
                  testID={`cns-reason-${r.key}`}
                >
                  <Ionicons
                    name={reasonId === r.id ? "radio-button-on" : "radio-button-off"}
                    size={18}
                    color={reasonId === r.id ? AMBER : colors.muted}
                  />
                  <Text style={styles.reasonLabel}>{r.label}</Text>
                </Pressable>
              ))}
            </View>
          )}

          <Text style={styles.label}>
            Notes{isOther ? <Text style={{ color: AMBER }}>  (required)</Text> : null}
          </Text>
          <TextInput
            value={notes}
            onChangeText={setNotes}
            placeholder={isOther ? "Describe what happened…" : "Optional context…"}
            placeholderTextColor={colors.muted}
            multiline
            numberOfLines={3}
            style={styles.notes}
            testID="cns-notes"
          />

          <Text style={styles.label}>
            Photo{photoIds.length !== 1 ? "s" : ""} · {photoIds.length}/1+
          </Text>
          <View testID="cns-photo-upload">
            <FileUpload
              purpose="job_could_not_service"
              linkedEntityType="job"
              linkedEntityId={jobId}
              accept="image/*"
              multiple
              maxFiles={6}
              onUploaded={(p: any) => {
                if (p?.id) setPhotoIds((prev) => [...prev, p.id]);
              }}
            />
          </View>
        </ScrollView>

        <View style={styles.footer}>
          <Pressable onPress={onClose} style={styles.cancelBtn} testID="cns-cancel">
            <Text style={styles.cancelLabel}>Cancel</Text>
          </Pressable>
          <Pressable
            onPress={submit}
            disabled={!canSubmit}
            style={[styles.submitBtn, !canSubmit && styles.submitBtnDisabled]}
            testID="cns-submit"
          >
            {submitting ? (
              <ActivityIndicator size="small" color="#fff" />
            ) : (
              <Text style={styles.submitLabel}>Mark Could Not Service</Text>
            )}
          </Pressable>
        </View>
      </View>
    </Modal>
  );
}


type ButtonProps = {
  jobId: string;
  jobStatus?: string | null;
  role?: string;
  variant?: "compact" | "detail";
  onDone?: (resp: any) => void;
  testID?: string;
};


export default function CouldNotServiceButton({
  jobId, jobStatus, role = "", variant = "compact", onDone, testID,
}: ButtonProps) {
  const [open, setOpen] = useState(false);

  if (!ALLOWED_ROLES.has((role || "").toLowerCase())) return null;
  if (TERMINAL_STATUSES.has((jobStatus || "").toLowerCase())) return null;

  const label = variant === "detail" ? "Could not service" : "Can't service";
  const stopAndOpen = (e: any) => {
    e?.stopPropagation?.();
    setOpen(true);
  };

  return (
    <>
      {variant === "detail" ? (
        <Pressable
          onPress={stopAndOpen}
          style={styles.detailBtn}
          testID={testID || `could-not-service-btn-${jobId}`}
        >
          <Ionicons name="warning-outline" size={16} color={AMBER} />
          <Text style={styles.detailLabel}>{label}</Text>
        </Pressable>
      ) : (
        <Pressable
          onPress={stopAndOpen}
          style={styles.compactBtn}
          testID={testID || `could-not-service-btn-${jobId}`}
          hitSlop={6}
        >
          <Ionicons name="warning-outline" size={10} color="#78350F" />
          <Text style={styles.compactLabel}>{label}</Text>
        </Pressable>
      )}
      <CouldNotServiceModal
        visible={open}
        jobId={jobId}
        onClose={() => setOpen(false)}
        onDone={onDone}
      />
    </>
  );
}


const styles = StyleSheet.create({
  backdrop: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: "rgba(15,23,42,0.5)",
  },
  sheet: {
    position: "absolute",
    left: 0, right: 0, bottom: 0,
    backgroundColor: colors.surface,
    borderTopLeftRadius: radius.xl,
    borderTopRightRadius: radius.xl,
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.sm,
    paddingBottom: spacing.lg,
    maxHeight: "85%",
  },
  handle: {
    alignSelf: "center",
    width: 40, height: 4, borderRadius: 2,
    backgroundColor: colors.border,
    marginBottom: spacing.sm,
  },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: spacing.xs,
  },
  title: {
    fontFamily: font.bold,
    fontSize: fontSize.lg,
    color: colors.onSurface,
  },
  helper: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
    marginBottom: spacing.md,
  },
  label: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.onSurface,
    marginTop: spacing.md,
    marginBottom: spacing.xs,
  },
  reasonList: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    overflow: "hidden",
  },
  reasonRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  reasonRowActive: {
    backgroundColor: "#FEF3C7",
  },
  reasonLabel: {
    fontFamily: font.medium,
    fontSize: fontSize.base,
    color: colors.onSurface,
  },
  muted: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
    padding: spacing.md,
  },
  notes: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    padding: spacing.md,
    minHeight: 72,
    textAlignVertical: "top",
    fontFamily: font.regular,
    fontSize: fontSize.base,
    color: colors.onSurface,
    backgroundColor: colors.surface,
  },
  footer: {
    flexDirection: "row",
    justifyContent: "flex-end",
    gap: spacing.sm,
    paddingTop: spacing.md,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  cancelBtn: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: radius.md,
  },
  cancelLabel: {
    fontFamily: font.semibold,
    fontSize: fontSize.base,
    color: colors.muted,
  },
  submitBtn: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: radius.md,
    backgroundColor: AMBER,
    minWidth: 180,
    alignItems: "center",
  },
  submitBtnDisabled: {
    opacity: 0.5,
  },
  submitLabel: {
    fontFamily: font.bold,
    fontSize: fontSize.base,
    color: "#fff",
  },
  compactBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: radius.sm,
    backgroundColor: "#FEF3C7",
    borderWidth: 1,
    borderColor: "#FCD34D",
    marginTop: spacing.xs,
    alignSelf: "flex-start",
  },
  compactLabel: {
    fontFamily: font.bold,
    fontSize: 10,
    color: "#78350F",
  },
  detailBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.sm,
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.lg,
    borderRadius: radius.md,
    borderWidth: 1.5,
    borderColor: "#FCD34D",
    backgroundColor: "#FEF3C7",
    marginTop: spacing.sm,
  },
  detailLabel: {
    fontFamily: font.bold,
    fontSize: fontSize.base,
    color: "#78350F",
  },
});
