/**
 * Chase Stalled Invites Sheet — mobile parity (Dispatch A, Feature 1).
 *
 * Two-phase bottom sheet:
 *   Phase 1 (Confirm): Preview list of the top-N stalest invited-but-
 *     never-signed-in customers + batch-size picker + Send button.
 *   Phase 2 (Summary): "Sent N. Rate-limited M. Failed K." + Done.
 *
 * Data sources:
 *   Preview:  GET /api/customers?portal_invited=any&first_access=never
 *                                &sort=stalest_first&limit=N
 *   Send:     POST /api/admin/customers/portal-invite/bulk
 *             body: { customer_ids, reason: "chase_stalled_invites" }
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  Pressable,
  ActivityIndicator,
  Modal,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { useToast } from "@/src/components/ToastProvider";
import { mapApiError } from "@/src/utils/mapApiError";

/* ------------------------------------------------------------------ */
/*  Constants                                                          */
/* ------------------------------------------------------------------ */

const DEFAULT_N = 10;
const BATCH_OPTIONS = [5, 10, 25];

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface StalledCustomer {
  id: string;
  name?: string;
  email?: string;
  phone?: string;
}

interface SendSummary {
  enqueued: number;
  rate_limited: number;
  failed: number;
}

interface Props {
  visible: boolean;
  onClose: () => void;
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function ChaseStalledInvitesSheet({ visible, onClose }: Props) {
  const { showToast } = useToast();
  const [batchN, setBatchN] = useState(DEFAULT_N);
  const [preview, setPreview] = useState<StalledCustomer[] | null>(null);
  const [loadingPreview, setLoadingPreview] = useState(false);
  const [sending, setSending] = useState(false);
  const [summary, setSummary] = useState<SendSummary | null>(null);

  // Reset on open
  useEffect(() => {
    if (visible) {
      setBatchN(DEFAULT_N);
      setPreview(null);
      setLoadingPreview(false);
      setSending(false);
      setSummary(null);
    }
  }, [visible]);

  // Fetch preview when batch size changes or sheet opens
  useEffect(() => {
    if (!visible || summary) return;
    let cancelled = false;
    setLoadingPreview(true);
    (async () => {
      try {
        const url = `/customers?portal_invited=any&first_access=never&sort=stalest_first&limit=${batchN}`;
        const r: any = await api.get(url);
        if (cancelled) return;
        const items: StalledCustomer[] = Array.isArray(r) ? r : (r?.items || []);
        setPreview(items.slice(0, batchN));
      } catch (e) {
        if (!cancelled) {
          showToast(mapApiError(e).message, "error");
          setPreview([]);
        }
      } finally {
        if (!cancelled) setLoadingPreview(false);
      }
    })();
    return () => { cancelled = true; };
  }, [visible, batchN, summary]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleSend = useCallback(async () => {
    if (!preview || preview.length === 0) return;
    setSending(true);
    try {
      const customer_ids = preview.map((c) => c.id).filter(Boolean);
      const r: any = await api.post("/admin/customers/portal-invite/bulk", {
        customer_ids,
        reason: "chase_stalled_invites",
      });
      const enqueued = typeof r?.enqueued === "number" ? r.enqueued : (r?.sent || 0);
      const rate_limited = Array.isArray(r?.rate_limited) ? r.rate_limited.length : 0;
      const failed = Array.isArray(r?.failed) ? r.failed.length : 0;
      setSummary({ enqueued, rate_limited, failed });
      if (enqueued > 0) {
        showToast(`Sent ${enqueued} portal invite${enqueued === 1 ? "" : "s"}.`);
      }
    } catch (e) {
      showToast(mapApiError(e).message, "error");
      setSummary({ enqueued: 0, rate_limited: 0, failed: preview.length });
    } finally {
      setSending(false);
    }
  }, [preview, showToast]);

  const handleClose = useCallback(() => {
    onClose();
  }, [onClose]);

  if (!visible) return null;

  const isSummary = summary !== null;
  const canSend = !loadingPreview && !sending && Boolean(preview && preview.length);

  return (
    <Modal
      visible={visible}
      transparent
      animationType="slide"
      onRequestClose={sending ? undefined : handleClose}
    >
      <Pressable
        style={s.backdrop}
        onPress={sending ? undefined : handleClose}
        testID="chase-stalled-invites-modal-backdrop"
      />
      <View style={s.sheet} testID="chase-stalled-invites-modal">
        <View style={s.handle} />

        {/* Header */}
        <View style={s.header}>
          <View style={{ flex: 1 }}>
            <Text style={s.headerTitle}>
              {isSummary ? "Chase results" : "Chase stalled invites"}
            </Text>
            {!isSummary && (
              <Text style={s.headerSubtitle}>
                {"Re-send portal invites to customers who were invited longest ago and still haven\u2019t logged in."}
              </Text>
            )}
          </View>
          <Pressable onPress={sending ? undefined : handleClose} hitSlop={12} testID="chase-invites-close-btn">
            <Ionicons name="close" size={24} color={colors.muted} />
          </Pressable>
        </View>

        {isSummary ? (
          /* ---- Phase 2: Summary ---- */
          <View style={s.body} testID="chase-invites-summary">
            <View style={s.summaryRow}>
              <Ionicons name="checkmark-circle" size={20} color="#059669" />
              <Text style={s.summaryText} testID="chase-invites-summary-enqueued">
                Sent {summary.enqueued}
              </Text>
            </View>
            <View style={s.summaryRow}>
              <Ionicons name="timer-outline" size={20} color="#D97706" />
              <Text style={s.summaryText} testID="chase-invites-summary-rate-limited">
                Rate-limited {summary.rate_limited}
              </Text>
            </View>
            <View style={s.summaryRow}>
              <Ionicons name="close-circle-outline" size={20} color="#DC2626" />
              <Text style={s.summaryText} testID="chase-invites-summary-failed">
                Failed {summary.failed}
              </Text>
            </View>

            <Pressable
              onPress={handleClose}
              style={s.doneBtn}
              testID="chase-invites-done-btn"
              accessibilityRole="button"
            >
              <Text style={s.doneBtnText}>Done</Text>
            </Pressable>
          </View>
        ) : (
          /* ---- Phase 1: Confirm ---- */
          <View style={s.body}>
            {/* Batch size picker */}
            <View style={s.batchRow}>
              <Text style={s.batchLabel}>Batch size</Text>
              <View style={s.batchOptions}>
                {BATCH_OPTIONS.map((n) => (
                  <Pressable
                    key={n}
                    onPress={() => setBatchN(n)}
                    disabled={sending}
                    style={[s.batchChip, batchN === n && s.batchChipActive]}
                    testID={`chase-invites-batch-${n}`}
                    accessibilityRole="button"
                  >
                    <Text style={[s.batchChipText, batchN === n && s.batchChipTextActive]}>
                      {n}
                    </Text>
                  </Pressable>
                ))}
              </View>
            </View>

            {/* Preview list */}
            <View style={s.previewContainer} testID="chase-invites-preview-list">
              {loadingPreview ? (
                <View style={s.previewPlaceholder}>
                  <ActivityIndicator size="small" color={colors.brand} />
                  <Text style={s.previewPlaceholderText}>Loading…</Text>
                </View>
              ) : preview && preview.length > 0 ? (
                <FlatList
                  data={preview}
                  keyExtractor={(item) => item.id}
                  style={{ maxHeight: 280 }}
                  renderItem={({ item }) => (
                    <View style={s.previewRow} testID="chase-invites-preview-row">
                      <Text style={s.previewName} numberOfLines={1}>
                        {item.name || item.email || item.id}
                      </Text>
                      <Text style={s.previewContact} numberOfLines={1}>
                        {item.email || item.phone || "no contact"}
                      </Text>
                    </View>
                  )}
                />
              ) : (
                <View style={s.previewPlaceholder} testID="chase-invites-preview-empty">
                  <Ionicons name="checkmark-done-circle-outline" size={28} color={colors.muted} />
                  <Text style={s.previewPlaceholderText}>
                    {"No stalled invites \u2014 nice work."}
                  </Text>
                </View>
              )}
            </View>

            <Text style={s.disclaimer}>
              This will re-send portal invite emails/SMS. Existing rate limits apply.
            </Text>

            {/* Action buttons */}
            <View style={s.actionRow}>
              <Pressable
                onPress={handleClose}
                disabled={sending}
                style={[s.cancelBtn, sending && { opacity: 0.5 }]}
                testID="chase-invites-cancel-btn"
                accessibilityRole="button"
              >
                <Text style={s.cancelBtnText}>Cancel</Text>
              </Pressable>
              <Pressable
                onPress={handleSend}
                disabled={!canSend}
                style={[s.sendBtn, !canSend && { opacity: 0.5 }]}
                testID="chase-invites-send-btn"
                accessibilityRole="button"
              >
                {sending ? (
                  <ActivityIndicator size="small" color="#fff" />
                ) : (
                  <Text style={s.sendBtnText}>
                    Send {preview ? preview.length : batchN} invite
                    {(preview ? preview.length : batchN) === 1 ? "" : "s"}
                  </Text>
                )}
              </Pressable>
            </View>
          </View>
        )}
      </View>
    </Modal>
  );
}

/* ------------------------------------------------------------------ */
/*  Styles                                                             */
/* ------------------------------------------------------------------ */

const s = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.45)",
  },
  sheet: {
    backgroundColor: colors.surface,
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    paddingBottom: 34,
    maxHeight: "80%",
  },
  handle: {
    width: 36,
    height: 4,
    borderRadius: 2,
    backgroundColor: colors.border,
    alignSelf: "center",
    marginTop: 10,
    marginBottom: 4,
  },
  header: {
    flexDirection: "row",
    alignItems: "flex-start",
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    gap: spacing.sm,
  },
  headerTitle: {
    fontFamily: font.bold,
    fontSize: fontSize.lg,
    color: colors.onSurface,
  },
  headerSubtitle: {
    fontFamily: font.regular,
    fontSize: fontSize.xs,
    color: colors.muted,
    marginTop: 2,
  },
  body: {
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.md,
  },
  /* Batch size */
  batchRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: spacing.md,
  },
  batchLabel: {
    fontFamily: font.semibold,
    fontSize: 10,
    textTransform: "uppercase",
    letterSpacing: 0.8,
    color: colors.muted,
  },
  batchOptions: {
    flexDirection: "row",
    gap: spacing.xs,
  },
  batchChip: {
    paddingHorizontal: 14,
    paddingVertical: 6,
    borderRadius: radius.md,
    backgroundColor: colors.background,
    borderWidth: 1,
    borderColor: colors.border,
  },
  batchChipActive: {
    backgroundColor: colors.brand,
    borderColor: colors.brand,
  },
  batchChipText: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.onSurface,
  },
  batchChipTextActive: {
    color: "#fff",
  },
  /* Preview */
  previewContainer: {
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.background,
    overflow: "hidden",
    marginBottom: spacing.sm,
  },
  previewRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  previewName: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.onSurface,
    flex: 1,
    marginRight: spacing.sm,
  },
  previewContact: {
    fontFamily: font.regular,
    fontSize: fontSize.xs,
    color: colors.muted,
    flexShrink: 0,
  },
  previewPlaceholder: {
    padding: spacing.lg,
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.sm,
  },
  previewPlaceholderText: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
  },
  disclaimer: {
    fontFamily: font.regular,
    fontSize: fontSize.xs,
    color: colors.muted,
    marginBottom: spacing.md,
  },
  /* Buttons */
  actionRow: {
    flexDirection: "row",
    justifyContent: "flex-end",
    gap: spacing.sm,
    marginTop: spacing.sm,
    paddingBottom: spacing.md,
  },
  cancelBtn: {
    paddingHorizontal: spacing.lg,
    paddingVertical: 10,
    borderRadius: radius.md,
    backgroundColor: colors.background,
    borderWidth: 1,
    borderColor: colors.border,
  },
  cancelBtnText: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.onSurface,
  },
  sendBtn: {
    paddingHorizontal: spacing.lg,
    paddingVertical: 10,
    borderRadius: radius.md,
    backgroundColor: colors.brand,
    minWidth: 120,
    alignItems: "center",
  },
  sendBtnText: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: "#fff",
  },
  /* Summary */
  summaryRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    marginBottom: spacing.sm,
  },
  summaryText: {
    fontFamily: font.semibold,
    fontSize: fontSize.base,
    color: colors.onSurface,
  },
  doneBtn: {
    marginTop: spacing.lg,
    paddingVertical: 12,
    borderRadius: radius.md,
    backgroundColor: colors.brand,
    alignItems: "center",
  },
  doneBtnText: {
    fontFamily: font.bold,
    fontSize: fontSize.base,
    color: "#fff",
  },
});
