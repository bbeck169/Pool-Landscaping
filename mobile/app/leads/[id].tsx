/**
 * Phase 8 · Lead Detail — admin/manager only.
 * GET /api/leads/:id → full lead with timeline
 * PATCH /api/leads/:id → update status
 * POST /api/leads/:id/note → add note
 * POST /api/leads/:id/close-won → convert to customer
 * POST /api/leads/:id/close-lost → close with loss_reason
 */
import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, ActivityIndicator, Alert, Linking, RefreshControl, Modal, KeyboardAvoidingView, Platform } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";

import { useAuth } from "@/src/auth";
import { api } from "@/src/api";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";
import { useToast } from "@/src/components/ToastProvider";
import AppTextInput from "@/src/components/ui/AppTextInput";
import { PhoneLink, AddressLink } from "@/src/components/customer";
import { isAdminPlus, isStrictAdmin } from "@/src/components/RoleGate";
import LeadComposeSheet, { type LeadComposeChannel } from "@/src/components/leads/LeadComposeSheet";
import LeadLinkedQuotesPanel from "@/src/components/leads/LeadLinkedQuotesPanel";

const STATUS_COLORS: Record<string, { bg: string; fg: string; label: string }> = {
  // Phase 34 · Task CC: 5 canonical snake_case statuses
  "new": { bg: "#DBEAFE", fg: "#1E3A8A", label: "New" },
  "contacted": { bg: "#FEF3C7", fg: "#854D0E", label: "Contacted" },
  "quoted": { bg: "#E0E7FF", fg: "#3730A3", label: "Quoted" },
  "closed_won": { bg: "#DCFCE7", fg: "#166534", label: "Closed – Won" },
  "closed_lost": { bg: "#FEE2E2", fg: "#991B1B", label: "Closed – Lost" },
  // Legacy backwards-compat
  "New": { bg: "#DBEAFE", fg: "#1E3A8A", label: "New" },
  "Contacted": { bg: "#FEF3C7", fg: "#854D0E", label: "Contacted" },
  "Quoted": { bg: "#E0E7FF", fg: "#3730A3", label: "Quoted" },
  "Closed Won": { bg: "#DCFCE7", fg: "#166534", label: "Closed – Won" },
  "Closed Lost": { bg: "#FEE2E2", fg: "#991B1B", label: "Closed – Lost" },
  "qualified": { bg: "#E0E7FF", fg: "#3730A3", label: "Quoted" },
  "won": { bg: "#DCFCE7", fg: "#166534", label: "Closed – Won" },
  "lost": { bg: "#FEE2E2", fg: "#991B1B", label: "Closed – Lost" },
  "On Hold": { bg: "#F1F5F9", fg: "#475569", label: "On Hold" },
  "Archived": { bg: "#E5E7EB", fg: "#374151", label: "Archived" },
  "on_hold": { bg: "#F1F5F9", fg: "#475569", label: "On Hold" },
  "archived": { bg: "#E5E7EB", fg: "#374151", label: "Archived" },
};

const SOURCE_LABELS: Record<string, string> = {
  website_form: "Website form", admin_manual: "Manual entry",
  phone: "Phone call", walk_in: "Walk-in", referral: "Referral",
  widget_chat: "Widget chat", import: "Imported", mobile_app: "Mobile app",
};

function StatusPill({ status }: { status: string }) {
  const sc = STATUS_COLORS[status] || { bg: "#F1F5F9", fg: "#475569" };
  return (
    <View style={[st.pill, { backgroundColor: sc.bg }]} testID="lead-status-pill">
      <Text style={[st.pillText, { color: sc.fg }]}>{sc.label || status || "—"}</Text>
    </View>
  );
}

