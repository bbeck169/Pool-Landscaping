/**
 * QuoteIQ Q2-UI · Mobile — AI Estimator.
 *
 * Compact single-screen flow: description + options toggle + generate.
 * Photo capture defers to a follow-up (users on mobile typically type
 * the description in the field; on-site photos can attach after the
 * draft opens in web). Draft result renders inline with tier cards or
 * a line-item list. Tap "Promote" to hand off to the web estimate
 * detail flow.
 */
import React, { useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity,
  Alert, ActivityIndicator, Switch } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";

import { Header } from "@/src/components/widgets";
import { OfflineGate } from "@/src/components/OfflineGate";
import { colors, fontSize, radius, spacing } from "@/src/theme";
import { api } from "@/src/api";
import AppTextInput from "@/src/components/ui/AppTextInput";

const $ = (c: number) => `$${((c || 0) / 100).toFixed(2)}`;

export default function AiEstimator() {
  const insets = useSafeAreaInsets();
  const [balance, setBalance] = useState<any>(null);
  const [desc, setDesc] = useState("");
  const [optionsMode, setOptionsMode] = useState(false);
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState<any>(null);

  useEffect(() => {
    api.get("/ai-credits/balance").then(setBalance).catch(() => setBalance(null));
  }, [draft]);

  const cost = optionsMode ? 20 : 10;

  const submit = async () => {
    if (!desc.trim()) { Alert.alert("Description required"); return; }
    setBusy(true);
    try {
      const r = await api.post("/ai-estimator/generate", {
        photo_urls: [], job_description: desc, options_mode: optionsMode,
      });
      setDraft(r.draft);
      if (r.credit_warning) Alert.alert("Low credit balance", "Top up on the web admin.");
    } catch (e: any) {
      Alert.alert("Generate failed", e?.message || "");
    } finally { setBusy(false); }
  };

  return (
    <OfflineGate testID="ai-estimator-offline-gate" message="AI Estimator requires an internet connection to generate estimates.">
    <View style={{ flex: 1, backgroundColor: colors.background }}>
      <Header title="AI Estimator" />
      <ScrollView contentContainerStyle={{ padding: spacing.md, paddingBottom: insets.bottom + 40 }}>
        <View style={s.card}>
          <View style={s.rowBetween}>
            <Text style={s.small}>Balance</Text>
            <Text style={{ fontWeight: "700", fontSize: 18, color: colors.text }}>
              {balance?.balance ?? "—"} · {balance?.plan || ""}
            </Text>
          </View>
        </View>

        <Text style={s.label}>Describe the job</Text>
        <AppTextInput
          value={desc}
          onChangeText={setDesc}
          multiline
          style={[s.input, { minHeight: 100, textAlignVertical: "top" }]}
          placeholder="e.g. Weekly service, 20k gal plaster pool, salt system, moderate leaf load…"
          placeholderTextColor={colors.textDim}
          testID="ai-est-mobile-desc"
        />
        <View style={s.rowBetween}>
          <Text style={s.small}>Generate 3 options (Good/Better/Best)</Text>
          <Switch value={optionsMode} onValueChange={setOptionsMode} testID="ai-est-mobile-options" />
        </View>
        <Text style={s.tinyMuted}>
          Will use {cost} credits. Balance after: {(balance?.balance ?? 0) - cost}
        </Text>

        <TouchableOpacity
          style={[s.button, busy && { opacity: 0.6 }]}
          onPress={submit}
          disabled={busy}
          testID="ai-est-mobile-generate"
        >
          {busy ? <ActivityIndicator color="#fff" /> :
            <>
              <Ionicons name="sparkles-outline" size={18} color="#fff" />
              <Text style={s.buttonText}>Generate</Text>
            </>
          }
        </TouchableOpacity>

        {draft && (
          <View style={[s.card, { marginTop: spacing.lg }]} testID="ai-est-mobile-result">
            <Text style={s.section}>Draft — {draft.status}</Text>
            <Text style={{ color: colors.text, marginBottom: spacing.sm }}>
              Suggested total: {$( draft.suggested_total_cents )}
            </Text>
            {draft.status === "error" ? (
              <Text style={{ color: "#DC2626" }}>{draft.error}</Text>
            ) : draft.options_mode && draft.tiers?.length ? (
              draft.tiers.map((t: any) => (
                <View
                  key={t.id}
                  style={[
                    s.tierRow,
                    t.is_default && { borderColor: colors.primary, backgroundColor: "#EFF6FF" },
                  ]}
                >
                  <Text style={{ fontWeight: "700" }}>
                    {t.name} {t.is_default && "★"}
                  </Text>
                  <Text style={s.small}>{t.description}</Text>
                  <Text style={{ marginTop: 4, color: colors.text }}>{$( t.total_cents )}</Text>
                </View>
              ))
            ) : (
              (draft.line_items || []).map((li: any, i: number) => (
                <View key={i} style={s.lineRow}>
                  <Text style={{ flex: 1, color: colors.text }}>{li.description}</Text>
                  <Text style={{ color: colors.textDim, marginHorizontal: 6 }}>
                    {li.qty}×
                  </Text>
                  <Text style={{ fontWeight: "600", color: colors.text }}>
                    {$( li.subtotal_cents )}
                  </Text>
                </View>
              ))
            )}
            <Text style={[s.tinyMuted, { marginTop: spacing.sm }]}>
              Promote to a formal estimate from the web admin (customer picker + PDF).
            </Text>
          </View>
        )}
      </ScrollView>
    </View>
    </OfflineGate>
  );
}

const s = StyleSheet.create({
  card: {
    backgroundColor: colors.card, padding: spacing.md,
    borderRadius: radius.md, borderWidth: 1, borderColor: colors.border,
    marginBottom: spacing.md,
  },
  rowBetween: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 4 },
  label: { fontSize: fontSize.sm, color: colors.textDim, marginBottom: 4 },
  input: { borderWidth: 1, borderColor: colors.border, borderRadius: radius.sm, padding: 10, color: colors.text, backgroundColor: colors.card, marginBottom: spacing.md },
  small: { fontSize: fontSize.sm, color: colors.textDim },
  tinyMuted: { fontSize: fontSize.xs, color: colors.textDim, marginBottom: spacing.md },
  button: { flexDirection: "row", justifyContent: "center", alignItems: "center", gap: 8, backgroundColor: colors.primary, padding: 14, borderRadius: radius.md },
  buttonText: { color: "#fff", fontWeight: "700", fontSize: fontSize.md },
  section: { fontSize: fontSize.sm, color: colors.textDim, textTransform: "uppercase", letterSpacing: 0.6, marginBottom: 4 },
  tierRow: { borderWidth: 1, borderColor: colors.border, borderRadius: radius.sm, padding: spacing.sm, marginBottom: 6 },
  lineRow: { flexDirection: "row", alignItems: "center", paddingVertical: 6, borderBottomWidth: 1, borderBottomColor: colors.border },
});
