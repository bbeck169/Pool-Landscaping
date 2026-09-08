/**
 * Task 6 · Send Service Records Link Modal (mobile parity with web).
 *
 * Opens from the customer detail "Send ▼" sheet. Lets the admin send
 * a portal auto-login link via email or SMS.
 *
 * Endpoints:
 *   POST /api/customers/{cid}/send-service-records-link  { channel, recipient? }
 *   GET  /api/customers/{cid}/service-records-link-status
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, TextInput,
  ActivityIndicator, Alert, Modal,
} from "react-native";
import * as Clipboard from "expo-clipboard";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";

type Channel = "email" | "sms";

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

export default function SendServiceRecordsLinkModal({
  visible, customerId, customerEmail, customerPhone,
  channelOptIn, isMuted, onClose,
}: Props) {
  const [channel, setChannel] = useState<Channel>("email");
  const [recipient, setRecipient] = useState("");
  const [sending, setSending] = useState(false);
  const [statusLoading, setStatusLoading] = useState(false);
  const [sendsRemaining, setSendsRemaining] = useState<number | null>(null);
  const [portalUrl, setPortalUrl] = useState<string | null>(null);

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

  // Fetch throttle status + portal URL on open.
  useEffect(() => {
    if (!visible) return;
    setStatusLoading(true);
    api.get(`/customers/${customerId}/service-records-link-status`)
      .then((data: any) => {
        setSendsRemaining(data?.sends_remaining ?? null);
        setPortalUrl(data?.portal_url ?? null);
      })
      .catch(() => {})
      .finally(() => setStatusLoading(false));
  }, [visible, customerId]);

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
      // Refresh status after send.
      try {
        const data = await api.get(`/customers/${customerId}/service-records-link-status`);
        setSendsRemaining(data?.sends_remaining ?? null);
      } catch { /* ignore */ }
    } catch (e: any) {
      const detail = e?.response?.detail || e?.message || "Send failed";
      Alert.alert("Error", String(detail));
    } finally {
      setSending(false);
    }
  }, [channel, recipient, customerId, sending, emailDisabled, smsDisabled]);

  const handleCopyLink = useCallback(async () => {
    if (!portalUrl) return;
    await Clipboard.setStringAsync(portalUrl);
    Alert.alert("Copied", "Portal link copied to clipboard");
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
      <View style={styles.root}>
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
        <TextInput
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
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: colors.surface,
    paddingHorizontal: spacing.xl,
    paddingTop: spacing["2xl"],
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
});
