// Feb-2026 · P29b — Mobile parity for the web MuteControl.jsx.
//
// Renders a single pill button; tapping opens a bottom-sheet picker
// that lazily loads GET /api/settings/muted-reasons and lets the
// operator either pick a seeded reason, type a custom one, or submit
// with no reason. Confirming issues PATCH /api/customers/{id}/mute
// (mute path) or PATCH /api/customers/{id}/unmute (unmute path).
//
// RBAC — the caller (customer detail screen) passes ``canMute`` /
// ``canUnmute`` booleans; the component returns null when gated.
// This mirrors ``frontend/src/components/customers/MuteControl.jsx``.

import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, Pressable, StyleSheet, TextInput, ScrollView,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Sheet } from "@/src/components/ui";


type Reason = { id: string; label: string; is_active?: boolean };


export type MuteControlSheetProps = {
  customer: { id: string; is_muted?: boolean; [k: string]: any };
  canMute?: boolean;
  canUnmute?: boolean;
  onChange?: (payload: any) => void;
  onError?: (msg: string) => void;
};


export default function MuteControlSheet({
  customer,
  canMute = true,
  canUnmute = true,
  onChange,
  onError,
}: MuteControlSheetProps) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [reasons, setReasons] = useState<Reason[]>([]);
  const [selectedReasonId, setSelectedReasonId] = useState<string>("");
  const [customReason, setCustomReason] = useState<string>("");

  const isMuted = Boolean(customer?.is_muted);
  const cid = customer?.id;
  const gated = isMuted ? !canUnmute : !canMute;

  // Lazy fetch — only when opening on the MUTE path.
  useEffect(() => {
    if (!open || isMuted || reasons.length > 0) return;
    api.get("/settings/muted-reasons")
      .then((res: any) => {
        const rows = Array.isArray(res?.items) ? res.items : [];
        setReasons(rows);
      })
      .catch(() => { /* silent — picker still usable via Custom */ });
  }, [open, isMuted, reasons.length]);

  const openSheet = useCallback(() => {
    if (gated || busy) return;
    setOpen(true);
  }, [gated, busy]);

  const closeSheet = useCallback(() => {
    if (busy) return;
    setOpen(false);
  }, [busy]);

  const confirm = useCallback(async () => {
    if (!cid) return;
    setBusy(true);
    try {
      const path = isMuted ? "unmute" : "mute";
      let body: Record<string, any> = {};
      if (!isMuted) {
        let reasonText = "";
        if (selectedReasonId === "__custom__") {
          reasonText = customReason.trim();
        } else if (selectedReasonId) {
          const r = reasons.find((x) => x.id === selectedReasonId);
          reasonText = r?.label || "";
        }
        if (reasonText) body = { muted_reason: reasonText.slice(0, 500) };
      }
      const res = await api.patch(`/customers/${cid}/${path}`, body);
      setOpen(false);
      setSelectedReasonId("");
      setCustomReason("");
      onChange?.(res);
    } catch (err: any) {
      onError?.(err?.message || `Failed to ${isMuted ? "unmute" : "mute"} customer`);
    } finally {
      setBusy(false);
    }
  }, [cid, isMuted, selectedReasonId, customReason, reasons, onChange, onError]);

  if (gated || !cid) return null;

  return (
    <>
      <Pressable
        onPress={openSheet}
        disabled={busy}
        testID={`mute-control-btn-${cid}`}
        style={[
          styles.pill,
          { borderColor: isMuted ? colors.brand : "#DC2626",
              opacity: busy ? 0.5 : 1 },
        ]}
      >
        <Ionicons
          name={isMuted ? "volume-high-outline" : "volume-mute-outline"}
          size={14}
          color={isMuted ? colors.brand : "#DC2626"}
        />
        <Text
          style={[
            styles.pillText,
            { color: isMuted ? colors.brand : "#DC2626" },
          ]}
        >
          {busy
            ? (isMuted ? "Unmuting…" : "Muting…")
            : (isMuted ? "Unmute" : "Mark Muted")}
        </Text>
      </Pressable>

      <Sheet
        visible={open}
        onClose={closeSheet}
        title={isMuted ? "Unmute this customer?" : "Mute this customer?"}
        testID={`mute-control-sheet-${cid}`}
      >
        {isMuted ? (
          <Text style={styles.body} testID={`mute-control-body-${cid}`}>
            They&apos;ll return to normal activity: marketing,
            autobilling, and route optimization will resume.
          </Text>
        ) : (
          <>
            <View style={styles.warning} testID={`mute-control-warning-${cid}`}>
              <Text style={styles.warningTitle}>Silent-mode warning.</Text>
              <Text style={styles.warningBody}>
                Muting stops all marketing, reactivation, autobilling,
                and lead alerts from this customer. Only an admin or
                super_admin can undo this.
              </Text>
            </View>
            <Text style={styles.pickerLabel}>Reason (optional)</Text>
            <ScrollView
              style={styles.pickerList}
              testID={`mute-control-reason-list-${cid}`}
              nestedScrollEnabled
            >
              <ReasonRow
                cid={cid}
                testID={`mute-control-reason-none-${cid}`}
                label="— No reason —"
                active={selectedReasonId === ""}
                onPress={() => setSelectedReasonId("")}
              />
              {reasons.map((r) => (
                <ReasonRow
                  key={r.id}
                  cid={cid}
                  testID={`mute-control-reason-${r.id}`}
                  label={r.label}
                  active={selectedReasonId === r.id}
                  onPress={() => setSelectedReasonId(r.id)}
                />
              ))}
              <ReasonRow
                cid={cid}
                testID={`mute-control-reason-custom-row-${cid}`}
                label="Custom…"
                active={selectedReasonId === "__custom__"}
                onPress={() => setSelectedReasonId("__custom__")}
              />
            </ScrollView>
            {selectedReasonId === "__custom__" ? (
              <TextInput
                testID={`mute-control-reason-custom-${cid}`}
                value={customReason}
                onChangeText={setCustomReason}
                placeholder="Type a reason (max 500 chars)…"
                placeholderTextColor={colors.muted}
                maxLength={500}
                style={styles.customInput}
              />
            ) : null}
          </>
        )}

        <View style={styles.footer}>
          <Pressable
            onPress={closeSheet}
            disabled={busy}
            testID={`mute-control-cancel-${cid}`}
            style={[styles.footerBtn, styles.footerCancel]}
          >
            <Text style={styles.footerCancelText}>Cancel</Text>
          </Pressable>
          <Pressable
            onPress={confirm}
            disabled={busy}
            testID={`mute-control-confirm-${cid}`}
            style={[
              styles.footerBtn,
              {
                backgroundColor: isMuted ? colors.brand : "#DC2626",
                opacity: busy ? 0.6 : 1,
              },
            ]}
          >
            <Text style={styles.footerConfirmText}>
              {busy
                ? (isMuted ? "Unmuting…" : "Muting…")
                : (isMuted ? "Yes, unmute" : "Yes, mute")}
            </Text>
          </Pressable>
        </View>
      </Sheet>
    </>
  );
}


