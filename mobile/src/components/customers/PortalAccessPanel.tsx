/**
 * Portal Access Panel — mobile parity (Dispatch B, Feature 3).
 *
 * Admin-only panel on the Customer Detail screen showing portal status,
 * action buttons, temp password display, and activity feed.
 *
 * Endpoints:
 *   GET  /customers/{id}/portal-status
 *   GET  /customers/{id}/portal-history?limit=25
 *   POST /customers/{id}/portal-invite
 *   POST /customers/{id}/portal-reset      (optional { password } body)
 *   POST /customers/{id}/portal-reset-link
 *   POST /customers/{id}/portal-reset-link-copy
 *   POST /customers/{id}/portal-revoke
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ActivityIndicator,
  Alert,
  Modal,
  Platform,
  KeyboardAvoidingView } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import * as Clipboard from "expo-clipboard";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { useToast } from "@/src/components/ToastProvider";
import { mapApiError } from "@/src/utils/mapApiError";
import { viewAsCustomer as runViewAsCustomer } from "@/src/lib/portalViewAsCustomer";
import AppTextInput from "@/src/components/ui/AppTextInput";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface PortalStatus {
  has_login?: boolean;
  active?: boolean;
  email?: string;
  last_portal_login_at?: string | null;
  last_portal_login_ip?: string | null;
}

interface HistoryEvent {
  id: string;
  event: string;
  actor_email?: string;
  ip_address?: string;
  created_at?: string;
}

interface Props {
  customerId: string;
  customerEmail?: string;
  customerName?: string;
  hasLogin?: boolean;
  userRole?: string;
  /** Called after any mutation so the parent can reload the customer. */
  onRefresh: () => void;
}

/* ------------------------------------------------------------------ */
/*  Constants                                                          */
/* ------------------------------------------------------------------ */

