/**
 * AutomationsMuteSection — admin-only toggle for `automations_muted`.
 *
 * Distinct from the existing MuteControlSheet which handles `is_muted`
 * (auto-scheduling gate). This controls the comms fan-out mute only.
 *
 * API: PATCH /api/customers/{cid}/mute-automations
 *   Body: { muted: bool, reason?: string, channel?: "all" }
 */
import React, { useState } from "react";
import {
  View, Text, Pressable, Switch, StyleSheet, TextInput, Modal,
  KeyboardAvoidingView, Platform, Alert,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/api";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";

type Props = {
  customer: any;
  isAdmin: boolean;
  onUpdated: (patch: any) => void;
};

export default function AutomationsMuteSection({ customer, isAdmin, onUpdated }: Props) {
  const isMuted = Boolean(customer?.automations_muted);
  const [mutePromptOpen, setMutePromptOpen] = useState(false);
  const [muteReason, setMuteReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [infoOpen, setInfoOpen] = useState(false);

  const cid = customer?.id;

  const doToggleMute = async (nextMuted: boolean, reason?: string) => {
    if (!cid) return;
    setBusy(true);
    try {
      const body: any = { muted: nextMuted, channel: "all" };
      if (nextMuted && reason) body.reason = reason;
      const res = await api.patch(`/customers/${cid}/mute-automations`, body);
      setMutePromptOpen(false);
      setMuteReason("");
      if (nextMuted) {
        onUpdated({
          automations_muted: true,
          automations_muted_reason: res?.automations_muted_reason ?? reason ?? null,
          automations_muted_at: res?.automations_muted_at ?? new Date().toISOString(),
          automations_muted_by: res?.automations_muted_by ?? null,
          automations_muted_channel: res?.automations_muted_channel ?? "all",
        });
      } else {
        onUpdated({
          automations_muted: false,
          automations_muted_reason: null,
          automations_muted_at: null,
          automations_muted_by: null,
          automations_muted_channel: "all",
        });
      }
    } catch (e: any) {
      Alert.alert("Update failed", e?.message || "Please try again.");
    } finally {
      setBusy(false);
    }
  };

  const handleToggle = (val: boolean) => {
    if (val) {
      setMutePromptOpen(true);
    } else {
      Alert.alert("Unmute automations?", "Automated emails & SMS will resume for this customer.", [
        { text: "Cancel", style: "cancel" },
        { text: "Unmute", onPress: () => doToggleMute(false) },
      ]);
    }
  };

  return (
    <View testID="automations-mute-section">
      {/* Banner when muted */}
      {isMuted && (
        <Pressable
          style={s.banner}
          onLongPress={() => setInfoOpen(true)}
          onPress={() => setInfoOpen(true)}
          testID="customer-automations-muted-banner"
        >
          <View style={s.badge} testID="customer-automations-muted-badge">
            <Text style={s.badgeText}>AUTOMATIONS MUTED</Text>
          </View>
          {customer?.automations_muted_reason ? (
            <Text style={s.bannerReason} numberOfLines={1}>
              · {customer.automations_muted_reason}
            </Text>
          ) : null}
          <Ionicons name="information-circle-outline" size={16} color="#78350F" style={{ marginLeft: "auto" }} />
        </Pressable>
      )}

      {/* Admin-only toggle */}
      {isAdmin && (
        <View style={s.toggleRow} testID="automations-mute-toggle-row">
          <View style={{ flex: 1 }}>
            <Text style={s.toggleLabel}>Mute all automated emails & SMS</Text>
            <Text style={s.toggleHint}>Stops automated comms only. Manual sends still work.</Text>
          </View>
          <Switch
            value={isMuted}
            onValueChange={handleToggle}
            disabled={busy}
            trackColor={{ false: "#9CA3AF", true: "#B45309" }}
            thumbColor="#fff"
            ios_backgroundColor="#9CA3AF"
            style={{ transform: [{ scaleX: 0.85 }, { scaleY: 0.85 }] }}
            testID="customer-mute-automations-toggle"
          />
        </View>
      )}

      {/* Reason prompt modal (mute ON) */}
      <Modal visible={mutePromptOpen} transparent animationType="fade" testID="automations-mute-reason-modal">
        <KeyboardAvoidingView style={s.overlay} behavior={Platform.OS === "ios" ? "padding" : "height"}>
          <View style={s.promptCard}>
            <Text style={s.promptTitle}>Mute automations</Text>
            <Text style={s.promptBody}>
              All automated emails & SMS will stop for this customer. Manual sends still work.
            </Text>
            <Text style={s.promptLabel}>Reason (optional, visible in audit log)</Text>
            <TextInput
              style={s.reasonInput}
              value={muteReason}
              onChangeText={setMuteReason}
              placeholder="e.g. Customer requested via phone"
              placeholderTextColor={colors.muted}
              maxLength={500}
              testID="customer-mute-reason-input"
            />
            <View style={s.promptBtns}>
              <Pressable
                style={s.cancelBtn}
                onPress={() => { setMutePromptOpen(false); setMuteReason(""); }}
                disabled={busy}
                testID="customer-mute-cancel-btn"
              >
                <Text style={s.cancelBtnText}>Cancel</Text>
              </Pressable>
              <Pressable
                style={[s.confirmBtn, busy && { opacity: 0.5 }]}
                onPress={() => doToggleMute(true, muteReason.trim() || undefined)}
                disabled={busy}
                testID="customer-mute-confirm-btn"
              >
                <Text style={s.confirmBtnText}>{busy ? "Muting…" : "Mute"}</Text>
              </Pressable>
            </View>
          </View>
        </KeyboardAvoidingView>
      </Modal>

      {/* Info modal (long-press on banner) */}
      <Modal visible={infoOpen} transparent animationType="fade" testID="automations-mute-info-modal">
        <Pressable style={s.overlay} onPress={() => setInfoOpen(false)}>
          <View style={s.infoCard}>
            <Text style={s.infoTitle}>Automations Mute Details</Text>
            <InfoRow label="Status" value="Muted" />
            <InfoRow label="Reason" value={customer?.automations_muted_reason || "—"} />
            <InfoRow label="Muted at" value={customer?.automations_muted_at ? new Date(customer.automations_muted_at).toLocaleString() : "—"} />
            <InfoRow label="Muted by" value={customer?.automations_muted_by || "—"} />
            <InfoRow label="Channel" value={customer?.automations_muted_channel || "all"} />
            <Pressable style={s.infoDismiss} onPress={() => setInfoOpen(false)} testID="automations-mute-info-close">
              <Text style={s.infoDismissText}>Close</Text>
            </Pressable>
          </View>
        </Pressable>
      </Modal>
    </View>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <View style={s.infoRow}>
      <Text style={s.infoLabel}>{label}</Text>
      <Text style={s.infoValue}>{value}</Text>
    </View>
  );
}

const s = StyleSheet.create({
  banner: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: "#FEF3C7",
    borderColor: "#FCD34D",
    borderWidth: 1,
    borderRadius: radius.md,
    padding: spacing.md,
    marginBottom: spacing.md,
    gap: spacing.sm,
  },
  badge: {
    backgroundColor: "#B45309",
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: radius.sm,
  },
  badgeText: {
    fontFamily: font.bold,
    fontSize: 10,
    color: "#fff",
    letterSpacing: 0.5,
    textTransform: "uppercase",
  },
  bannerReason: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: "#78350F",
    flex: 1,
  },
  toggleRow: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
    marginBottom: spacing.md,
  },
  toggleLabel: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.onSurface,
  },
  toggleHint: {
    fontFamily: font.regular,
    fontSize: 11,
    color: colors.muted,
    marginTop: 2,
  },
  overlay: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.5)",
    justifyContent: "center",
    padding: 24,
  },
  promptCard: {
    backgroundColor: "#fff",
    borderRadius: radius.lg,
    padding: spacing.xl,
  },
  promptTitle: {
    fontFamily: font.bold,
    fontSize: fontSize.lg,
    color: colors.onSurface,
    marginBottom: spacing.sm,
  },
  promptBody: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.onSurfaceSecondary,
    marginBottom: spacing.md,
  },
  promptLabel: {
    fontFamily: font.medium,
    fontSize: fontSize.sm,
    color: colors.muted,
    marginBottom: spacing.xs,
  },
  reasonInput: {
    backgroundColor: colors.surfaceSecondary,
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
  promptBtns: {
    flexDirection: "row",
    justifyContent: "flex-end",
    gap: spacing.sm,
  },
  cancelBtn: {
    paddingHorizontal: 16,
    paddingVertical: 10,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
  },
  cancelBtnText: {
    fontFamily: font.medium,
    fontSize: fontSize.sm,
    color: colors.onSurface,
  },
  confirmBtn: {
    paddingHorizontal: 16,
    paddingVertical: 10,
    borderRadius: radius.md,
    backgroundColor: "#B45309",
  },
  confirmBtnText: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: "#fff",
  },
  infoCard: {
    backgroundColor: "#fff",
    borderRadius: radius.lg,
    padding: spacing.xl,
  },
  infoTitle: {
    fontFamily: font.bold,
    fontSize: fontSize.lg,
    color: colors.onSurface,
    marginBottom: spacing.md,
  },
  infoRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    paddingVertical: 8,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  infoLabel: {
    fontFamily: font.medium,
    fontSize: fontSize.sm,
    color: colors.muted,
  },
  infoValue: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.onSurface,
    maxWidth: "60%",
    textAlign: "right",
  },
  infoDismiss: {
    marginTop: spacing.md,
    alignSelf: "center",
    paddingHorizontal: 20,
    paddingVertical: 8,
    borderRadius: radius.md,
    backgroundColor: colors.surfaceTertiary,
  },
  infoDismissText: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.onSurface,
  },
});
