/**
 * QuoteIQ Q1-UI · Mobile — Deal detail screen.
 *
 * Shows deal fields + events timeline + action buttons. Move-stage
 * uses a bottom sheet of stage chips. Mark won/lost and convert-to-job
 * are single-tap actions.
 */
import React, { useCallback, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  Alert,
  ActivityIndicator,
  Modal,
  TextInput,
} from "react-native";
import { useLocalSearchParams, useRouter, useFocusEffect } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { Header } from "@/src/components/widgets";
import { colors, fontSize, radius, spacing } from "@/src/theme";
import {
  getDeal, getDealEvents, listPipelines, moveDeal, wonDeal, lostDeal,
  convertDeal,
} from "@/src/api/quoteiq_q1";

const centsToUsd = (c: number) =>
  `$${((c || 0) / 100).toLocaleString(undefined, {
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  })}`;

export default function DealDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const [deal, setDeal] = useState<any>(null);
  const [events, setEvents] = useState<any[]>([]);
  const [pipeline, setPipeline] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [moveOpen, setMoveOpen] = useState(false);
  const [lostOpen, setLostOpen] = useState(false);
  const [lostReason, setLostReason] = useState("");

  const load = useCallback(async () => {
    if (!id) return;
    try {
      setLoading(true);
      const d = await getDeal(id);
      setDeal(d);
      const ev = await getDealEvents(id);
      setEvents(ev.events || []);
      const pps = await listPipelines();
      setPipeline(
        pps.pipelines.find((p: any) => p.id === d.pipeline_id) ||
          pps.pipelines.find((p: any) => p.is_default),
      );
    } finally {
      setLoading(false);
    }
  }, [id]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const doMove = async (stageId: string) => {
    setBusy(true);
    try {
      await moveDeal(id!, stageId);
      setMoveOpen(false);
      await load();
    } catch (e: any) {
      Alert.alert("Move failed", e?.message || "");
    } finally {
      setBusy(false);
    }
  };
  const doWon = async () => {
    setBusy(true);
    try {
      await wonDeal(id!);
      await load();
    } finally { setBusy(false); }
  };
  const doLost = async () => {
    setBusy(true);
    try {
      await lostDeal(id!, lostReason);
      setLostOpen(false);
      setLostReason("");
      await load();
    } finally { setBusy(false); }
  };
  const doConvert = async () => {
    setBusy(true);
    try {
      const r = await convertDeal(id!);
      if (r.job_id) {
        Alert.alert("Converted", `Job ${r.job_id.slice(0, 8)}… created`);
      } else {
        Alert.alert("Marked won", r.reason || "No customer to attach.");
      }
      await load();
    } finally { setBusy(false); }
  };

  if (loading || !deal) {
    return (
      <View style={{ flex: 1, backgroundColor: colors.background }}>
        <Header title="Deal" />
        <View style={{ padding: spacing.xl, alignItems: "center" }}>
          <ActivityIndicator />
        </View>
      </View>
    );
  }

  const stageName =
    (pipeline?.stages || []).find((s: any) => s.id === deal.stage_id)?.name || "—";

  return (
    <View style={{ flex: 1, backgroundColor: colors.background }}>
      <Header title="Deal" />
      <ScrollView
        contentContainerStyle={{
          padding: spacing.md,
          paddingBottom: insets.bottom + spacing.xl,
        }}
      >
        <View style={s.card}>
          <Text style={s.title}>{deal.title}</Text>
          <Text style={s.value}>{centsToUsd(deal.value_cents)}</Text>
          <View style={s.metaRow}>
            <Text style={s.metaLabel}>Stage</Text>
            <Text style={s.metaValue}>{stageName} · {deal.probability_pct}%</Text>
          </View>
          <View style={s.metaRow}>
            <Text style={s.metaLabel}>Status</Text>
            <Text
              style={[
                s.metaValue,
                deal.status === "won" && { color: "#059669" },
                deal.status === "lost" && { color: "#DC2626" },
              ]}
            >
              {deal.status}
            </Text>
          </View>
          <View style={s.metaRow}>
            <Text style={s.metaLabel}>Contact</Text>
            <Text style={s.metaValue}>{deal.contact_name || "—"}</Text>
          </View>
          {deal.contact_email && (
            <View style={s.metaRow}>
              <Text style={s.metaLabel}>Email</Text>
              <Text style={s.metaValue}>{deal.contact_email}</Text>
            </View>
          )}
          {deal.contact_phone && (
            <View style={s.metaRow}>
              <Text style={s.metaLabel}>Phone</Text>
              <Text style={s.metaValue}>{deal.contact_phone}</Text>
            </View>
          )}
          {deal.expected_close_date && (
            <View style={s.metaRow}>
              <Text style={s.metaLabel}>Expected close</Text>
              <Text style={s.metaValue}>{deal.expected_close_date}</Text>
            </View>
          )}
          {deal.notes ? (
            <View style={{ marginTop: spacing.sm }}>
              <Text style={s.metaLabel}>Notes</Text>
              <Text style={{ color: colors.text, marginTop: 4 }}>{deal.notes}</Text>
            </View>
          ) : null}
        </View>

        {deal.status === "open" && (
          <View style={{ gap: spacing.sm, marginBottom: spacing.md }}>
            <TouchableOpacity
              style={s.actionBtn}
              onPress={() => setMoveOpen(true)}
              disabled={busy}
              testID="deal-mobile-move"
            >
              <Ionicons name="swap-horizontal" size={18} color="#fff" />
              <Text style={s.actionText}>Move stage</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[s.actionBtn, { backgroundColor: "#059669" }]}
              onPress={doWon}
              disabled={busy}
              testID="deal-mobile-won"
            >
              <Ionicons name="trophy-outline" size={18} color="#fff" />
              <Text style={s.actionText}>Mark won</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[s.actionBtn, { backgroundColor: "#DC2626" }]}
              onPress={() => setLostOpen(true)}
              disabled={busy}
              testID="deal-mobile-lost"
            >
              <Ionicons name="close-circle-outline" size={18} color="#fff" />
              <Text style={s.actionText}>Mark lost</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[s.actionBtn, { backgroundColor: "#7C3AED" }]}
              onPress={doConvert}
              disabled={busy}
              testID="deal-mobile-convert"
            >
              <Ionicons name="briefcase-outline" size={18} color="#fff" />
              <Text style={s.actionText}>Convert to job</Text>
            </TouchableOpacity>
          </View>
        )}

        <Text style={s.section}>Timeline</Text>
        {events.length === 0 && (
          <Text style={s.empty}>No events yet.</Text>
        )}
        {events.map((e) => (
          <View key={e.id} style={s.event}>
            <Text style={s.eventKind}>{e.type.replace(/_/g, " ")}</Text>
            <Text style={s.eventTs}>
              {new Date(e.created_at).toLocaleString()}
            </Text>
            {e.to_value && (
              <Text style={s.eventBody}>→ {JSON.stringify(e.to_value)}</Text>
            )}
          </View>
        ))}
      </ScrollView>

      {/* Move-stage bottom sheet */}
      <Modal
        visible={moveOpen}
        transparent
        animationType="slide"
        onRequestClose={() => setMoveOpen(false)}
      >
        <TouchableOpacity
          style={s.modalBg}
          activeOpacity={1}
          onPress={() => setMoveOpen(false)}
        >
          <View
            style={[s.sheet, { paddingBottom: insets.bottom + spacing.md }]}
            onStartShouldSetResponder={() => true}
          >
            <Text style={s.sheetTitle}>Move to stage</Text>
            {(pipeline?.stages || []).map((st: any) => (
              <TouchableOpacity
                key={st.id}
                style={[s.stageItem, st.id === deal.stage_id && { opacity: 0.4 }]}
                disabled={st.id === deal.stage_id || busy}
                onPress={() => doMove(st.id)}
                testID={`deal-mobile-move-target-${st.name.toLowerCase().replace(/\s+/g, "-")}`}
              >
                <View style={[s.stageDot, { backgroundColor: st.color || "#94A3B8" }]} />
                <Text style={s.stageName}>{st.name}</Text>
                <Text style={s.stageProb}>{st.probability_pct}%</Text>
              </TouchableOpacity>
            ))}
          </View>
        </TouchableOpacity>
      </Modal>

      {/* Lost-reason modal */}
      <Modal
        visible={lostOpen}
        transparent
        animationType="fade"
        onRequestClose={() => setLostOpen(false)}
      >
        <View style={s.modalBg}>
          <View style={s.lostModal}>
            <Text style={s.sheetTitle}>Reason for losing</Text>
            <TextInput
              value={lostReason}
              onChangeText={setLostReason}
              placeholder="e.g. price too high, went with competitor"
              placeholderTextColor={colors.textDim}
              multiline
              style={s.input}
              testID="deal-mobile-lost-reason-input"
            />
            <View style={{ flexDirection: "row", gap: spacing.sm }}>
              <TouchableOpacity
                style={[s.actionBtn, { flex: 1, backgroundColor: "#6B7280" }]}
                onPress={() => setLostOpen(false)}
              >
                <Text style={s.actionText}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[s.actionBtn, { flex: 1, backgroundColor: "#DC2626" }]}
                onPress={doLost}
                testID="deal-mobile-lost-confirm"
              >
                <Text style={s.actionText}>Mark lost</Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>
    </View>
  );
}

