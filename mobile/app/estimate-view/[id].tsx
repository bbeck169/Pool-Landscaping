/**
 * Estimate Viewer + Phase A Line-Item Decline + Top-Level Approve/Decline.
 *
 * Fetches GET /api/quotes/{id}/full (canonical).
 * Renders: company header, bill-to, line items (with per-line decline),
 * totals (with adjusted-total block), notes, status.
 *
 * Phase A features:
 *   - Per-line decline button + decline modal with optional reason
 *   - Declined line strike-through + "Declined" chip + undecline
 *   - Top-level Approve (green) / Decline (red) toolbar
 *   - Adjusted totals (original strikethrough → adjusted bold)
 *   - Accepted/Declined pill
 *   - Status guards: actions only when status in {sent, viewed}
 *   - 409 already_finalized → friendly toast
 */
import React, { useCallback, useEffect, useState, useRef } from "react";
import {
  View, Text, ScrollView, StyleSheet, TouchableOpacity,
  ActivityIndicator, Alert, Modal, TextInput, KeyboardAvoidingView, Platform,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useLocalSearchParams, useRouter } from "expo-router";

import { useAuth } from "@/src/auth";
import {
  getEstimateFull, acceptEstimate, declineEstimate, requestEstimateChanges,
  fetchMagicLinkToken, declineLineItem, undeclineLineItem,
  approveViaToken, declineViaToken,
  type EstimateFull,
} from "@/src/api/estimatesFull";
import { InvoiceAttachments } from "@/src/components/files";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";

const fmt = (n: number | undefined) => "$" + (n || 0).toFixed(2);