const EVENT_LABELS: Record<string, string> = {
  portal_login: "Customer signed in",
  portal_reset: "Admin reset password",
  portal_revoke: "Admin revoked access",
  impersonation_started: "Admin viewed as customer",
  impersonation_ended: "Admin ended impersonation",
  admin_password_reset_triggered: "Admin sent reset link",
  admin_password_reset_copied: "Admin copied reset link",
  portal_invite_sent: "Portal invite sent",
  portal_invite_accepted: "Portal invite accepted",
  login_created: "Login created",
};

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function PortalAccessPanel({
  customerId,
  customerEmail,
  customerName,
  hasLogin: hasLoginProp,
  userRole,
  onRefresh,
}: Props) {
  const { showToast } = useToast();
  const isSuperAdmin = userRole === "super_admin";

  /* ---------- state ---------- */
  const [status, setStatus] = useState<PortalStatus | null>(null);
  const [history, setHistory] = useState<HistoryEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [tempPassword, setTempPassword] = useState<string | null>(null);
  const [inviteLink, setInviteLink] = useState<string | null>(null);
  const [resetModalOpen, setResetModalOpen] = useState(false);

  /* ---------- data fetch ---------- */
  const loadStatus = useCallback(async () => {
    try {
      const [s, h] = await Promise.all([
        api.get(`/customers/${customerId}/portal-status`),
        api.get(`/customers/${customerId}/portal-history?limit=25`),
      ]);
      setStatus((s as PortalStatus) || null);
      setHistory(((h as any)?.events || []) as HistoryEvent[]);
    } catch {
      // Non-fatal — panel still renders with the legacy hasLogin flag.
    } finally {
      setLoading(false);
    }
  }, [customerId]);

  useEffect(() => {
    loadStatus();
  }, [loadStatus]);

  /* ---------- derived ---------- */
  const hasLogin = (status?.has_login) ?? hasLoginProp ?? false;
  const active = (status?.active) ?? true;
  const portalEmail = status?.email || customerEmail || "";

  /* ---------- actions ---------- */

  /** Send / re-send portal invite. */
  const sendInvite = async () => {
    setBusy("invite");
    setTempPassword(null);
    setInviteLink(null);
    try {
      const r: any = await api.post(`/customers/${customerId}/portal-invite`);
      if (r?.emailed) {
        showToast(`Portal invite sent to ${r.email || portalEmail}`);
      } else if (r?.password) {
        setTempPassword(r.password);
        setInviteLink(r.login_url || null);
        showToast("Portal invite ready — share credentials manually", "info");
      } else {
        showToast("Portal invite sent");
      }
      onRefresh();
      await loadStatus();
    } catch (e) {
      showToast(mapApiError(e).message, "error");
    } finally {
      setBusy("");
    }
  };

  /** Send tokenized reset link (email). */
  const sendResetLink = () => {
    Alert.alert(
      "Send password reset link?",
      `Send ${customerName || "this customer"} a password reset email at ${portalEmail || "their email"}? The link expires in 30 minutes.`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Send reset link",
          onPress: async () => {
            setBusy("reset-link");
            try {
              const r: any = await api.post(`/customers/${customerId}/portal-reset-link`);
              const sentTo = r?.sent_to || portalEmail;
              showToast(`Reset link sent to ${sentTo}`);
              onRefresh();
              await loadStatus();
            } catch (e) {
              showToast(mapApiError(e).message, "error");
            } finally {
              setBusy("");
            }
          },
        },
      ],
    );
  };

  /** Copy reset link to clipboard (super_admin only). */
  const copyResetLink = () => {
    Alert.alert(
      "Copy password reset link?",
      `Generate and copy a one-time reset link for ${customerName || "this customer"}? This link works for 30 minutes — do not share by insecure channels.`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Generate and copy",
          onPress: async () => {
            setBusy("copy-link");
            try {
              const r: any = await api.post(`/customers/${customerId}/portal-reset-link-copy`);
              const url = r?.reset_url || "";
              if (url) {
                await Clipboard.setStringAsync(url);
                showToast(`Link copied — expires in ${r?.token_ttl_minutes || 30} min`, "info");
              } else {
                showToast("Reset link generated");
              }
              onRefresh();
              await loadStatus();
            } catch (e) {
              showToast(mapApiError(e).message, "error");
            } finally {
              setBusy("");
            }
          },
        },
      ],
    );
  };

  /** Reset password — opens modal for auto/explicit mode. */
  const handleResetSubmit = async (explicitPassword: string | null) => {
    setResetModalOpen(false);
    setBusy("reset");
    setTempPassword(null);
    setInviteLink(null);
    try {
      const body = explicitPassword ? { password: explicitPassword } : {};
      const r: any = await api.post(`/customers/${customerId}/portal-reset`, body);
      if (r?.emailed) {
        showToast(`Password reset email sent to ${r.email || portalEmail}`);
      } else if (r?.password) {
        setTempPassword(r.password);
        setInviteLink(r.login_url || null);
        showToast("New password generated — share it manually", "info");
      } else {
        showToast("Portal password reset");
      }
      onRefresh();
      await loadStatus();
    } catch (e) {
      showToast(mapApiError(e).message, "error");
    } finally {
      setBusy("");
    }
  };

  /** TD-91 · web `cd-impersonate` parity — "View as customer" opens the
   *  customer portal in the in-app browser AS this customer; the admin's
   *  own mobile session is never touched. Shared with the profile header:
   *  src/lib/portalViewAsCustomer.ts (endpoint, URL, browser fallback,
   *  error toasts). Busy key stays "view-as". */
  const viewAsCustomer = () =>
    runViewAsCustomer(customerId, { setBusy: (on) => setBusy(on ? "view-as" : ""), showToast });

  /** Revoke portal access. */
  const revokeAccess = () => {
    Alert.alert(
      "Revoke portal access?",
      `This will lock ${customerName || "this customer"} out of the portal immediately. You can re-invite them later.`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Revoke",
          style: "destructive",
          onPress: async () => {
            setBusy("revoke");
            try {
              await api.post(`/customers/${customerId}/portal-revoke`);
              showToast("Portal access revoked");
              onRefresh();
              await loadStatus();
            } catch (e) {
              showToast(mapApiError(e).message, "error");
            } finally {
              setBusy("");
            }
          },
        },
      ],
    );
  };

  /** Copy temp password to clipboard. */
  const copyTempPassword = async () => {
    if (!tempPassword) return;
    await Clipboard.setStringAsync(tempPassword);
    showToast("Copied to clipboard", "info");
  };

  /* ---------- render ---------- */

  if (loading) {
    return (
      <View style={s.loadingWrap} testID="portal-access-panel-loading">
        <ActivityIndicator size="small" color={colors.brand} />
        <Text style={s.loadingText}>Loading portal status…</Text>
      </View>
    );
  }

  return (
    <View style={s.panelWrap} testID="portal-access-panel">
      {/* Section label */}
      <Text style={s.sectionLabel}>Portal Access</Text>

      {/* Status row */}
      <View style={s.statusRow} testID="portal-status-row">
        {hasLogin ? (
          <>
            <View style={s.statusLine}>
              <Text style={s.statusEmail} numberOfLines={1} testID="portal-status-email">
                {portalEmail || "No email"}
              </Text>
              {active ? (
                <View style={[s.statusBadge, s.statusActive]} testID="portal-status-active">
                  <Text style={[s.statusBadgeText, { color: "#166534" }]}>Active</Text>
                </View>
              ) : (
                <View style={[s.statusBadge, s.statusRevoked]} testID="portal-status-revoked">
                  <Text style={[s.statusBadgeText, { color: "#B91C1C" }]}>Revoked</Text>
                </View>
              )}
            </View>
            <Text style={s.statusMeta} testID="portal-last-login">
              {status?.last_portal_login_at
                ? `Last login: ${new Date(status.last_portal_login_at).toLocaleString()}${status.last_portal_login_ip ? ` · ${status.last_portal_login_ip}` : ""}`
                : "No portal login recorded yet"}
            </Text>
          </>
        ) : (
          <Text style={s.statusMeta}>
            No portal login yet. Send an invite or create one manually.
          </Text>
        )}
      </View>

      {/* Action buttons */}
      <View style={s.actionsRow} testID="portal-actions-row">
        <ActionButton
          testID="portal-send-invite-btn"
          icon="mail-outline"
          label={hasLogin ? "Re-send invite" : "Send invite"}
          busy={busy === "invite"}
          disabled={!!busy || !portalEmail}
          onPress={sendInvite}
        />
        <ActionButton
          testID="portal-send-reset-link-btn"
          icon="link-outline"
          label="Send reset link"
          busy={busy === "reset-link"}
          disabled={!!busy || !portalEmail}
          onPress={sendResetLink}
        />
        {isSuperAdmin ? (
          <ActionButton
            testID="portal-copy-reset-link-btn"
            icon="copy-outline"
            label="Copy reset link"
            busy={busy === "copy-link"}
            disabled={!!busy || !portalEmail}
            onPress={copyResetLink}
          />
        ) : null}
        {hasLogin ? (
          <>
            <ActionButton
              testID="portal-reset-password-btn"
              icon="key-outline"
              label="Reset password"
              busy={busy === "reset"}
              disabled={!!busy}
              onPress={() => setResetModalOpen(true)}
            />
            {userRole === "admin" || userRole === "super_admin" ? (
              <ActionButton
                testID="portal-view-as-customer-btn"
                icon="eye-outline"
                label="View as customer"
                busy={busy === "view-as"}
                disabled={!!busy || !active}
                onPress={viewAsCustomer}
              />
            ) : null}
            <ActionButton
              testID="portal-revoke-btn"
              icon="ban-outline"
              label="Revoke access"
              busy={busy === "revoke"}
              disabled={!!busy || !active}
              onPress={revokeAccess}
              danger
            />
          </>
        ) : null}
      </View>

      {/* Temp password display */}
      {tempPassword ? (
        <View style={s.tempCard} testID="portal-temp-password-card">
          <Text style={s.tempTitle}>Share these credentials manually:</Text>
          {inviteLink ? (
            <Text style={s.tempRow} testID="portal-temp-login-url">
              Login: {inviteLink}
            </Text>
          ) : null}
          <Text style={s.tempRow} testID="portal-temp-email">
            Email: {portalEmail}
          </Text>
          <View style={s.tempPasswordRow}>
            <Text style={s.tempRow} testID="portal-temp-password-value">
              Temp password: {tempPassword}
            </Text>
            <Pressable
              onPress={copyTempPassword}
              style={s.copyBtn}
              hitSlop={8}
              testID="portal-copy-temp-password-btn"
              accessibilityRole="button"
              accessibilityLabel="Copy temporary password"
            >
              <Ionicons name="copy-outline" size={16} color={colors.brand} />
              <Text style={s.copyBtnText}>Copy</Text>
            </Pressable>
          </View>
        </View>
      ) : null}

      {/* Activity feed */}
      <View testID="portal-history-section">
        <Text style={s.feedLabel}>Recent portal activity</Text>
        {history.length === 0 ? (
          <Text style={s.feedEmpty} testID="portal-history-empty">No recent activity.</Text>
        ) : (
          <View testID="portal-history-list">
            {history.slice(0, 10).map((evt) => (
              <View key={evt.id} style={s.feedRow}>
                <View style={{ flex: 1 }}>
                  <Text style={s.feedEvent} numberOfLines={1}>
                    {EVENT_LABELS[evt.event] || evt.event}
                    {evt.actor_email ? ` — ${evt.actor_email}` : ""}
                  </Text>
                </View>
                <Text style={s.feedTime}>
                  {evt.created_at ? new Date(evt.created_at).toLocaleString() : "—"}
                </Text>
              </View>
            ))}
          </View>
        )}
      </View>

      {/* Reset password modal */}
      <PortalResetModal
        visible={resetModalOpen}
        onClose={() => setResetModalOpen(false)}
        onSubmit={handleResetSubmit}
      />
    </View>
  );
}