function TimelineEntry({ ev }: { ev: any }) {
  const label: Record<string, string> = {
    created: "Lead created",
    status_change: `Status → ${ev.payload?.to || "?"}`,
    note_added: "Note added",
    converted_to_customer: "Converted to customer",
    archived: "Archived",
  };
  const when = ev.ts ? new Date(ev.ts).toLocaleString() : "";
  return (
    <View style={st.tlEntry} testID={`timeline-${ev.kind}`}>
      <View style={st.tlDot} />
      <View style={{ flex: 1 }}>
        <Text style={st.tlLabel}>{label[ev.kind] || ev.kind}</Text>
        <Text style={st.tlTime}>{when}</Text>
        {ev.kind === "note_added" && ev.payload?.text ? (
          <Text style={st.tlNote}>{ev.payload.text}</Text>
        ) : null}
        {ev.kind === "status_change" && ev.payload?.loss_reason ? (
          <Text style={st.tlLoss}>Reason: {ev.payload.loss_reason}</Text>
        ) : null}
      </View>
    </View>
  );
}

export default function LeadDetailScreen() {
  const insets = useSafeAreaInsets();
  const { showToast } = useToast();
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const { user } = useAuth();
  const role = String((user as any)?.role || "");
  const allowed = ["admin", "super_admin", "manager"].includes(role);
  // TD-96-mobile — manager+ send (BE lead_communications roles; owner is
  // already blocked by GET /leads/{id}, so no owner special-case).
  const canCompose = isAdminPlus(user);
  // Create Quote + linked panel: admin/super_admin (BE POST /quotes require_admin;
  // GET /leads/{id}/quotes excludes owner). Managers never see these.
  const canQuote = isStrictAdmin(user);
  const [composeChannel, setComposeChannel] = useState<LeadComposeChannel | null>(null);

  const [lead, setLead] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [noteText, setNoteText] = useState("");
  const [conversion, setConversion] = useState<any>(null);
  const [lostOpen, setLostOpen] = useState(false);
  const [lostReason, setLostReason] = useState("");
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    if (!allowed || !id) { setLoading(false); return; }
    try {
      const l = await api.get(`/leads/${id}`);
      setLead(l);
      if (l.converted_customer_id) {
        setConversion({ customer_id: l.converted_customer_id, was_merged: false });
      }
    } catch {} finally { setLoading(false); setRefreshing(false); }
  }, [id, allowed]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const setStatus = async (status: string) => {
    setBusy(true);
    try {
      const updated = await api.patch(`/leads/${id}`, { status });
      setLead(updated);
      showToast(`Marked ${status}`);
    } catch (e: any) { Alert.alert("Failed", e.message); }
    finally { setBusy(false); }
  };

  const addNote = async () => {
    const t = noteText.trim();
    if (!t) return;
    setBusy(true);
    try {
      const updated = await api.post(`/leads/${id}/note`, { text: t });
      setLead(updated);
      setNoteText("");
    } catch (e: any) { Alert.alert("Failed", e.message); }
    finally { setBusy(false); }
  };

  const closeWon = async () => {
    Alert.alert("Convert to Customer?", "This will create (or merge into) a customer record, send welcome email + SMS, and optionally enroll in a drip sequence.", [
      { text: "Cancel", style: "cancel" },
      { text: "Convert", style: "default", onPress: async () => {
        setBusy(true);
        try {
          const res = await api.post(`/leads/${id}/close-won`);
          setConversion(res);
          showToast(res.was_merged ? "Merged into existing customer" : "New customer created");
          load();
        } catch (e: any) { Alert.alert("Failed", e.message); }
        finally { setBusy(false); }
      }},
    ]);
  };

  const closeLost = async () => {
    if (lostReason.trim().length < 3) {
      Alert.alert("Reason required", "Please enter at least 3 characters.");
      return;
    }
    setBusy(true);
    try {
      const updated = await api.post(`/leads/${id}/close-lost`, { loss_reason: lostReason.trim() });
      setLead(updated);
      setLostOpen(false);
      setLostReason("");
      showToast("Lead marked as lost.");
    } catch (e: any) { Alert.alert("Failed", e.message); }
    finally { setBusy(false); }
  };

  if (!allowed) {
    return (
      <View style={[st.center, { paddingTop: insets.top + 60 }]} testID="lead-detail-role-gate">
        <Ionicons name="lock-closed" size={36} color={colors.muted} />
        <Text style={st.gateText}>Not authorized</Text>
        <Text style={st.gateSubtext}>Leads are available to admins and managers only.</Text>
        <TouchableOpacity onPress={() => router.replace("/(app)")} style={st.gateBtn}>
          <Text style={st.gateBtnText}>Go Home</Text>
        </TouchableOpacity>
      </View>
    );
  }

  if (loading) {
    return <View style={[st.center, { paddingTop: insets.top + 60 }]}><ActivityIndicator size="large" color={colors.brand} /></View>;
  }

  if (!lead) {
    return (
      <View style={[st.center, { paddingTop: insets.top + 60 }]}>
        <Text style={st.gateText}>Lead not found</Text>
        <TouchableOpacity onPress={() => router.back()} style={st.gateBtn}><Text style={st.gateBtnText}>Back</Text></TouchableOpacity>
      </View>
    );
  }

  const timeline = [...(lead.timeline || [])].reverse();
  const sourceLabel = lead.source?.startsWith("referral_from_customer:") ? "Referral" :
    lead.source?.startsWith("form:") ? `Form · ${lead.source.slice(5)}` :
    SOURCE_LABELS[lead.source] || lead.source || "—";

  const canAct = !["closed_won", "closed_lost", "archived", "won", "lost", "Closed Won", "Closed Lost", "Archived"].includes(lead.status);

  return (
    <View style={[st.root, { paddingTop: insets.top }]}>
      <View style={st.navBar}>
        <TouchableOpacity onPress={() => router.back()} hitSlop={12} testID="lead-detail-back">
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </TouchableOpacity>
        <Text style={st.navTitle} numberOfLines={1}>{lead.name}</Text>
        <TouchableOpacity onPress={load} hitSlop={12}><Ionicons name="refresh" size={20} color={colors.muted} /></TouchableOpacity>
      </View>

      <ScrollView
        contentContainerStyle={st.scroll}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.brand} />}
      >
        {/* Conversion banner */}
        {conversion?.customer_id && (
          <TouchableOpacity
            style={st.convBanner}
            onPress={() => router.push(`/customer/${conversion.customer_id}`)}
            testID="conversion-banner"
          >
            <Ionicons name="checkmark-circle" size={18} color="#166534" />
            <Text style={st.convText}>
              {conversion.was_merged ? "Merged into existing customer" : "New customer created"}
            </Text>
            <Ionicons name="arrow-forward" size={16} color="#166534" />
          </TouchableOpacity>
        )}

        {/* Contact card */}
        <View style={st.card} testID="lead-contact-card">
          <View style={st.cardHeader}>
            <Text style={st.leadName} testID="lead-name">{lead.name}</Text>
            <StatusPill status={lead.status} />
          </View>
          <View style={st.sourceRow}>
            <Ionicons name="globe-outline" size={12} color={colors.muted} />
            <Text style={st.sourceText}>{sourceLabel}</Text>
          </View>
          {lead.service_interest && (
            <Text style={st.interestText}>Interest: {lead.service_interest}</Text>
          )}
          <View style={st.contactSection}>
            {lead.phone ? (
              <PhoneLink phone={lead.phone} style={st.contactText} testID="lead-phone" />
            ) : null}
            {lead.email ? (
              <TouchableOpacity style={st.contactRow} onPress={() => Linking.openURL(`mailto:${lead.email}`)} testID="lead-email">
                <Ionicons name="mail-outline" size={16} color={colors.brand} />
                <Text style={st.contactText}>{lead.email}</Text>
              </TouchableOpacity>
            ) : null}
            {(lead.address || lead.service_address) ? (
              <AddressLink address={lead.service_address || lead.address} style={st.contactText} testID="lead-address" />
            ) : null}
          </View>
          {lead.est_value ? <Text style={st.estValue}>Est. value: ${Number(lead.est_value).toLocaleString()}</Text> : null}
        </View>

        {/* TD-96-mobile — outreach (web header SMS/Email); not status-gated like web */}
        {canCompose && (
          <View style={st.actionsCard} testID="lead-outreach-card">
            <Text style={st.sectionLabel}>REACH OUT</Text>
            <View style={st.actionsGrid}>
              <ActionBtn icon="chatbubble-ellipses-outline" label="Send SMS" color={colors.brand} onPress={() => lead.phone && setComposeChannel("sms")} disabled={!lead.phone} testID="lead-detail-send-sms" />
              <ActionBtn icon="mail-outline" label="Send Email" color={colors.brand} onPress={() => lead.email && setComposeChannel("email")} disabled={!lead.email} testID="lead-detail-send-email" />
            </View>
            {canQuote && (
              <TouchableOpacity
                style={[st.quoteBtn, busy && { opacity: 0.5 }]}
                disabled={busy}
                onPress={() => router.push(`/quote/new?recipient_type=lead&recipient_id=${encodeURIComponent(String(id))}` as any)}
                testID="lead-create-quote"
              >
                <Ionicons name="document-text-outline" size={16} color="#fff" />
                <Text style={st.quoteBtnText}>Create Quote</Text>
                {lead.quotes_count ? (
                  <View style={st.quoteCount} testID="lead-create-quote-count">
                    <Text style={st.quoteCountText}>{String(lead.quotes_count)}</Text>
                  </View>
                ) : null}
              </TouchableOpacity>
            )}
          </View>
        )}

        {/* Action buttons */}
        {canAct && (
          <View style={st.actionsCard} testID="lead-actions">
            <Text style={st.sectionLabel}>ACTIONS</Text>
            <View style={st.actionsGrid}>
              {lead.status === "New" && (
                <ActionBtn icon="chatbubble-outline" label="Contacted" color="#A16207" onPress={() => setStatus("Contacted")} busy={busy} testID="lead-action-contacted" />
              )}
              {["New", "Contacted"].includes(lead.status) && (
                <ActionBtn icon="document-text-outline" label="Quoted" color="#3730A3" onPress={() => setStatus("Quoted")} busy={busy} testID="lead-action-quoted" />
              )}
              <ActionBtn icon="pause-outline" label="On Hold" color="#475569" onPress={() => setStatus("On Hold")} busy={busy} testID="lead-action-onhold" />
              <ActionBtn icon="checkmark-circle-outline" label="Close Won" color="#166534" onPress={closeWon} busy={busy} testID="lead-action-close-won" />
              <ActionBtn icon="close-circle-outline" label="Close Lost" color="#991B1B" onPress={() => setLostOpen(true)} busy={busy} testID="lead-action-close-lost" />
              <ActionBtn icon="archive-outline" label="Archive" color="#6B7280" onPress={() => setStatus("Archived")} busy={busy} testID="lead-action-archive" />
            </View>
          </View>
        )}

        {/* TD-96-mobile — linked quotes (admin). Fetch gated on linked_quotes_count (TD-96-g2-mobile). */}
        {canQuote && <LeadLinkedQuotesPanel leadId={String(id)} refreshKey={lead} linkedQuotesCount={lead?.linked_quotes_count} />}

        {/* Notes */}
        <View style={st.card}>
          <Text style={st.sectionLabel}>ADD NOTE</Text>
          <AppTextInput
            style={st.noteInput}
            value={noteText}
            onChangeText={setNoteText}
            placeholder="Type a note…"
            placeholderTextColor={colors.muted}
            multiline
            testID="lead-note-input"
          />
          <TouchableOpacity
            style={[st.noteBtn, !noteText.trim() && { opacity: 0.4 }]}
            onPress={addNote}
            disabled={!noteText.trim() || busy}
            testID="lead-note-submit"
          >
            <Ionicons name="send" size={14} color="#fff" />
            <Text style={st.noteBtnText}>Add Note</Text>
          </TouchableOpacity>
        </View>

        {/* Timeline */}
        <View style={st.card}>
          <Text style={st.sectionLabel}>TIMELINE ({timeline.length})</Text>
          {timeline.length === 0 ? (
            <Text style={st.emptyText}>No activity yet</Text>
          ) : (
            timeline.map((ev: any, i: number) => <TimelineEntry key={i} ev={ev} />)
          )}
        </View>
      </ScrollView>

      {/* Close Lost Modal */}
      <Modal visible={lostOpen} transparent animationType="fade" testID="close-lost-modal">
        <KeyboardAvoidingView style={st.modalOverlay} behavior={Platform.OS === "ios" ? "padding" : "height"}>
          <View style={st.modalCard}>
            <Text style={st.modalTitle}>Close as Lost</Text>
            <Text style={st.modalDesc}>Why did we lose this lead? (min 3 chars)</Text>
            <AppTextInput
              style={st.modalInput}
              value={lostReason}
              onChangeText={setLostReason}
              placeholder="Chose competitor / price / no response…"
              placeholderTextColor={colors.muted}
              multiline
              testID="close-lost-reason"
            />
            <View style={st.modalBtns}>
              <TouchableOpacity style={st.modalCancel} onPress={() => { setLostOpen(false); setLostReason(""); }} testID="close-lost-cancel">
                <Text style={st.modalCancelText}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[st.modalConfirm, lostReason.trim().length < 3 && { opacity: 0.4 }]}
                onPress={closeLost}
                disabled={busy || lostReason.trim().length < 3}
                testID="close-lost-confirm"
              >
                <Text style={st.modalConfirmText}>{busy ? "Closing…" : "Close Lost"}</Text>
              </TouchableOpacity>
            </View>
          </View>
        </KeyboardAvoidingView>
      </Modal>

      {composeChannel && (
        <LeadComposeSheet lead={lead} channel={composeChannel} onClose={() => setComposeChannel(null)} />
      )}
    </View>
  );
}