function ReasonRow({
  cid, testID, label, active, onPress,
}: {
  cid: string;
  testID: string;
  label: string;
  active: boolean;
  onPress: () => void;
}) {
  return (
    <Pressable
      onPress={onPress}
      testID={testID}
      style={[
        styles.reasonRow,
        active ? styles.reasonRowActive : null,
      ]}
    >
      <Ionicons
        name={active ? "radio-button-on" : "radio-button-off"}
        size={16}
        color={active ? colors.brand : colors.muted}
      />
      <Text
        style={[
          styles.reasonRowText,
          active ? styles.reasonRowTextActive : null,
        ]}
      >
        {label}
      </Text>
    </Pressable>
  );
}


const styles = StyleSheet.create({
  pill: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    alignSelf: "flex-start",
    paddingHorizontal: spacing.md,
    paddingVertical: 6,
    borderWidth: 1,
    borderRadius: radius.pill,
    marginTop: spacing.sm,
  },
  pillText: { fontFamily: font.semibold, fontSize: fontSize.sm },
  body: {
    fontFamily: font.regular,
    fontSize: fontSize.base,
    color: colors.onSurface,
    marginBottom: spacing.md,
  },
  warning: {
    borderWidth: 1,
    borderColor: "#FCA5A5",
    backgroundColor: "rgba(220, 38, 38, 0.06)",
    borderRadius: radius.md,
    padding: spacing.md,
    marginBottom: spacing.md,
  },
  warningTitle: {
    fontFamily: font.bold,
    fontSize: fontSize.sm,
    color: "#7F1D1D",
    marginBottom: 4,
  },
  warningBody: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: "#7F1D1D",
  },
  pickerLabel: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.onSurfaceSecondary,
    marginBottom: spacing.xs,
  },
  pickerList: { maxHeight: 220, marginBottom: spacing.sm },
  reasonRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    paddingHorizontal: spacing.md,
    paddingVertical: 10,
    borderRadius: radius.md,
    marginBottom: 4,
    borderWidth: 1,
    borderColor: colors.border,
  },
  reasonRowActive: {
    borderColor: colors.brand,
    backgroundColor: "rgba(2, 132, 199, 0.06)",
  },
  reasonRowText: {
    fontFamily: font.regular,
    fontSize: fontSize.base,
    color: colors.onSurface,
    flex: 1,
  },
  reasonRowTextActive: { fontFamily: font.semibold, color: colors.brand },
  customInput: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: 10,
    fontFamily: font.regular,
    fontSize: fontSize.base,
    color: colors.onSurface,
    marginBottom: spacing.md,
  },
  footer: {
    flexDirection: "row",
    justifyContent: "flex-end",
    gap: spacing.sm,
    marginTop: spacing.md,
  },
  footerBtn: {
    paddingHorizontal: spacing.lg,
    paddingVertical: 10,
    borderRadius: radius.md,
  },
  footerCancel: {
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  footerCancelText: {
    fontFamily: font.semibold,
    fontSize: fontSize.base,
    color: colors.onSurfaceSecondary,
  },
  footerConfirmText: {
    fontFamily: font.semibold,
    fontSize: fontSize.base,
    color: "#fff",
  },
});
