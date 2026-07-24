import React, { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  RefreshControl,
  Pressable,
  ActivityIndicator,
  TextInput,
  Switch,
  ScrollView,
  Modal,
  KeyboardAvoidingView,
  Platform,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { EmptyState } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";

/* ── helpers ────────────────────────────── */

function relTime(iso: string | undefined) {
  if (!iso) return "\u2014";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return String(iso);
  const sec = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (sec < 60) return `${sec}s ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const d = Math.floor(hr / 24);
  return `${d}d ago`;
}

const STAT_TONES: Record<string, { bg: string; fg: string }> = {
  sent: { bg: "#DCFCE7", fg: "#166534" },
  failed: { bg: "#FEE2E2", fg: "#991B1B" },
  suppressed: { bg: "#FEF3C7", fg: "#92400E" },
  no_contact: { bg: "#E5E7EB", fg: "#374151" },
};

function StatPill({ label, value, tone }: { label: string; value: number; tone: string }) {
  const t = STAT_TONES[tone] || STAT_TONES.no_contact;
  return (
    <View style={[s.statPill, { backgroundColor: t.bg }]} testID={`broadcast-stat-${tone}`}>
      <Text style={[s.statPillText, { color: t.fg }]}>
        {label}: {value}
      </Text>
    </View>
  );
}

/* ── skeleton ────────────────────────────── */

function SkeletonRows() {
  return (
    <View style={s.skeletonWrap} testID="broadcasts-skeleton">
      {[1, 2, 3].map((i) => (
        <View key={i} style={s.skeletonCard}>
          <View style={[s.skeletonBar, { width: "70%" }]} />
          <View style={[s.skeletonBar, { width: "50%", marginTop: 6 }]} />
          <View style={{ flexDirection: "row", gap: 6, marginTop: 8 }}>
            <View style={[s.skeletonBar, { width: 60, height: 18 }]} />
            <View style={[s.skeletonBar, { width: 60, height: 18 }]} />
          </View>
        </View>
      ))}
    </View>
  );
}

/* ── Batch Row ───────────────────────────── */

function BatchRow({
  batch,
  expanded,
  onToggle,
}: {
  batch: any;
  expanded: boolean;
  onToggle: () => void;
}) {
  const [detail, setDetail] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!expanded || detail) return;
    setLoading(true);
    api
      .get(`/mass-messaging/batches/${batch.id}`)
      .then(setDetail)
      .catch(() => setDetail(null))
      .finally(() => setLoading(false));
  }, [expanded, batch.id, detail]);

  const stats = batch.stats || {};

  return (
    <View style={s.batchWrap} testID={`broadcast-row-${batch.id}`}>
      <Pressable
        onPress={onToggle}
        style={({ pressed }) => [s.batchHeader, pressed && { opacity: 0.85 }]}
      >
        <Ionicons
          name={expanded ? "chevron-down" : "chevron-forward"}
          size={16}
          color={colors.muted}
        />
        <View style={{ flex: 1 }}>
          <Text style={s.batchTitle} numberOfLines={1}>
            {batch.custom_subject || batch.template_id || "Broadcast"}
          </Text>
          <Text style={s.batchMeta}>
            {relTime(batch.started_at)} {"\u00b7"} channels{" "}
            {(batch.channels || []).join(" + ")} {"\u00b7"} status {batch.status}
          </Text>
        </View>
        <View style={s.statsRow}>
          <StatPill label="sent" value={stats.sent || 0} tone="sent" />
          <StatPill label="fail" value={stats.failed || 0} tone="failed" />
        </View>
      </Pressable>

      {expanded ? (
        <View style={s.batchDetail}>
          {/* Stat pills row */}
          <View style={[s.statsRow, { marginBottom: spacing.sm }]}>
            <StatPill label="sent" value={stats.sent || 0} tone="sent" />
            <StatPill label="failed" value={stats.failed || 0} tone="failed" />
            <StatPill label="suppressed" value={stats.suppressed || 0} tone="suppressed" />
            <StatPill label="no contact" value={stats.no_contact || 0} tone="no_contact" />
          </View>
          {loading ? (
            <ActivityIndicator size="small" color={colors.brand} />
          ) : detail?.deliveries?.items?.length ? (
            <View>
              <Text style={s.recipientLabel}>
                Recipients ({detail.deliveries.total})
              </Text>
              {detail.deliveries.items.map((d: any) => (
                <View
                  key={d.id}
                  style={s.deliveryRow}
                  testID={`broadcast-delivery-${d.id}`}
                >
                  <View style={s.channelBadge}>
                    <Text style={s.channelBadgeText}>{(d.channel || "").toUpperCase()}</Text>
                  </View>
                  <Text style={s.recipientText} numberOfLines={1}>
                    {d.recipient || "(no address)"}
                  </Text>
                  <Text
                    style={[
                      s.deliveryStatus,
                      {
                        color:
                          d.delivery_status === "sent"
                            ? "#166534"
                            : d.delivery_status === "failed"
                            ? "#991B1B"
                            : colors.muted,
                      },
                    ]}
                  >
                    {d.delivery_status}
                  </Text>
                </View>
              ))}
            </View>
          ) : (
            <Text style={s.noDeliveries}>No delivery rows yet.</Text>
          )}
        </View>
      ) : null}
    </View>
  );
}

/* ── Compose Bottom Sheet ─────────────────── */

function ComposeSheet({
  visible,
  onClose,
}: {
  visible: boolean;
  onClose: (success?: boolean) => void;
}) {
  const [emailOn, setEmailOn] = useState(true);
  const [smsOn, setSmsOn] = useState(true);
  const [subject, setSubject] = useState("Hi {{customer.first_name}}");
  const [body, setBody] = useState(
    "Hi {{customer.first_name}} \u2014 quick note from the team. Reply STOP to opt out."
  );
  const [preview, setPreview] = useState<any>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [confirmVisible, setConfirmVisible] = useState(false);
  const [error, setError] = useState("");
  const [successMsg, setSuccessMsg] = useState("");

  const channels = [emailOn && "email", smsOn && "sms"].filter(Boolean) as string[];

  // Load preview
  useEffect(() => {
    if (!visible || channels.length === 0 || !body.trim()) {
      setPreview(null);
      return;
    }
    const timer = setTimeout(() => {
      setPreviewLoading(true);
      setError("");
      const payload: any = {
        channels,
        audience: "all_active_customers",
        audience_status: "active",
        subject: emailOn ? subject : null,
        body,
      };
      api
        .post("/mass-messaging/preview", payload)
        .then(setPreview)
        .catch((e: any) => {
          setError(e?.message || "Preview failed");
          setPreview(null);
        })
        .finally(() => setPreviewLoading(false));
    }, 600);
    return () => clearTimeout(timer);
  }, [visible, emailOn, smsOn, subject, body]);

  const total =
    (preview?.estimated_recipients?.email || 0) +
    (preview?.estimated_recipients?.sms || 0);

  const canSend =
    channels.length > 0 &&
    body.trim().length > 0 &&
    !!preview?.confirm_token &&
    total > 0 &&
    !sending;

  const handleSend = async () => {
    if (!canSend) return;
    setSending(true);
    setError("");
    try {
      const payload = {
        channels,
        audience: "all_active_customers",
        audience_status: "active",
        confirm_token: preview.confirm_token,
        subject: emailOn ? subject : null,
        body,
      };
      const res = await api.post("/mass-messaging/send", payload);
      setSuccessMsg(
        `Broadcast started \u2014 ${(res.queued_email || 0) + (res.queued_sms || 0)} messages queued.`
      );
      setConfirmVisible(false);
      setTimeout(() => onClose(true), 1500);
    } catch (e: any) {
      setError(e?.message || "Send failed");
      setConfirmVisible(false);
    } finally {
      setSending(false);
    }
  };

  const reset = () => {
    setEmailOn(true);
    setSmsOn(true);
    setSubject("Hi {{customer.first_name}}");
    setBody("Hi {{customer.first_name}} \u2014 quick note from the team. Reply STOP to opt out.");
    setPreview(null);
    setError("");
    setSuccessMsg("");
    setSending(false);
    setConfirmVisible(false);
  };

  return (
    <Modal
      visible={visible}
      animationType="slide"
      presentationStyle="pageSheet"
      onRequestClose={() => { reset(); onClose(); }}
    >
      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : "height"}
        style={{ flex: 1, backgroundColor: colors.surfaceSecondary }}
      >
        {/* Header bar */}
        <View style={s.sheetHeader}>
          <Pressable onPress={() => { reset(); onClose(); }} testID="mass-messaging-cancel-btn">
            <Text style={s.sheetCancel}>Cancel</Text>
          </Pressable>
          <Text style={s.sheetTitle}>Compose Broadcast</Text>
          <Pressable
            onPress={() => setConfirmVisible(true)}
            disabled={!canSend}
            testID="mass-messaging-send-btn"
          >
            <Text
              style={[s.sheetSend, !canSend && { opacity: 0.4 }]}
            >
              {sending ? "Sending\u2026" : "Send Now"}
            </Text>
          </Pressable>
        </View>

        <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}>
          {/* Success */}
          {successMsg ? (
            <View style={s.successBanner} testID="mass-messaging-success">
              <Ionicons name="checkmark-circle" size={18} color="#166534" />
              <Text style={s.successText}>{successMsg}</Text>
            </View>
          ) : null}

          {/* Channels */}
          <Text style={s.fieldLabel}>Channels</Text>
          <View style={s.channelRow}>
            <View style={s.channelItem}>
              <Switch
                value={emailOn}
                onValueChange={setEmailOn}
                trackColor={{ true: colors.brand }}
                testID="mass-messaging-channel-email-checkbox"
              />
              <Ionicons name="mail-outline" size={16} color={colors.onSurface} />
              <Text style={s.channelText}>Email</Text>
            </View>
            <View style={s.channelItem}>
              <Switch
                value={smsOn}
                onValueChange={setSmsOn}
                trackColor={{ true: colors.brand }}
                testID="mass-messaging-channel-sms-checkbox"
              />
              <Ionicons name="chatbubble-outline" size={16} color={colors.onSurface} />
              <Text style={s.channelText}>SMS</Text>
            </View>
          </View>

          {/* Subject (email only) */}
          {emailOn ? (
            <>
              <Text style={s.fieldLabel}>Subject (email)</Text>
              <TextInput
                style={s.input}
                value={subject}
                onChangeText={setSubject}
                placeholder="Hi {{customer.first_name}}"
                placeholderTextColor={colors.muted}
                testID="mass-messaging-subject-input"
              />
            </>
          ) : null}

          {/* Body */}
          <Text style={s.fieldLabel}>Body (supports merge tags)</Text>
          <TextInput
            style={[s.input, { height: 120, textAlignVertical: "top" }]}
            value={body}
            onChangeText={setBody}
            placeholder="Type your broadcast message..."
            placeholderTextColor={colors.muted}
            multiline
            testID="mass-messaging-body-input"
          />

          {/* Preview */}
          <View style={s.previewBox} testID="mass-messaging-preview">
            <Text style={s.previewLabel}>
              Live Preview{" "}
              {previewLoading ? (
                <Text style={{ color: colors.brand }}>Refreshing\u2026</Text>
              ) : null}
            </Text>
            {error ? (
              <View style={s.errorRow}>
                <Ionicons name="alert-circle" size={14} color="#DC2626" />
                <Text style={s.errorRowText}>{error}</Text>
              </View>
            ) : null}
            {preview ? (
              <View>
                <Text style={s.previewSummary} testID="mass-messaging-preview-summary">
                  Sending to {total} recipient{total === 1 ? "" : "s"} \u2014{" "}
                  {preview.estimated_recipients.email} via email,{" "}
                  {preview.estimated_recipients.sms} via SMS.
                </Text>
                <Text style={s.previewMeta}>
                  {(preview.stats?.suppressed_email || 0) + (preview.stats?.suppressed_sms || 0)}{" "}
                  suppressed, {preview.stats?.no_contact_email || 0} without email,{" "}
                  {preview.stats?.no_contact_sms || 0} without phone.
                  {preview.estimated_cost_hint
                    ? ` Est. cost: $${preview.estimated_cost_hint}`
                    : ""}
                </Text>
              </View>
            ) : !previewLoading ? (
              <Text style={s.previewPlaceholder}>
                Pick channels + type a message to preview.
              </Text>
            ) : null}
          </View>
        </ScrollView>

        {/* Confirm Dialog */}
        <Modal visible={confirmVisible} transparent animationType="fade">
          <View style={s.confirmOverlay}>
            <View style={s.confirmBox} testID="mass-messaging-confirm-modal">
              <Text style={s.confirmTitle}>Confirm broadcast</Text>
              <Text style={s.confirmDesc}>
                You are about to send to {total} customer{total === 1 ? "" : "s"}.
                This can't be undone.
              </Text>
              <View style={s.confirmBtns}>
                <Pressable
                  style={s.confirmCancelBtn}
                  onPress={() => setConfirmVisible(false)}
                  testID="mass-messaging-confirm-cancel"
                >
                  <Text style={s.confirmCancelText}>Cancel</Text>
                </Pressable>
                <Pressable
                  style={s.confirmSendBtn}
                  onPress={handleSend}
                  testID="mass-messaging-confirm-send"
                >
                  <Text style={s.confirmSendText}>
                    {sending ? "Sending\u2026" : "Yes, send now"}
                  </Text>
                </Pressable>
              </View>
            </View>
          </View>
        </Modal>
      </KeyboardAvoidingView>
    </Modal>
  );
}

/* ── main page ───────────────────────────── */

export default function BroadcastsPage() {
  const { user } = useAuth();
  const role = (user?.role || "").toLowerCase();
  const allowed = role === "admin" || role === "super_admin";

  const [batches, setBatches] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [composeOpen, setComposeOpen] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await api.get("/mass-messaging/batches");
      setBatches(r?.items || []);
    } catch {
      setBatches([]);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      if (allowed) load();
    }, [allowed, load])
  );

  if (!allowed) {
    return (
      <View style={s.root}>
        <Header title="Broadcasts" back />
        <View style={s.forbiddenWrap}>
          <Ionicons name="lock-closed" size={32} color={colors.muted} />
          <Text style={s.forbiddenText}>Broadcasts are admin-only.</Text>
        </View>
      </View>
    );
  }

  return (
    <View style={s.root}>
      <Header
        title="Broadcasts"
        subtitle="Past mass-messaging batches"
        back
        right={
          <View style={{ flexDirection: "row", gap: spacing.sm }}>
            <Pressable onPress={load} style={s.refreshBtn} testID="broadcasts-refresh-btn">
              <Ionicons name="refresh-outline" size={18} color={colors.onSurface} />
            </Pressable>
            <Pressable
              onPress={() => setComposeOpen(true)}
              style={s.composeBtn}
              testID="mass-messaging-compose-btn"
            >
              <Ionicons name="megaphone-outline" size={16} color="#fff" />
              <Text style={s.composeBtnText}>Compose</Text>
            </Pressable>
          </View>
        }
      />

      {loading ? (
        <SkeletonRows />
      ) : batches.length === 0 ? (
        <EmptyState
          icon="megaphone-outline"
          title="No broadcasts yet"
          subtitle='Use the "Compose" button to send your first broadcast.'
          testID="broadcasts-empty"
        />
      ) : (
        <FlatList
          testID="broadcasts-list"
          data={batches}
          keyExtractor={(item) => item.id}
          renderItem={({ item }) => (
            <BatchRow
              batch={item}
              expanded={expanded === item.id}
              onToggle={() =>
                setExpanded((cur) => (cur === item.id ? null : item.id))
              }
            />
          )}
          contentContainerStyle={{ paddingBottom: spacing["3xl"] }}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={() => {
                setRefreshing(true);
                load();
              }}
            />
          }
        />
      )}

      <ComposeSheet
        visible={composeOpen}
        onClose={(success) => {
          setComposeOpen(false);
          if (success) load();
        }}
      />
    </View>
  );
}

/* ── styles ──────────────────────────────── */

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },

  /* Batch rows */
  batchWrap: {
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    backgroundColor: colors.surface,
  },
  batchHeader: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
  },
  batchTitle: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  batchMeta: { fontFamily: font.regular, fontSize: 11, color: colors.muted, marginTop: 2 },
  statsRow: { flexDirection: "row", flexWrap: "wrap", gap: 4 },
  statPill: { paddingHorizontal: 8, paddingVertical: 2, borderRadius: radius.pill },
  statPillText: { fontFamily: font.bold, fontSize: 10 },

  batchDetail: {
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    backgroundColor: colors.surfaceSecondary,
  },
  recipientLabel: {
    fontFamily: font.bold,
    fontSize: 10,
    textTransform: "uppercase",
    color: colors.muted,
    marginBottom: spacing.xs,
  },
  deliveryRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: 4,
    borderRadius: radius.sm,
    backgroundColor: colors.surface,
    marginBottom: 4,
  },
  channelBadge: {
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
    backgroundColor: colors.brandTertiary,
  },
  channelBadgeText: { fontFamily: font.bold, fontSize: 9, color: colors.onBrandTertiary },
  recipientText: { flex: 1, fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurface },
  deliveryStatus: { fontFamily: font.bold, fontSize: 11 },
  noDeliveries: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },

  /* Header buttons */
  refreshBtn: {
    width: 36,
    height: 36,
    borderRadius: radius.sm,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: "center",
    justifyContent: "center",
  },
  composeBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: radius.sm,
    backgroundColor: colors.brand,
  },
  composeBtnText: { fontFamily: font.bold, fontSize: fontSize.sm, color: "#fff" },

  /* Skeleton */
  skeletonWrap: { padding: spacing.lg, gap: spacing.md },
  skeletonCard: {
    padding: spacing.lg,
    borderRadius: radius.lg,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
  },
  skeletonBar: { height: 12, borderRadius: 6, backgroundColor: colors.surfaceTertiary },

  /* Forbidden */
  forbiddenWrap: { flex: 1, alignItems: "center", justifyContent: "center", gap: spacing.md },
  forbiddenText: { fontFamily: font.medium, fontSize: fontSize.lg, color: colors.muted },

  /* Compose Sheet */
  sheetHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.xl,
    paddingBottom: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    backgroundColor: colors.surface,
  },
  sheetCancel: { fontFamily: font.medium, fontSize: fontSize.base, color: colors.brand },
  sheetTitle: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  sheetSend: { fontFamily: font.bold, fontSize: fontSize.base, color: colors.brand },

  fieldLabel: {
    fontFamily: font.bold,
    fontSize: 11,
    textTransform: "uppercase",
    letterSpacing: 0.6,
    color: colors.muted,
    marginTop: spacing.lg,
    marginBottom: spacing.xs,
  },
  channelRow: { flexDirection: "row", gap: spacing.xl },
  channelItem: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  channelText: { fontFamily: font.medium, fontSize: fontSize.base, color: colors.onSurface },

  input: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.md,
    fontFamily: font.regular,
    fontSize: fontSize.base,
    color: colors.onSurface,
  },

  previewBox: {
    marginTop: spacing.lg,
    padding: spacing.md,
    borderRadius: radius.md,
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.border,
  },
  previewLabel: {
    fontFamily: font.bold,
    fontSize: 11,
    textTransform: "uppercase",
    letterSpacing: 0.6,
    color: colors.muted,
    marginBottom: spacing.sm,
  },
  previewSummary: { fontFamily: font.medium, fontSize: fontSize.base, color: colors.onSurface },
  previewMeta: { fontFamily: font.regular, fontSize: 11, color: colors.muted, marginTop: 4 },
  previewPlaceholder: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  errorRow: { flexDirection: "row", alignItems: "center", gap: 4, marginBottom: spacing.xs },
  errorRowText: { fontFamily: font.medium, fontSize: fontSize.sm, color: "#DC2626" },

  successBanner: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    padding: spacing.md,
    borderRadius: radius.md,
    backgroundColor: "#DCFCE7",
    borderWidth: 1,
    borderColor: "#86EFAC",
    marginBottom: spacing.md,
  },
  successText: { fontFamily: font.medium, fontSize: fontSize.sm, color: "#166534", flex: 1 },

  /* Confirm dialog */
  confirmOverlay: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.5)",
    justifyContent: "center",
    alignItems: "center",
    padding: spacing.xl,
  },
  confirmBox: {
    width: "100%",
    maxWidth: 360,
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.xl,
  },
  confirmTitle: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface },
  confirmDesc: {
    fontFamily: font.regular,
    fontSize: fontSize.base,
    color: colors.onSurfaceSecondary,
    marginTop: spacing.sm,
    lineHeight: 22,
  },
  confirmBtns: {
    flexDirection: "row",
    justifyContent: "flex-end",
    gap: spacing.md,
    marginTop: spacing.xl,
  },
  confirmCancelBtn: {
    paddingHorizontal: 20,
    paddingVertical: 10,
    borderRadius: radius.sm,
    backgroundColor: colors.surfaceSecondary,
  },
  confirmCancelText: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  confirmSendBtn: {
    paddingHorizontal: 20,
    paddingVertical: 10,
    borderRadius: radius.sm,
    backgroundColor: "#DC2626",
  },
  confirmSendText: { fontFamily: font.bold, fontSize: fontSize.base, color: "#fff" },
});