/* ------------------------------------------------------------------ */
/*  Sub-components                                                     */
/* ------------------------------------------------------------------ */

function ActionButton({
  testID,
  icon,
  label,
  busy,
  disabled,
  onPress,
  danger,
}: {
  testID: string;
  icon: string;
  label: string;
  busy?: boolean;
  disabled?: boolean;
  onPress: () => void;
  danger?: boolean;
}) {
  const textColor = danger ? "#B91C1C" : colors.brand;
  const bgColor = danger ? "#FEE2E2" : colors.brandTertiary;
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled}
      style={[s.actionBtn, { backgroundColor: bgColor }, disabled && { opacity: 0.4 }]}
      testID={testID}
      accessibilityRole="button"
      accessibilityLabel={label}
    >
      {busy ? (
        <ActivityIndicator size="small" color={textColor} />
      ) : (
        <Ionicons name={icon as any} size={16} color={textColor} />
      )}
      <Text style={[s.actionBtnText, { color: textColor }]} numberOfLines={1}>
        {busy ? "…" : label}
      </Text>
    </Pressable>
  );
}

function PortalResetModal({
  visible,
  onClose,
  onSubmit,
}: {
  visible: boolean;
  onClose: () => void;
  onSubmit: (explicitPassword: string | null) => void;
}) {
  const [mode, setMode] = useState<"auto" | "explicit">("auto");
  const [password, setPassword] = useState("");

  useEffect(() => {
    if (visible) {
      setMode("auto");
      setPassword("");
    }
  }, [visible]);

  const canSubmit = mode === "auto" || (mode === "explicit" && password.length >= 8);

  return (
    <Modal
      visible={visible}
      transparent
      animationType="slide"
      onRequestClose={onClose}
    >
      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : "height"}
        style={s.modalOverlay}
      >
        <Pressable style={s.modalBackdrop} onPress={onClose} />
        <View style={s.modalCard} testID="portal-reset-modal">
          <Text style={s.modalTitle}>Reset portal password</Text>

          {/* Auto mode */}
          <Pressable
            onPress={() => setMode("auto")}
            style={s.radioRow}
            testID="portal-reset-mode-auto"
            accessibilityRole="radio"
            accessibilityState={{ selected: mode === "auto" }}
          >
            <Ionicons
              name={mode === "auto" ? "radio-button-on" : "radio-button-off"}
              size={20}
              color={mode === "auto" ? colors.brand : colors.muted}
            />
            <View style={{ flex: 1 }}>
              <Text style={s.radioLabel}>Generate + email to customer</Text>
              <Text style={s.radioHint}>
                A one-time password is generated and emailed. If email delivery
                is not configured, the password appears here for manual sharing.
              </Text>
            </View>
          </Pressable>

          {/* Explicit mode */}
          <Pressable
            onPress={() => setMode("explicit")}
            style={s.radioRow}
            testID="portal-reset-mode-explicit"
            accessibilityRole="radio"
            accessibilityState={{ selected: mode === "explicit" }}
          >
            <Ionicons
              name={mode === "explicit" ? "radio-button-on" : "radio-button-off"}
              size={20}
              color={mode === "explicit" ? colors.brand : colors.muted}
            />
            <View style={{ flex: 1 }}>
              <Text style={s.radioLabel}>Set a specific password</Text>
              <Text style={s.radioHint}>
                Minimum 8 characters, at least one uppercase, one lowercase, one digit.
              </Text>
            </View>
          </Pressable>

          {mode === "explicit" ? (
            <AppTextInput
              style={s.passwordInput}
              value={password}
              onChangeText={setPassword}
              placeholder="New password"
              placeholderTextColor={colors.muted}
              secureTextEntry
              autoFocus
              testID="portal-reset-password-input"
            />
          ) : null}

          {/* Actions */}
          <View style={s.modalActions}>
            <Pressable
              onPress={onClose}
              style={s.modalCancelBtn}
              testID="portal-reset-cancel-btn"
              accessibilityRole="button"
            >
              <Text style={s.modalCancelText}>Cancel</Text>
            </Pressable>
            <Pressable
              onPress={() => onSubmit(mode === "explicit" ? password : null)}
              disabled={!canSubmit}
              style={[s.modalSubmitBtn, !canSubmit && { opacity: 0.4 }]}
              testID="portal-reset-submit-btn"
              accessibilityRole="button"
            >
              <Text style={s.modalSubmitText}>
                {mode === "auto" ? "Generate & send" : "Set password"}
              </Text>
            </Pressable>
          </View>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

/* ------------------------------------------------------------------ */
/*  Styles                                                             */
/* ------------------------------------------------------------------ */

const s = StyleSheet.create({
  panelWrap: {
    marginTop: spacing.xl,
    gap: spacing.md,
  },
  sectionLabel: {
    fontFamily: font.bold,
    fontSize: fontSize.xl,
    color: colors.onSurface,
  },
  loadingWrap: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    paddingVertical: spacing.md,
    marginTop: spacing.xl,
  },
  loadingText: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
  },
  /* Status row */
  statusRow: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
  },
  statusLine: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    flexWrap: "wrap",
  },
  statusEmail: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.onSurface,
    flexShrink: 1,
  },
  statusBadge: {
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: radius.pill,
    borderWidth: 1,
  },
  statusActive: {
    backgroundColor: "#DCFCE7",
    borderColor: "#86EFAC",
  },
  statusRevoked: {
    backgroundColor: "#FEE2E2",
    borderColor: "#FCA5A5",
  },
  statusBadgeText: {
    fontFamily: font.bold,
    fontSize: 10,
    textTransform: "uppercase",
    letterSpacing: 0.5,
  },
  statusMeta: {
    fontFamily: font.regular,
    fontSize: fontSize.xs,
    color: colors.onSurfaceSecondary,
    marginTop: 4,
  },
  /* Action buttons */
  actionsRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: spacing.sm,
  },
  actionBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
  },
  actionBtnText: {
    fontFamily: font.semibold,
    fontSize: fontSize.xs,
  },
  /* Temp password card */
  tempCard: {
    backgroundColor: colors.brandTertiary,
    borderRadius: radius.md,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.brand,
  },
  tempTitle: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.onBrandTertiary,
    marginBottom: spacing.sm,
  },
  tempRow: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.onBrandTertiary,
    marginBottom: 2,
  },
  tempPasswordRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: spacing.sm,
  },
  copyBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
  },
  copyBtnText: {
    fontFamily: font.semibold,
    fontSize: fontSize.xs,
    color: colors.brand,
  },
  /* Activity feed */
  feedLabel: {
    fontFamily: font.bold,
    fontSize: 10,
    color: colors.muted,
    letterSpacing: 1,
    textTransform: "uppercase",
    marginBottom: spacing.sm,
  },
  feedEmpty: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.onSurfaceSecondary,
  },
  feedRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "flex-start",
    gap: spacing.sm,
    paddingVertical: 6,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  feedEvent: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.onSurface,
  },
  feedTime: {
    fontFamily: font.regular,
    fontSize: fontSize.xs,
    color: colors.onSurfaceSecondary,
    flexShrink: 0,
  },
  /* Reset modal */
  modalOverlay: {
    flex: 1,
    justifyContent: "flex-end",
  },
  modalBackdrop: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.45)",
  },
  modalCard: {
    backgroundColor: colors.surface,
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    padding: spacing.xl,
    paddingBottom: 34,
  },
  modalTitle: {
    fontFamily: font.bold,
    fontSize: fontSize.lg,
    color: colors.onSurface,
    marginBottom: spacing.md,
  },
  radioRow: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: spacing.sm,
    marginBottom: spacing.md,
    paddingVertical: spacing.xs,
  },
  radioLabel: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.onSurface,
  },
  radioHint: {
    fontFamily: font.regular,
    fontSize: fontSize.xs,
    color: colors.onSurfaceSecondary,
    marginTop: 2,
  },
  passwordInput: {
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    height: 48,
    fontFamily: font.regular,
    fontSize: fontSize.base,
    color: colors.onSurface,
    marginBottom: spacing.md,
    ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}),
  },
  modalActions: {
    flexDirection: "row",
    justifyContent: "flex-end",
    gap: spacing.sm,
    marginTop: spacing.sm,
  },
  modalCancelBtn: {
    paddingHorizontal: spacing.lg,
    paddingVertical: 10,
    borderRadius: radius.md,
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.border,
  },
  modalCancelText: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.onSurface,
  },
  modalSubmitBtn: {
    paddingHorizontal: spacing.lg,
    paddingVertical: 10,
    borderRadius: radius.md,
    backgroundColor: colors.brand,
  },
  modalSubmitText: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: "#fff",
  },
});
