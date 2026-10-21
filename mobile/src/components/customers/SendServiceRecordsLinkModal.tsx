/**
 * Task 6 + 6b · Send Service Records Link Modal (mobile parity with web).
 *
 * Opens from the customer detail "Send ▼" sheet. Lets the admin send
 * a portal auto-login link via email or SMS, view recent sends, and
 * revoke individual links.
 *
 * Endpoints:
 *   POST /api/customers/{cid}/send-service-records-link  { channel, recipient? }
 *   GET  /api/customers/{cid}/service-records-link-status
 *   GET  /api/customers/{cid}/service-records-links        → { sends: [...] }
 *   POST /api/customers/{cid}/service-records-links/{token_id}/revoke → { ok: true }
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, ActivityIndicator, Alert, Modal, ScrollView } from "react-native";
import * as Clipboard from "expo-clipboard";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";
import AppTextInput from "@/src/components/ui/AppTextInput";
import { useToast } from "@/src/components/ToastProvider";

type Channel = "email" | "sms";

type RecentSend = {
  token_id: string;
  channel: string;
  recipient: string;
  sent_at: string;
  revoked_at?: string | null;
  revoked_by?: string | null;
};

interface Props {
  visible: boolean;
  customerId: string;
  customerEmail?: string | null;
  customerPhone?: string | null;
  channelOptIn?: {
    email_marketing?: boolean;
    sms_marketing?: boolean;
  };
  isMuted?: boolean;
  onClose: () => void;
}

function formatTimestamp(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric" })
      + " " + d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  } catch { return iso; }
}

export default function SendServiceRecordsLinkModal({
  visible, customerId, customerEmail, customerPhone,
  channelOptIn, isMuted, onClose,
}: Props) {
  const { showToast } = useToast(); // TD-96-mobile-toast-sweep (undefined since 4a8d04429)
  const [channel, setChannel] = useState<Channel>("email");
  const [recipient, setRecipient] = useState("");
  const [sending, setSending] = useState(false);
  const [statusLoading, setStatusLoading] = useState(false);
  const [sendsRemaining, setSendsRemaining] = useState<number | null>(null);
  const [portalUrl, setPortalUrl] = useState<string | null>(null);

  // Recent sends state (Task 6b)
  const [recentSends, setRecentSends] = useState<RecentSend[]>([]);
  const [sendsLoading, setSendsLoading] = useState(false);
  const [revoking, setRevoking] = useState<string | null>(null); // token_id being revoked
  const [confirmRevoke, setConfirmRevoke] = useState<string | null>(null); // token_id pending confirm

  // Consent checks.
  const emailDisabled = channelOptIn?.email_marketing === false || isMuted === true;
  const smsDisabled = channelOptIn?.sms_marketing === false || isMuted === true;

  // Prefill recipient when channel changes.
  useEffect(() => {
    if (channel === "email") {
      setRecipient(customerEmail || "");
    } else {
      setRecipient(customerPhone || "");
    }
  }, [channel, customerEmail, customerPhone]);

  // If email is disabled, default to SMS.
  useEffect(() => {
    if (emailDisabled && !smsDisabled) setChannel("sms");
  }, [emailDisabled, smsDisabled]);

  // Fetch throttle status + portal URL + recent sends on open.
  const fetchStatus = useCallback(async () => {
    if (!customerId) return;
    setStatusLoading(true);
    try {
      const data = await api.get(`/customers/${customerId}/service-records-link-status`);
      setSendsRemaining(data?.sends_remaining ?? null);
      setPortalUrl(data?.portal_url ?? null);
    } catch { /* ignore */ }
    setStatusLoading(false);
  }, [customerId]);

  const fetchRecentSends = useCallback(async () => {
    if (!customerId) return;
    setSendsLoading(true);
    try {
      const data = await api.get(`/customers/${customerId}/service-records-links`);
      setRecentSends(data?.sends || []);
    } catch {
      setRecentSends([]);
    }
    setSendsLoading(false);
  }, [customerId]);

  useEffect(() => {
    if (!visible) return;
    fetchStatus();
    fetchRecentSends();
  }, [visible, customerId, fetchStatus, fetchRecentSends]);

  const handleSend = useCallback(async () => {
    if (sending) return;
    if (channel === "email" && emailDisabled) {
      Alert.alert("Email disabled", "This customer has opted out of email communications.");
      return;
    }
    if (channel === "sms" && smsDisabled) {
      Alert.alert("SMS disabled", "This customer has opted out of SMS communications.");
      return;
    }
    setSending(true);
    try {
      const body: any = { channel };
      if (recipient.trim()) body.recipient = recipient.trim();
      await api.post(`/customers/${customerId}/send-service-records-link`, body);
      Alert.alert(
        "Sent",
        channel === "email" ? "Sent by email" : "Sent by text",
      );
      // Refresh status + recent sends after send.
      fetchStatus();
      fetchRecentSends();
    } catch (e: any) {
      const detail = e?.response?.detail || e?.message || "Send failed";
      Alert.alert("Error", String(detail));
    } finally {
      setSending(false);
    }
  }, [channel, recipient, customerId, sending, emailDisabled, smsDisabled, fetchStatus, fetchRecentSends]);

  const handleRevoke = useCallback(async (tokenId: string) => {
    setRevoking(tokenId);
    try {
      await api.post(`/customers/${customerId}/service-records-links/${tokenId}/revoke`, {});
      setConfirmRevoke(null);
      // Refresh the list to show "Revoked" badge.
      await fetchRecentSends();
    } catch (e: any) {
      const detail = e?.response?.detail || e?.message || "Revoke failed";
      Alert.alert("Error", String(detail));
    } finally {
      setRevoking(null);
    }
  }, [customerId, fetchRecentSends]);

  const handleCopyLink = useCallback(async () => {
    if (!portalUrl) return;
    await Clipboard.setStringAsync(portalUrl);
    showToast("Portal link copied to clipboard");
  }, [portalUrl]);

  const canSend = sendsRemaining === null || sendsRemaining > 0;

  return (
    <Modal
      visible={visible}
      animationType="slide"
      presentationStyle="pageSheet"
      onRequestClose={onClose}
      testID="send-service-records-link-modal"
    >
      <ScrollView style={styles.root} contentContainerStyle={styles.scrollContent}>
        {/* Header */}
        <View style={styles.header}>
          <Text style={styles.headerTitle}>Send Service Records</Text>
          <Pressable onPress={onClose} hitSlop={12} testID="send-records-close-btn">
            <Ionicons name="close" size={22} color={colors.onSurface} />
          </Pressable>
        </View>

        {/* Channel tabs */}
        <View style={styles.tabs}>
          <Pressable
            style={[styles.tab, channel === "email" && styles.tabActive, emailDisabled && styles.tabDisabled]}
            onPress={() => !emailDisabled && setChannel("email")}
            testID="send-via-email-btn"
          >
            <Ionicons name="mail-outline" size={16} color={channel === "email" ? colors.brand : colors.muted} />
            <Text style={[styles.tabText, channel === "email" && styles.tabTextActive]}>Email</Text>
          </Pressable>
          <Pressable
            style={[styles.tab, channel === "sms" && styles.tabActive, smsDisabled && styles.tabDisabled]}
            onPress={() => !smsDisabled && setChannel("sms")}
            testID="send-via-sms-btn"
          >
            <Ionicons name="chatbubble-outline" size={16} color={channel === "sms" ? colors.brand : colors.muted} />
            <Text style={[styles.tabText, channel === "sms" && styles.tabTextActive]}>SMS</Text>
          </Pressable>
        </View>

        {/* Consent warnings */}
        {emailDisabled && channel === "email" ? (
          <View style={styles.consentWarn} testID="email-consent-warning">
            <Ionicons name="alert-circle" size={14} color="#B45309" />
            <Text style={styles.consentWarnText}>
              {isMuted ? "Customer is muted" : "Customer opted out of email"}
            </Text>
          </View>
        ) : null}
        {smsDisabled && channel === "sms" ? (
          <View style={styles.consentWarn} testID="sms-consent-warning">
            <Ionicons name="alert-circle" size={14} color="#B45309" />
            <Text style={styles.consentWarnText}>
              {isMuted ? "Customer is muted" : "Customer opted out of SMS"}
            </Text>
          </View>
        ) : null}

        {/* Recipient */}
        <Text style={styles.label}>
          {channel === "email" ? "RECIPIENT EMAIL" : "RECIPIENT PHONE"}
        </Text>
        <AppTextInput
          style={styles.input}
          value={recipient}
          onChangeText={setRecipient}
          placeholder={channel === "email" ? "customer@example.com" : "+1 555-1234"}
          placeholderTextColor={colors.muted}
          keyboardType={channel === "email" ? "email-address" : "phone-pad"}
          autoCapitalize="none"
          autoCorrect={false}
          testID="send-records-recipient-input"
        />

        {/* Throttle info */}
        {statusLoading ? (
          <ActivityIndicator size="small" style={{ marginTop: spacing.md }} />
        ) : sendsRemaining !== null ? (
          <Text style={styles.throttle} testID="send-records-throttle">
            {sendsRemaining} of 5 sends remaining this hour
          </Text>
        ) : null}

        {/* Copy Link */}
        {portalUrl ? (
          <Pressable
            style={styles.copyLinkRow}
            onPress={handleCopyLink}
            testID="copy-link-btn"
          >
            <Ionicons name="link-outline" size={16} color={colors.brand} />
            <Text style={styles.copyLinkText} numberOfLines={1}>
              {portalUrl}
            </Text>
            <Ionicons name="copy-outline" size={16} color={colors.brand} />
          </Pressable>
        ) : null}

        {/* Send button */}
        <Pressable
          style={[styles.sendBtn, (!canSend || sending) && styles.sendBtnDisabled]}
          onPress={handleSend}
          disabled={!canSend || sending}
          testID="send-service-records-link-btn"
        >
          {sending ? (
            <ActivityIndicator size="small" color="#fff" />
          ) : (
            <>
              <Ionicons name="send-outline" size={16} color="#fff" />
              <Text style={styles.sendBtnText}>
                Send via {channel === "email" ? "Email" : "SMS"}
              </Text>
            </>
          )}
        </Pressable>

        {!canSend ? (
          <Text style={styles.throttleWarn} testID="send-records-throttle-exceeded">
            Hourly send limit reached. Try again later.
          </Text>
        ) : null}

        {/* ── Task 6b · Recent sends + Revoke ────────────────────── */}
        <View style={styles.recentSection} testID="recent-sends-section">
          <Text style={styles.recentTitle}>Recent sends</Text>

          {sendsLoading ? (
            <ActivityIndicator size="small" style={{ marginTop: spacing.md }} />
          ) : recentSends.length === 0 ? (
            <Text style={styles.recentEmpty} testID="recent-sends-empty">
              No links sent yet.
            </Text>
          ) : (
            recentSends.map((s) => {
              const isRevoked = !!s.revoked_at;
              const isConfirming = confirmRevoke === s.token_id;
              const isRevoking = revoking === s.token_id;

              return (
                <View
                  key={s.token_id}
                  style={[styles.sendRow, isRevoked && styles.sendRowRevoked]}
                  testID={`recent-send-row-${s.token_id}`}
                >
                  {/* Channel icon */}
                  <Ionicons
                    name={s.channel === "sms" ? "chatbubble-outline" : "mail-outline"}
                    size={16}
                    color={isRevoked ? colors.muted : colors.onSurface}
                  />

                  {/* Info column */}
                  <View style={styles.sendInfo}>
                    <Text style={[styles.sendRecipient, isRevoked && { color: colors.muted }]} numberOfLines={1}>
                      {s.recipient || "—"}
                    </Text>
                    <Text style={styles.sendTimestamp}>
                      {formatTimestamp(s.sent_at)}
                    </Text>
                  </View>

                  {/* Status / Revoke action */}
                  {isRevoked ? (
                    <View style={styles.revokedBadge} testID={`revoked-badge-${s.token_id}`}>
                      <Ionicons name="shield-outline" size={12} color="#991B1B" />
                      <Text style={styles.revokedText}>Revoked</Text>
                    </View>
                  ) : isConfirming ? (
                    <View style={styles.confirmRow}>
                      <Text style={styles.confirmLabel}>Revoke?</Text>
                      <Pressable
                        style={styles.confirmYes}
                        onPress={() => handleRevoke(s.token_id)}
                        disabled={isRevoking}
                        testID={`revoke-confirm-yes-${s.token_id}`}
                      >
                        {isRevoking ? (
                          <ActivityIndicator size={10} color="#fff" />
                        ) : (
                          <Text style={styles.confirmYesText}>Yes</Text>
                        )}
                      </Pressable>
                      <Pressable
                        style={styles.confirmNo}
                        onPress={() => setConfirmRevoke(null)}
                        testID={`revoke-confirm-no-${s.token_id}`}
                      >
                        <Text style={styles.confirmNoText}>No</Text>
                      </Pressable>
                    </View>
                  ) : (
                    <Pressable
                      style={styles.revokeBtn}
                      onPress={() => setConfirmRevoke(s.token_id)}
                      testID={`revoke-btn-${s.token_id}`}
                    >
                      <Text style={styles.revokeBtnText}>Revoke</Text>
                    </Pressable>
                  )}
                </View>
              );
            })
          )}
        </View>
      </ScrollView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: colors.surface,
  },
  scrollContent: {
    paddingHorizontal: spacing.xl,
    paddingTop: spacing["2xl"],
    paddingBottom: 40,
  },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: spacing.xl,
  },
  headerTitle: {
    fontFamily: font.bold,
    fontSize: fontSize.xl,
    color: colors.onSurface,
  },
  tabs: {
    flexDirection: "row",
    gap: spacing.sm,
    marginBottom: spacing.lg,
  },
  tab: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    paddingVertical: spacing.md,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surfaceSecondary,
  },
  tabActive: {
    borderColor: colors.brand,
    backgroundColor: "#EFF6FF",
  },
  tabDisabled: {
    opacity: 0.4,
  },
  tabText: {
    fontFamily: font.semibold,
    fontSize: fontSize.base,
    color: colors.muted,
  },
  tabTextActive: {
    color: colors.brand,
  },
  consentWarn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: "#FEF3C7",
    padding: spacing.md,
    borderRadius: radius.md,
    marginBottom: spacing.md,
  },
  consentWarnText: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: "#B45309",
  },
  label: {
    fontFamily: font.bold,
    fontSize: 11,
    letterSpacing: 1.2,
    color: colors.muted,
    marginBottom: spacing.xs,
  },
  input: {
    fontFamily: font.regular,
    fontSize: fontSize.base,
    color: colors.onSurface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.md,
    backgroundColor: colors.surfaceSecondary,
    marginBottom: spacing.sm,
  },
  throttle: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
    marginTop: spacing.xs,
    marginBottom: spacing.md,
  },
  copyLinkRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    backgroundColor: colors.surfaceSecondary,
    marginBottom: spacing.lg,
  },
  copyLinkText: {
    flex: 1,
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.brand,
  },
  sendBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.sm,
    backgroundColor: colors.brand,
    paddingVertical: spacing.lg,
    borderRadius: radius.md,
    marginTop: spacing.sm,
  },
  sendBtnDisabled: {
    opacity: 0.5,
  },
  sendBtnText: {
    fontFamily: font.bold,
    fontSize: fontSize.base,
    color: "#fff",
  },
  throttleWarn: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: "#B45309",
    textAlign: "center",
    marginTop: spacing.md,
  },
  // ── Task 6b · Recent sends ──────────────────────────────────
  recentSection: {
    marginTop: spacing["2xl"],
    borderTopWidth: 1,
    borderTopColor: colors.border,
    paddingTop: spacing.lg,
  },
  recentTitle: {
    fontFamily: font.bold,
    fontSize: fontSize.base,
    color: colors.onSurface,
    marginBottom: spacing.md,
  },
  recentEmpty: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
    fontStyle: "italic",
  },
  sendRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    paddingVertical: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  sendRowRevoked: {
    opacity: 0.6,
  },
  sendInfo: {
    flex: 1,
  },
  sendRecipient: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.onSurface,
  },
  sendTimestamp: {
    fontFamily: font.regular,
    fontSize: 11,
    color: colors.muted,
    marginTop: 1,
  },
  revokedBadge: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    backgroundColor: "#FEE2E2",
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: radius.sm,
  },
  revokedText: {
    fontFamily: font.bold,
    fontSize: 10,
    color: "#991B1B",
    letterSpacing: 0.3,
  },
  revokeBtn: {
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: "#DC2626",
  },
  revokeBtnText: {
    fontFamily: font.semibold,
    fontSize: 11,
    color: "#DC2626",
  },
  confirmRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
  },
  confirmLabel: {
    fontFamily: font.semibold,
    fontSize: 11,
    color: colors.muted,
  },
  confirmYes: {
    backgroundColor: "#DC2626",
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: radius.sm,
    minWidth: 36,
    alignItems: "center",
  },
  confirmYesText: {
    fontFamily: font.bold,
    fontSize: 11,
    color: "#fff",
  },
  confirmNo: {
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: colors.border,
  },
  confirmNoText: {
    fontFamily: font.semibold,
    fontSize: 11,
    color: colors.muted,
  },
});