function ActionBtn({ icon, label, color, onPress, busy, disabled, testID }: any) {
  const off = !!(busy || disabled);
  return (
    <TouchableOpacity style={[st.actionBtn, disabled && { opacity: 0.4 }]} onPress={onPress} disabled={off} accessibilityState={{ disabled: off }} testID={testID}>
      <View style={[st.actionIcon, { backgroundColor: color + "18" }]}>
        <Ionicons name={icon} size={18} color={color} />
      </View>
      <Text style={[st.actionLabel, { color }]}>{label}</Text>
    </TouchableOpacity>
  );
}

const st = StyleSheet.create({
  root: { flex: 1, backgroundColor: "#F8FAFC" },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 24 },
  gateText: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface, marginTop: 12 },
  gateSubtext: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted, marginTop: 4, textAlign: "center" },
  gateBtn: { marginTop: 20, paddingHorizontal: 24, paddingVertical: 12, borderRadius: radius.md, backgroundColor: colors.brand },
  gateBtnText: { fontFamily: font.semibold, fontSize: fontSize.base, color: "#fff" },
  navBar: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.lg, paddingVertical: spacing.md, borderBottomWidth: 1, borderBottomColor: colors.border, backgroundColor: colors.surface, gap: 12 },
  navTitle: { flex: 1, fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  scroll: { padding: spacing.lg, paddingBottom: 60 },
  convBanner: { flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: "#DCFCE7", borderWidth: 1, borderColor: "#BBF7D0", borderRadius: radius.md, padding: spacing.md, marginBottom: spacing.md },
  convText: { flex: 1, fontFamily: font.semibold, fontSize: fontSize.sm, color: "#166534" },
  card: { backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.lg, marginBottom: spacing.md, borderWidth: 1, borderColor: colors.border },
  cardHeader: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  leadName: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface, flex: 1, marginRight: 8 },
  pill: { paddingHorizontal: 10, paddingVertical: 3, borderRadius: 999 },
  pillText: { fontFamily: font.bold, fontSize: 11, letterSpacing: 0.3 },
  sourceRow: { flexDirection: "row", alignItems: "center", gap: 4, marginTop: 4 },
  sourceText: { fontFamily: font.medium, fontSize: 11, color: colors.muted, textTransform: "uppercase" },
  interestText: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurfaceSecondary, marginTop: 4 },
  contactSection: { marginTop: spacing.md, gap: 8 },
  contactRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  contactText: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.brand },
  estValue: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.brand, marginTop: spacing.sm },
  actionsCard: { backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.lg, marginBottom: spacing.md, borderWidth: 1, borderColor: colors.border },
  sectionLabel: { fontFamily: font.bold, fontSize: 10, color: colors.muted, letterSpacing: 1, textTransform: "uppercase", marginBottom: spacing.sm },
  actionsGrid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  actionBtn: { alignItems: "center", width: 88, gap: 4, paddingVertical: 8 },
  actionIcon: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center" },
  actionLabel: { fontFamily: font.semibold, fontSize: 10, textAlign: "center" },
  quoteBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, minHeight: 44, marginTop: spacing.sm, borderRadius: radius.md, backgroundColor: "#4F46E5" },
  quoteBtnText: { fontFamily: font.semibold, fontSize: fontSize.base, color: "#fff" },
  quoteCount: { minWidth: 20, height: 20, paddingHorizontal: 6, borderRadius: 10, backgroundColor: "rgba(255,255,255,0.25)", alignItems: "center", justifyContent: "center" },
  quoteCountText: { fontFamily: font.semibold, fontSize: 11, color: "#fff" },
  noteInput: { backgroundColor: "#F8FAFC", borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, padding: spacing.md, minHeight: 60, fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, textAlignVertical: "top" },
  noteBtn: { flexDirection: "row", alignItems: "center", gap: 6, alignSelf: "flex-end", marginTop: spacing.sm, backgroundColor: colors.brand, paddingHorizontal: 14, paddingVertical: 8, borderRadius: radius.md },
  noteBtnText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: "#fff" },
  emptyText: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  tlEntry: { flexDirection: "row", gap: 10, paddingVertical: 8, borderLeftWidth: 2, borderLeftColor: colors.border, paddingLeft: 12 },
  tlDot: { width: 8, height: 8, borderRadius: 4, backgroundColor: colors.brand, marginTop: 5, marginLeft: -17 },
  tlLabel: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface },
  tlTime: { fontFamily: font.regular, fontSize: 11, color: colors.muted },
  tlNote: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurfaceSecondary, marginTop: 2 },
  tlLoss: { fontFamily: font.regular, fontSize: 11, color: "#991B1B", marginTop: 2 },
  modalOverlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.5)", justifyContent: "center", padding: 24 },
  modalCard: { backgroundColor: "#fff", borderRadius: radius.lg, padding: spacing.xl },
  modalTitle: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  modalDesc: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 4, marginBottom: spacing.md },
  modalInput: { backgroundColor: "#F8FAFC", borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, padding: spacing.md, minHeight: 80, fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, textAlignVertical: "top" },
  modalBtns: { flexDirection: "row", justifyContent: "flex-end", gap: spacing.sm, marginTop: spacing.lg },
  modalCancel: { paddingHorizontal: 16, paddingVertical: 10, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border },
  modalCancelText: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurface },
  modalConfirm: { paddingHorizontal: 16, paddingVertical: 10, borderRadius: radius.md, backgroundColor: "#DC2626" },
  modalConfirmText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: "#fff" },
});