const s = StyleSheet.create({
  card: {
    backgroundColor: colors.card,
    padding: spacing.md,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    marginBottom: spacing.md,
  },
  title: { fontSize: 20, fontWeight: "700", color: colors.text },
  value: { fontSize: 26, fontWeight: "700", color: colors.primary, marginTop: 4 },
  metaRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    marginTop: spacing.sm,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    paddingTop: spacing.sm,
  },
  metaLabel: { color: colors.textDim, fontSize: fontSize.sm },
  metaValue: { color: colors.text, fontSize: fontSize.sm, fontWeight: "500" },
  actionBtn: {
    flexDirection: "row",
    gap: 6,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.primary,
    padding: 14,
    borderRadius: radius.md,
  },
  actionText: { color: "#fff", fontWeight: "600", fontSize: fontSize.md },
  section: {
    fontSize: fontSize.sm,
    color: colors.textDim,
    textTransform: "uppercase",
    letterSpacing: 0.6,
    marginBottom: spacing.sm,
  },
  event: {
    backgroundColor: colors.card,
    padding: spacing.sm,
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: colors.border,
    marginBottom: spacing.sm,
  },
  eventKind: { fontWeight: "600", color: colors.text, textTransform: "capitalize" },
  eventTs: { fontSize: fontSize.xs, color: colors.textDim, marginTop: 2 },
  eventBody: { fontSize: fontSize.xs, color: colors.textDim, marginTop: 4 },
  empty: {
    fontSize: fontSize.sm,
    color: colors.textDim,
    textAlign: "center",
    paddingVertical: spacing.md,
  },
  modalBg: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.4)",
    justifyContent: "flex-end",
  },
  sheet: {
    backgroundColor: colors.card,
    borderTopLeftRadius: 16,
    borderTopRightRadius: 16,
    padding: spacing.md,
  },
  sheetTitle: { fontSize: fontSize.lg, fontWeight: "700", marginBottom: spacing.sm },
  stageItem: {
    flexDirection: "row",
    alignItems: "center",
    padding: spacing.md,
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: colors.border,
    marginBottom: 6,
  },
  stageDot: { width: 12, height: 12, borderRadius: 6, marginRight: 10 },
  stageName: { flex: 1, fontSize: fontSize.md, color: colors.text },
  stageProb: { fontSize: fontSize.sm, color: colors.textDim },
  lostModal: {
    backgroundColor: colors.card,
    margin: spacing.md,
    borderRadius: radius.md,
    padding: spacing.md,
    marginTop: "auto",
    marginBottom: "auto",
  },
  input: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.sm,
    padding: 10,
    minHeight: 80,
    color: colors.text,
    marginVertical: spacing.md,
    textAlignVertical: "top",
  },
});
