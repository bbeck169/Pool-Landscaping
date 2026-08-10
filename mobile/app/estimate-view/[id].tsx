/**
 * Estimate Viewer + Accept/Decline.
 *
 * Fetches GET /api/estimates/{id}/full.
 * Renders: company header, bill-to, line items, totals, notes, status.
 * Buttons: Accept, Decline, Request Changes.
 *
 * Tech pricing guardrail: the `as_customer` flag from the API controls
 * which columns are visible. We trust the API — do NOT re-derive pricing.
 */
import React, { useCallback, useEffect, useState } from "react";
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

  const load = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    setError("");
    try {
      setData(await getEstimateFull(id));
    } catch (e: any) {
      setError(e?.message || "Failed to load estimate");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => { load(); }, [load]);

  const onAccept = async () => {
    Alert.alert("Accept Estimate", "Are you sure you want to accept this estimate?", [
      { text: "Cancel", style: "cancel" },
      {
        text: "Accept", style: "default", onPress: async () => {
          setBusy(true);
          try {
            const res = await acceptEstimate(id!);
            if (res) setData(res);
            else await load();
            Alert.alert("Accepted", "Estimate accepted successfully.");
          } catch (e: any) {
            Alert.alert("Error", e?.message || "Failed to accept");
          } finally {
            setBusy(false);
          }
        },
      },
    ]);
  };

  const onDecline = async () => {
    setBusy(true);
    try {
      const res = await declineEstimate(id!, declineMsg);
      if (res) setData(res);
      else await load();
      setDeclineOpen(false);
      setDeclineMsg("");
      Alert.alert("Declined", "Estimate declined.");
    } catch (e: any) {
      Alert.alert("Error", e?.message || "Failed to decline");
    } finally {
      setBusy(false);
    }
  };

  const onRequestChanges = async () => {
    if (!changesMsg.trim()) return;
    setBusy(true);
    try {
      const res = await requestEstimateChanges(id!, changesMsg);
      if (res) setData(res);
      else await load();
      setChangesOpen(false);
      setChangesMsg("");
      Alert.alert("Sent", "Change request sent.");
    } catch (e: any) {
      Alert.alert("Error", e?.message || "Failed to send");
    } finally {
      setBusy(false);
    }
  };

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
  const locked = decision === "accepted" || decision === "declined";

  return (
    <View style={[s.root, { paddingTop: insets.top }]}>
      <View style={s.navBar}>
        <TouchableOpacity onPress={() => router.back()} hitSlop={12} testID="estimate-back-btn">
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </TouchableOpacity>
        <Text style={s.navTitle}>Estimate</Text>
        <View style={{ width: 22 }} />
      </View>

      <ScrollView contentContainerStyle={s.scroll} showsVerticalScrollIndicator={false}>
        {/* Status banner */}
        {locked && (
          <View style={[s.lockedBanner, decision === "accepted" ? s.acceptedBanner : s.declinedBanner]} testID={`estimate-${decision}-pill`}>
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

        {/* Action buttons */}
        {!locked && (
          <View style={s.actionRow}>
            <TouchableOpacity style={s.acceptBtn} onPress={onAccept} disabled={busy} testID="estimate-accept-btn">
              <Ionicons name="checkmark" size={18} color="#fff" />
              <Text style={s.acceptBtnText}>Accept</Text>
            </TouchableOpacity>
            <TouchableOpacity style={s.declineBtn} onPress={() => setDeclineOpen(true)} disabled={busy} testID="estimate-decline-btn">
              <Ionicons name="close" size={18} color={colors.error} />
              <Text style={s.declineBtnText}>Decline</Text>
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
            line_items.map((li, i) => (
              <View key={i} style={s.lineRow} testID={`estimate-line-item-${i}`}>
                <View style={{ flex: 1 }}>
                  <Text style={s.lineDesc}>{li.description}</Text>
                  <Text style={s.lineDetail}>
                    {li.qty_hr || li.quantity || 0} qty × {li.visits || 1} visit{(li.visits || 1) > 1 ? "s" : ""}
                  </Text>
                </View>
                <Text style={s.lineTotal}>{fmt(li.total)}</Text>
              </View>
            ))
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

        {/* F2b — Attachments */}
        <InvoiceAttachments docId={id!} isInvoice={false} user={user} />

        {/* Disclaimer */}
        <View style={s.disclaimer}>
          <Text style={s.disclaimerText}>
            This estimate is a good faith estimate only and is not a guarantee of final cost.
          </Text>
        </View>
      </ScrollView>

      {/* Decline modal */}
      <Modal visible={declineOpen} transparent animationType="fade" testID="estimate-decline-modal">
        <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={s.modalOverlay}>
          <View style={s.modalCard}>
            <Text style={s.modalTitle}>Decline Estimate</Text>
            <Text style={s.modalHelp}>Optional — let us know why so we can improve.</Text>
            <TextInput style={s.modalInput} value={declineMsg} onChangeText={setDeclineMsg} multiline numberOfLines={3} placeholder="Reason (optional)" placeholderTextColor={colors.muted} testID="estimate-decline-reason" />
            <View style={s.modalActions}>
              <TouchableOpacity onPress={() => setDeclineOpen(false)} style={s.modalCancel}><Text style={s.modalCancelText}>Cancel</Text></TouchableOpacity>
              <TouchableOpacity onPress={onDecline} style={s.modalDeclineBtn} disabled={busy} testID="estimate-decline-confirm">
                <Text style={s.modalDeclineBtnText}>{busy ? "Declining..." : "Decline"}</Text>
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
                <Text style={s.modalSendBtnText}>{busy ? "Sending..." : "Send"}</Text>
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
  actionRow: { flexDirection: "row", gap: spacing.sm, marginBottom: spacing.md },
  acceptBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, backgroundColor: colors.success, paddingVertical: 14, borderRadius: radius.md },
  acceptBtnText: { fontFamily: font.bold, fontSize: fontSize.base, color: "#fff" },
  declineBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, backgroundColor: colors.surface, paddingVertical: 14, borderRadius: radius.md, borderWidth: 1, borderColor: colors.error },
  declineBtnText: { fontFamily: font.bold, fontSize: fontSize.base, color: colors.error },
  changesBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, backgroundColor: colors.surface, paddingVertical: 14, paddingHorizontal: 16, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border },
  changesBtnText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.brand },
  companyName: { fontFamily: font.bold, fontSize: fontSize.base, color: colors.onSurface },
  billName: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  muted: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
  lineRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start", paddingVertical: spacing.sm, borderBottomWidth: 1, borderBottomColor: colors.border },
  lineDesc: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface },
  lineDetail: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
  lineTotal: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface, marginLeft: 12 },
  totalsRow: { flexDirection: "row", justifyContent: "space-between", paddingVertical: 6 },
  totalsLabel: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted },
  totalsValue: { fontFamily: font.medium, fontSize: fontSize.base, color: colors.onSurface },
  totalHighlight: { borderTopWidth: 1, borderTopColor: colors.border, paddingTop: spacing.sm, marginTop: spacing.xs },
  totalsLabelBold: { fontFamily: font.bold, fontSize: fontSize.base, color: colors.brand },
  totalsValueBold: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.brand },
  notesText: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, lineHeight: 22 },
  disclaimer: { padding: spacing.md, marginBottom: 20 },
  disclaimerText: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, fontStyle: "italic", textAlign: "center", lineHeight: 18 },
  modalOverlay: { flex: 1, backgroundColor: "rgba(15,23,42,0.5)", justifyContent: "center", padding: 20 },
  modalCard: { backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.xl },
  modalTitle: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  modalHelp: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 4, marginBottom: spacing.md },
  modalInput: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.sm, padding: spacing.md, fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, minHeight: 80, textAlignVertical: "top", borderWidth: 1, borderColor: colors.border },
  modalActions: { flexDirection: "row", justifyContent: "flex-end", gap: spacing.sm, marginTop: spacing.lg },
  modalCancel: { paddingHorizontal: 16, paddingVertical: 10, borderRadius: radius.sm },
  modalCancelText: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.muted },
  modalDeclineBtn: { paddingHorizontal: 16, paddingVertical: 10, borderRadius: radius.sm, backgroundColor: colors.error },
  modalDeclineBtnText: { fontFamily: font.semibold, fontSize: fontSize.base, color: "#fff" },
  modalSendBtn: { paddingHorizontal: 16, paddingVertical: 10, borderRadius: radius.sm, backgroundColor: colors.brand },
  modalSendBtnText: { fontFamily: font.semibold, fontSize: fontSize.base, color: "#fff" },
});