export default function EstimateViewScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { user } = useAuth();

  const [data, setData] = useState<EstimateFull | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [declineOpen, setDeclineOpen] = useState(false);
  const [declineMsg, setDeclineMsg] = useState("");
  const [changesOpen, setChangesOpen] = useState(false);
  const [changesMsg, setChangesMsg] = useState("");
  // Phase A state
  const [magicToken, setMagicToken] = useState<string | null>(null);
  const [busyLineIdx, setBusyLineIdx] = useState<number | null>(null);
  const [lineDeclineOpen, setLineDeclineOpen] = useState<number | null>(null);
  const [lineDeclineReason, setLineDeclineReason] = useState("");
  const [toast, setToast] = useState("");
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const showToast = (msg: string, ms = 2500) => {
    if (toastTimer.current) clearTimeout(toastTimer.current);
    setToast(msg);
    toastTimer.current = setTimeout(() => setToast(""), ms);
  };

  const load = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    setError("");
    try {
      const d = await getEstimateFull(id);
      setData(d);
      // Fetch magic-link token for Phase A line-item operations
      const tok = await fetchMagicLinkToken(id);
      setMagicToken(tok);
    } catch (e: any) {
      setError(e?.message || "Failed to load estimate");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => { load(); }, [load]);

  // Derived state
  const statusLc = String(data?.status || "").toLowerCase();
  const actionable = statusLc === "sent" || statusLc === "viewed";
  const locked = data?.decision === "accepted" || data?.decision === "declined";

  // ── Top-level approve ──────────────────────────────────────────
  const onApprove = () => {
    Alert.alert("Approve Estimate", "Are you sure you want to approve this estimate?", [
      { text: "Cancel", style: "cancel" },
      {
        text: "Approve", style: "default", onPress: async () => {
          setBusy(true);
          try {
            if (magicToken) {
              const res = await approveViaToken(magicToken);
              if (res) setData(res);
              else await load();
            } else {
              const res = await acceptEstimate(id!);
              if (res) setData(res);
              else await load();
            }
            showToast("Estimate approved");
          } catch (e: any) {
            const code = e?.error_code || e?.response?.error_code;
            if (code === "already_finalized") {
              showToast("This estimate has already been finalized.", 3000);
              await load();
            } else {
              Alert.alert("Error", e?.message || "Failed to approve");
            }
          } finally {
            setBusy(false);
          }
        },
      },
    ]);
  };

  // ── Top-level decline ──────────────────────────────────────────
  const onSubmitDecline = async () => {
    setBusy(true);
    try {
      if (magicToken) {
        const res = await declineViaToken(magicToken, declineMsg);
        if (res) setData(res);
        else await load();
      } else {
        const res = await declineEstimate(id!, declineMsg);
        if (res) setData(res);
        else await load();
      }
      setDeclineOpen(false);
      setDeclineMsg("");
      showToast("Estimate declined");
    } catch (e: any) {
      const code = e?.error_code || e?.response?.error_code;
      if (code === "already_finalized") {
        showToast("This estimate has already been finalized.", 3000);
        setDeclineOpen(false);
        setDeclineMsg("");
        await load();
      } else {
        Alert.alert("Error", e?.message || "Failed to decline");
      }
    } finally {
      setBusy(false);
    }
  };

  // ── Request changes ────────────────────────────────────────────
  const onRequestChanges = async () => {
    if (!changesMsg.trim()) return;
    setBusy(true);
    try {
      const res = await requestEstimateChanges(id!, changesMsg);
      if (res) setData(res);
      else await load();
      setChangesOpen(false);
      setChangesMsg("");
      showToast("Change request sent");
    } catch (e: any) {
      Alert.alert("Error", e?.message || "Failed to send");
    } finally {
      setBusy(false);
    }
  };

  // ── Per-line decline ───────────────────────────────────────────
  const submitLineDecline = async () => {
    if (lineDeclineOpen === null || !magicToken) return;
    setBusyLineIdx(lineDeclineOpen);
    try {
      const res = await declineLineItem(magicToken, lineDeclineOpen, lineDeclineReason);
      if (res) setData(res);
      else await load();
      showToast("Line item declined");
    } catch (e: any) {
      showToast(e?.message || "Failed to decline line", 3000);
    } finally {
      setBusyLineIdx(null);
      setLineDeclineOpen(null);
      setLineDeclineReason("");
    }
  };

  const onUndeclineLine = async (idx: number) => {
    if (!magicToken) return;
    setBusyLineIdx(idx);
    try {
      const res = await undeclineLineItem(magicToken, idx);
      if (res) setData(res);
      else await load();
      showToast("Line item restored");
    } catch (e: any) {
      showToast(e?.message || "Failed to restore line", 3000);
    } finally {
      setBusyLineIdx(null);
    }
  };

  // ── Loading / error states ─────────────────────────────────────
  if (loading) {
    return (
      <View style={[s.center, { paddingTop: insets.top + 60 }]}>
        <ActivityIndicator size="large" color={colors.brand} />
      </View>
    );
  }

  if (error || !data) {
    return (
      <View style={[s.center, { paddingTop: insets.top + 60 }]}>
        <Ionicons name="alert-circle" size={32} color={colors.error} />
        <Text style={s.errorText}>{error || "Estimate not found"}</Text>
        <TouchableOpacity onPress={() => router.back()} style={s.backBtn}>
          <Text style={s.backBtnText}>Go Back</Text>
        </TouchableOpacity>
      </View>
    );
  }

  const { company, bill_to, property_address, header, line_items, totals, notes, title, decision, accepted_at, declined_at, as_customer } = data;
  const canLineDecline = actionable && !locked && !!magicToken;

  return (
    <View style={[s.root, { paddingTop: insets.top }]}>
      <View style={s.navBar}>
        <TouchableOpacity onPress={() => router.back()} hitSlop={12} testID="estimate-back-btn">
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </TouchableOpacity>
        <Text style={s.navTitle}>Estimate</Text>
        <View style={{ width: 22 }} />
      </View>

      {/* Toast */}
      {toast ? (
        <View style={s.toast} testID="estimate-toast">
          <Text style={s.toastText}>{toast}</Text>
        </View>
      ) : null}

      <ScrollView contentContainerStyle={s.scroll} showsVerticalScrollIndicator={false}>
        {/* Accepted/Declined pill */}
        {locked && (
          <View
            style={[s.lockedBanner, decision === "accepted" ? s.acceptedBanner : s.declinedBanner]}
            testID={decision === "accepted" ? "estimate-accepted-pill" : "estimate-declined-pill"}
          >
            <Ionicons name={decision === "accepted" ? "checkmark-circle" : "close-circle"} size={18} color={decision === "accepted" ? "#166534" : "#991B1B"} />
            <Text style={[s.lockedText, { color: decision === "accepted" ? "#166534" : "#991B1B" }]}>
              {decision === "accepted" ? `Accepted on ${String(accepted_at || "").slice(0, 10)}` : `Declined on ${String(declined_at || "").slice(0, 10)}`}
            </Text>
          </View>
        )}

        {/* Header card */}
        <View style={s.card} testID="estimate-header-card">
          <View style={s.statusRow}>
            <View style={[s.statusPill, { backgroundColor: decision === "accepted" ? "#DCFCE7" : decision === "declined" ? "#FEE2E2" : "#E0F2FE" }]}>
              <Text style={[s.statusText, { color: decision === "accepted" ? "#166534" : decision === "declined" ? "#991B1B" : "#0369A1" }]}>
                {(data.status || "draft").toUpperCase()}
              </Text>
            </View>
          </View>
          {title ? <Text style={s.estTitle}>{title}</Text> : null}
          <Text style={s.estNum} testID="estimate-number">Estimate #{header.estimate_number}</Text>
          <Text style={s.estDate}>{header.estimate_date}</Text>
          {header.expiration_date && <Text style={s.expiry}>Expires: {header.expiration_date}</Text>}
          <View style={s.totalRow}>
            <Text style={s.totalAmount} testID="estimate-total">{fmt(totals.total_estimated_cost)}</Text>
            <Text style={s.totalLabel}>Total Estimated Cost</Text>
          </View>
        </View>

        {/* Top-level Approve/Decline toolbar — Phase A */}
        {!locked && actionable && (
          <View style={s.actionRow}>
            <TouchableOpacity style={s.approveBtn} onPress={onApprove} disabled={busy} testID="estimate-toolbar-customer-approve">
              <Ionicons name="checkmark" size={18} color="#fff" />
              <Text style={s.approveBtnText}>Approve</Text>
            </TouchableOpacity>
            <TouchableOpacity style={s.toolbarDeclineBtn} onPress={() => setDeclineOpen(true)} disabled={busy} testID="estimate-toolbar-customer-decline">
              <Ionicons name="close" size={18} color="#fff" />
              <Text style={s.toolbarDeclineBtnText}>Decline</Text>
            </TouchableOpacity>
            <TouchableOpacity style={s.changesBtn} onPress={() => setChangesOpen(true)} disabled={busy} testID="estimate-changes-btn">
              <Ionicons name="chatbubble-ellipses" size={16} color={colors.brand} />
              <Text style={s.changesBtnText}>Changes</Text>
            </TouchableOpacity>
          </View>
        )}

        {/* Legacy action buttons for non-actionable, non-locked states */}
        {!locked && !actionable && (
          <View style={s.actionRow}>
            <TouchableOpacity style={s.approveBtn} onPress={onApprove} disabled={busy} testID="estimate-accept-btn">
              <Ionicons name="checkmark" size={18} color="#fff" />
              <Text style={s.approveBtnText}>Accept</Text>
            </TouchableOpacity>
            <TouchableOpacity style={s.toolbarDeclineBtn} onPress={() => setDeclineOpen(true)} disabled={busy} testID="estimate-decline-btn">
              <Ionicons name="close" size={18} color="#fff" />
              <Text style={s.toolbarDeclineBtnText}>Decline</Text>
            </TouchableOpacity>
            <TouchableOpacity style={s.changesBtn} onPress={() => setChangesOpen(true)} disabled={busy} testID="estimate-changes-btn">
              <Ionicons name="chatbubble-ellipses" size={16} color={colors.brand} />
              <Text style={s.changesBtnText}>Changes</Text>
            </TouchableOpacity>
          </View>
        )}

        {/* Company */}
        <View style={s.card}>
          <Text style={s.sectionLabel}>FROM</Text>
          <Text style={s.companyName}>{company.name}</Text>
          {company.address ? <Text style={s.muted}>{company.address}</Text> : null}
          {company.phone ? <Text style={[s.muted, { color: colors.brand }]}>{company.phone}</Text> : null}
        </View>

        {/* Bill To */}
        <View style={s.card}>
          <Text style={s.sectionLabel}>PREPARED FOR</Text>
          <Text style={s.billName}>{bill_to.name || "—"}</Text>
          {bill_to.address ? <Text style={s.muted}>{bill_to.address}</Text> : null}
          {property_address ? <Text style={[s.muted, { marginTop: 4 }]}><Text style={{ fontFamily: font.semibold }}>Property: </Text>{property_address}</Text> : null}
        </View>

        {/* Line Items */}
        <View style={s.card} testID="estimate-line-items">
          <Text style={s.sectionLabel}>LINE ITEMS</Text>
          {line_items.length === 0 ? (
            <Text style={s.muted}>No line items</Text>
          ) : (
            line_items.map((li, i) => {
              const isDeclined = (li.customer_status || "pending") === "declined";
              return (
                <View key={i} style={[s.lineRow, isDeclined && s.lineRowDeclined]} testID={`estimate-line-item-${i}`}>
                  <View style={{ flex: 1 }}>
                    <View style={{ flexDirection: "row", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                      <Text style={[s.lineDesc, isDeclined && s.lineDeclinedText]}>{li.description}</Text>
                      {isDeclined && (
                        <View style={s.declinedChip} testID={`estimate-line-item-declined-chip-${i}`}>
                          <Text style={s.declinedChipText}>Declined</Text>
                        </View>
                      )}
                    </View>
                    <Text style={[s.lineDetail, isDeclined && s.lineDeclinedText]}>
                      {li.qty_hr || li.quantity || 0} qty × {li.visits || 1} visit{(li.visits || 1) > 1 ? "s" : ""}
                    </Text>
                  </View>
                  <View style={{ alignItems: "flex-end", gap: 6 }}>
                    <Text style={[s.lineTotal, isDeclined && s.lineDeclinedText]}>{fmt(li.total)}</Text>
                    {canLineDecline && (
                      isDeclined ? (
                        <TouchableOpacity
                          onPress={() => onUndeclineLine(i)}
                          disabled={busyLineIdx === i}
                          style={s.undeclineBtn}
                          testID={`estimate-line-item-undecline-${i}`}
                        >
                          <Text style={s.undeclineBtnText}>
                            {busyLineIdx === i ? "…" : "Undo"}
                          </Text>
                        </TouchableOpacity>
                      ) : (
                        <TouchableOpacity
                          onPress={() => setLineDeclineOpen(i)}
                          disabled={busyLineIdx === i}
                          style={s.lineDeclineBtn}
                          testID={`estimate-line-item-decline-${i}`}
                        >
                          <Text style={s.lineDeclineBtnText}>
                            {busyLineIdx === i ? "…" : "Decline"}
                          </Text>
                        </TouchableOpacity>
                      )
                    )}
                  </View>
                </View>
              );
            })
          )}
        </View>

        {/* Totals */}
        <View style={s.card} testID="estimate-totals">
          <View style={s.totalsRow}><Text style={s.totalsLabel}>Subtotal</Text><Text style={s.totalsValue}>{fmt(totals.subtotal)}</Text></View>
          <View style={s.totalsRow}><Text style={s.totalsLabel}>Taxes</Text><Text style={s.totalsValue}>{fmt(totals.taxes)}</Text></View>
          <View style={s.totalsRow}><Text style={s.totalsLabel}>Amount Paid</Text><Text style={s.totalsValue}>{fmt(totals.amount_paid)}</Text></View>
          <View style={[s.totalsRow, s.totalHighlight]}>
            <Text style={s.totalsLabelBold}>Total Estimated Cost</Text>
            <Text style={s.totalsValueBold}>{fmt(totals.total_estimated_cost)}</Text>
          </View>
          {/* Phase A — Adjusted totals row */}
          {totals.has_declined_lines && (
            <View style={[s.totalsRow, { marginTop: 8 }]} testID="estimate-totals-adjusted-row">
              <Text style={s.totalsLabel}>Adjusted for declined</Text>
              <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
                <Text style={s.originalTotal} testID="estimate-totals-original">{fmt(totals.original_total)}</Text>
                <Text style={s.adjustedTotal} testID="estimate-totals-adjusted">{fmt(totals.adjusted_total)}</Text>
              </View>
            </View>
          )}
          {!as_customer && totals.estimated_profit != null && (
            <>
              <View style={s.totalsRow}><Text style={s.totalsLabel}>Est. Profit</Text><Text style={s.totalsValue}>{fmt(totals.estimated_profit)}</Text></View>
              <View style={s.totalsRow}><Text style={s.totalsLabel}>Total B.Hrs</Text><Text style={s.totalsValue}>{fmt(totals.total_b_hrs)}</Text></View>
            </>
          )}
        </View>

        {/* Notes */}
        {notes ? (
          <View style={s.card} testID="estimate-notes">
            <Text style={s.sectionLabel}>NOTES</Text>
            <Text style={s.notesText}>{notes}</Text>
          </View>
        ) : null}

        {/* Attachments */}
        <InvoiceAttachments docId={id!} isInvoice={false} user={user} />

        {/* Disclaimer */}
        <View style={s.disclaimer}>
          <Text style={s.disclaimerText}>
            This estimate is a good faith estimate only and is not a guarantee of final cost.
          </Text>
        </View>
      </ScrollView>

      {/* Per-line decline modal — Phase A */}
      <Modal visible={lineDeclineOpen !== null} transparent animationType="fade" testID="estimate-line-item-decline-dialog">
        <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={s.modalOverlay}>
          <View style={s.modalCard}>
            <Text style={s.modalTitle}>Decline this line item?</Text>
            <Text style={s.modalHelp}>
              {lineDeclineOpen !== null
                ? `You're telling us you don't want "${line_items[lineDeclineOpen]?.description || "this item"}" (${fmt(line_items[lineDeclineOpen]?.total)}). Your total will adjust automatically.`
                : ""}
            </Text>
            <TextInput
              style={s.modalInput}
              value={lineDeclineReason}
              onChangeText={(t) => setLineDeclineReason(t.slice(0, 200))}
              multiline
              numberOfLines={2}
              placeholder="Optional reason (max 200 chars)"
              placeholderTextColor={colors.muted}
              testID="estimate-line-item-decline-reason"
            />
            <View style={s.modalActions}>
              <TouchableOpacity
                onPress={() => { setLineDeclineOpen(null); setLineDeclineReason(""); }}
                style={s.modalCancel}
                testID="estimate-line-item-decline-cancel"
              >
                <Text style={s.modalCancelText}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity
                onPress={submitLineDecline}
                style={s.modalDeclineBtn}
                disabled={busyLineIdx !== null}
                testID="estimate-line-item-decline-confirm"
              >
                <Text style={s.modalDeclineBtnText}>{busyLineIdx !== null ? "Declining…" : "Decline this line"}</Text>
              </TouchableOpacity>
            </View>
          </View>
        </KeyboardAvoidingView>
      </Modal>

      {/* Top-level decline modal */}
      <Modal visible={declineOpen} transparent animationType="fade" testID="estimate-decline-modal">
        <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={s.modalOverlay}>
          <View style={s.modalCard}>
            <Text style={s.modalTitle}>Decline Estimate</Text>
            <Text style={s.modalHelp}>Optional — let us know why so we can improve.</Text>
            <TextInput style={s.modalInput} value={declineMsg} onChangeText={setDeclineMsg} multiline numberOfLines={3} placeholder="Reason (optional)" placeholderTextColor={colors.muted} testID="estimate-decline-reason" />
            <View style={s.modalActions}>
              <TouchableOpacity onPress={() => setDeclineOpen(false)} style={s.modalCancel}><Text style={s.modalCancelText}>Cancel</Text></TouchableOpacity>
              <TouchableOpacity onPress={onSubmitDecline} style={s.modalDeclineBtn} disabled={busy} testID="estimate-decline-confirm">
                <Text style={s.modalDeclineBtnText}>{busy ? "Declining…" : "Decline"}</Text>
              </TouchableOpacity>
            </View>
          </View>
        </KeyboardAvoidingView>
      </Modal>

      {/* Changes modal */}
      <Modal visible={changesOpen} transparent animationType="fade" testID="estimate-changes-modal">
        <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={s.modalOverlay}>
          <View style={s.modalCard}>
            <Text style={s.modalTitle}>Request Changes</Text>
            <Text style={s.modalHelp}>Tell us what you&apos;d like changed.</Text>
            <TextInput style={s.modalInput} value={changesMsg} onChangeText={setChangesMsg} multiline numberOfLines={4} placeholder="Describe the changes..." placeholderTextColor={colors.muted} testID="estimate-changes-message" />
            <View style={s.modalActions}>
              <TouchableOpacity onPress={() => setChangesOpen(false)} style={s.modalCancel}><Text style={s.modalCancelText}>Cancel</Text></TouchableOpacity>
              <TouchableOpacity onPress={onRequestChanges} style={s.modalSendBtn} disabled={busy || !changesMsg.trim()} testID="estimate-changes-confirm">
                <Text style={s.modalSendBtnText}>{busy ? "Sending…" : "Send"}</Text>
              </TouchableOpacity>
            </View>
          </View>
        </KeyboardAvoidingView>
      </Modal>
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: "#F8FAFC" },
  center: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface, padding: 20 },
  errorText: { fontFamily: font.medium, fontSize: fontSize.base, color: colors.error, marginTop: 8, textAlign: "center" },
  backBtn: { marginTop: 16, paddingHorizontal: 20, paddingVertical: 10, borderRadius: radius.md, backgroundColor: colors.brand },
  backBtnText: { fontFamily: font.semibold, fontSize: fontSize.base, color: "#fff" },
  navBar: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.lg, paddingVertical: spacing.md, borderBottomWidth: 1, borderBottomColor: colors.border, backgroundColor: colors.surface },
  navTitle: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  scroll: { padding: spacing.lg, paddingBottom: 40 },
  toast: { position: "absolute", top: 8, left: 20, right: 20, zIndex: 99, backgroundColor: "#1E293B", borderRadius: radius.md, paddingVertical: 10, paddingHorizontal: 16, alignItems: "center" },
  toastText: { fontFamily: font.medium, fontSize: fontSize.sm, color: "#fff" },
  lockedBanner: { flexDirection: "row", alignItems: "center", gap: 8, padding: spacing.md, borderRadius: radius.md, marginBottom: spacing.md },
  acceptedBanner: { backgroundColor: "#DCFCE7" },
  declinedBanner: { backgroundColor: "#FEE2E2" },
  lockedText: { fontFamily: font.semibold, fontSize: fontSize.sm },
  card: { backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.lg, marginBottom: spacing.md, borderWidth: 1, borderColor: colors.border },
  sectionLabel: { fontFamily: font.bold, fontSize: 10, color: colors.muted, textTransform: "uppercase", letterSpacing: 1, marginBottom: spacing.sm },
  statusRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm, marginBottom: spacing.sm },
  statusPill: { paddingHorizontal: 10, paddingVertical: 3, borderRadius: 999 },
  statusText: { fontFamily: font.bold, fontSize: 10, letterSpacing: 0.5 },
  estTitle: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface, marginBottom: 4 },
  estNum: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  estDate: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
  expiry: { fontFamily: font.medium, fontSize: fontSize.sm, color: "#C2410C", marginTop: 4 },
  totalRow: { marginTop: spacing.md, alignItems: "flex-end" },
  totalAmount: { fontFamily: font.bold, fontSize: fontSize["2xl"], color: colors.brand },
  totalLabel: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
  // Phase A — Approve (GREEN) / Decline (RED) toolbar
  actionRow: { flexDirection: "row", gap: spacing.sm, marginBottom: spacing.md },
  approveBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, backgroundColor: colors.success, paddingVertical: 14, borderRadius: radius.md },
  approveBtnText: { fontFamily: font.bold, fontSize: fontSize.base, color: "#fff" },
  toolbarDeclineBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, backgroundColor: "#DC2626", paddingVertical: 14, borderRadius: radius.md },
  toolbarDeclineBtnText: { fontFamily: font.bold, fontSize: fontSize.base, color: "#fff" },
  changesBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, backgroundColor: colors.surface, paddingVertical: 14, paddingHorizontal: 16, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border },
  changesBtnText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.brand },
  companyName: { fontFamily: font.bold, fontSize: fontSize.base, color: colors.onSurface },
  billName: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  muted: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
  // Line items — Phase A
  lineRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start", paddingVertical: spacing.sm, borderBottomWidth: 1, borderBottomColor: colors.border },
  lineRowDeclined: { opacity: 0.55 },
  lineDesc: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface },
  lineDeclinedText: { textDecorationLine: "line-through", color: colors.muted },
  lineDetail: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
  lineTotal: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface, marginLeft: 12 },
  declinedChip: { backgroundColor: "#FEE2E2", paddingHorizontal: 6, paddingVertical: 2, borderRadius: 6 },
  declinedChipText: { fontFamily: font.bold, fontSize: 11, color: "#7F1D1D" },
  lineDeclineBtn: { paddingHorizontal: 8, paddingVertical: 4, borderRadius: radius.sm, borderWidth: 1, borderColor: colors.error },
  lineDeclineBtnText: { fontFamily: font.semibold, fontSize: 12, color: colors.error },
  undeclineBtn: { paddingHorizontal: 8, paddingVertical: 4, borderRadius: radius.sm, borderWidth: 1, borderColor: colors.brand },
  undeclineBtnText: { fontFamily: font.semibold, fontSize: 12, color: colors.brand },
  // Totals — Phase A adjusted block
  totalsRow: { flexDirection: "row", justifyContent: "space-between", paddingVertical: 6 },
  totalsLabel: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted },
  totalsValue: { fontFamily: font.medium, fontSize: fontSize.base, color: colors.onSurface },
  totalHighlight: { borderTopWidth: 1, borderTopColor: colors.border, paddingTop: spacing.sm, marginTop: spacing.xs },
  totalsLabelBold: { fontFamily: font.bold, fontSize: fontSize.base, color: colors.brand },
  totalsValueBold: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.brand },
  originalTotal: { fontFamily: font.regular, fontSize: fontSize.base, color: "#9CA3AF", textDecorationLine: "line-through" },
  adjustedTotal: { fontFamily: font.bold, fontSize: fontSize.base, color: colors.onSurface },
  notesText: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, lineHeight: 22 },
  disclaimer: { padding: spacing.md, marginBottom: 20 },
  disclaimerText: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, fontStyle: "italic", textAlign: "center", lineHeight: 18 },
  // Modals
  modalOverlay: { flex: 1, backgroundColor: "rgba(15,23,42,0.5)", justifyContent: "center", padding: 20 },
  modalCard: { backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.xl },
  modalTitle: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  modalHelp: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 4, marginBottom: spacing.md, lineHeight: 20 },
  modalInput: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.sm, padding: spacing.md, fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, minHeight: 80, textAlignVertical: "top", borderWidth: 1, borderColor: colors.border },
  modalActions: { flexDirection: "row", justifyContent: "flex-end", gap: spacing.sm, marginTop: spacing.lg },
  modalCancel: { paddingHorizontal: 16, paddingVertical: 10, borderRadius: radius.sm },
  modalCancelText: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.muted },
  modalDeclineBtn: { paddingHorizontal: 16, paddingVertical: 10, borderRadius: radius.sm, backgroundColor: colors.error },
  modalDeclineBtnText: { fontFamily: font.semibold, fontSize: fontSize.base, color: "#fff" },
  modalSendBtn: { paddingHorizontal: 16, paddingVertical: 10, borderRadius: radius.sm, backgroundColor: colors.brand },
  modalSendBtnText: { fontFamily: font.semibold, fontSize: fontSize.base, color: "#fff" },
});
