/**
 * QuoteIQ Q1-UI · Mobile — New deal modal screen.
 *
 * Simple form. Falls back to the default pipeline + its first stage.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, Alert, ActivityIndicator } from "react-native";
import { useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";

import { Header } from "@/src/components/widgets";
import { colors, fontSize, radius, spacing } from "@/src/theme";
import { listPipelines, createDeal } from "@/src/api/quoteiq_q1";
import AppTextInput from "@/src/components/ui/AppTextInput";

export default function DealNew() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const [pipeline, setPipeline] = useState<any>(null);
  const [stageId, setStageId] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({
    title: "", value_cents: "0", contact_name: "", contact_email: "",
    contact_phone: "", notes: "",
  });

  useEffect(() => {
    (async () => {
      const pps = await listPipelines();
      const def =
        pps.pipelines.find((p: any) => p.is_default) || pps.pipelines[0];
      setPipeline(def);
      setStageId(def?.stages?.[0]?.id || "");
    })();
  }, []);

  const submit = async () => {
    if (!form.title.trim()) {
      Alert.alert("Title required");
      return;
    }
    setBusy(true);
    try {
      const created = await createDeal({
        title: form.title,
        value_cents: parseInt(form.value_cents, 10) || 0,
        contact_name: form.contact_name,
        contact_email: form.contact_email,
        contact_phone: form.contact_phone,
        notes: form.notes,
        stage_id: stageId,
        pipeline_id: pipeline?.id,
      });
      router.replace(`/(app)/deals/${created.id}`);
    } catch (e: any) {
      Alert.alert("Create failed", e?.message || "");
    } finally {
      setBusy(false);
    }
  };

  if (!pipeline) {
    return (
      <View style={{ flex: 1, backgroundColor: colors.background }}>
        <Header title="New Deal" />
        <ActivityIndicator style={{ marginTop: spacing.xl }} />
      </View>
    );
  }

  return (
    <View style={{ flex: 1, backgroundColor: colors.background }}>
      <Header title="New Deal" />
      <ScrollView
        contentContainerStyle={{
          padding: spacing.md,
          paddingBottom: insets.bottom + spacing.xl,
        }}
      >
        <Field
          label="Title *"
          value={form.title}
          onChange={(v) => setForm({ ...form, title: v })}
          testID="deal-new-title"
        />
        <Field
          label="Value (cents)"
          value={form.value_cents}
          onChange={(v) => setForm({ ...form, value_cents: v.replace(/[^\d]/g, "") })}
          keyboard="numeric"
          testID="deal-new-value"
        />
        <Field
          label="Contact name"
          value={form.contact_name}
          onChange={(v) => setForm({ ...form, contact_name: v })}
        />
        <Field
          label="Email"
          value={form.contact_email}
          onChange={(v) => setForm({ ...form, contact_email: v })}
        />
        <Field
          label="Phone"
          value={form.contact_phone}
          onChange={(v) => setForm({ ...form, contact_phone: v })}
        />
        <Field
          label="Notes"
          value={form.notes}
          onChange={(v) => setForm({ ...form, notes: v })}
          multiline
        />

        <Text style={s.label}>Starting stage</Text>
        <View style={{ gap: 6 }}>
          {(pipeline.stages || []).map((st: any) => (
            <TouchableOpacity
              key={st.id}
              onPress={() => setStageId(st.id)}
              style={[
                s.stageBtn,
                stageId === st.id && { borderColor: colors.primary, backgroundColor: "#EFF6FF" },
              ]}
            >
              <View style={[s.stageDot, { backgroundColor: st.color }]} />
              <Text style={{ flex: 1 }}>{st.name}</Text>
              <Text style={{ color: colors.textDim }}>{st.probability_pct}%</Text>
            </TouchableOpacity>
          ))}
        </View>

        <TouchableOpacity
          disabled={busy}
          onPress={submit}
          style={[s.submit, busy && { opacity: 0.6 }]}
          testID="deal-new-submit"
        >
          <Ionicons name="save-outline" size={18} color="#fff" />
          <Text style={{ color: "#fff", fontWeight: "700", fontSize: 16 }}>
            {busy ? "Creating…" : "Create deal"}
          </Text>
        </TouchableOpacity>
      </ScrollView>
    </View>
  );
}

function Field({ label, value, onChange, keyboard, multiline, testID }: any) {
  return (
    <View style={{ marginBottom: spacing.md }}>
      <Text style={s.label}>{label}</Text>
      <AppTextInput
        value={value}
        onChangeText={onChange}
        keyboardType={keyboard || "default"}
        multiline={!!multiline}
        style={[s.input, multiline && { minHeight: 80, textAlignVertical: "top" }]}
        placeholderTextColor={colors.textDim}
        testID={testID}
      />
    </View>
  );
}

const s = StyleSheet.create({
  label: { fontSize: fontSize.sm, color: colors.textDim, marginBottom: 4 },
  input: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.sm,
    padding: 10,
    color: colors.text,
    backgroundColor: colors.card,
  },
  stageBtn: {
    flexDirection: "row",
    alignItems: "center",
    padding: 10,
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: colors.border,
  },
  stageDot: { width: 10, height: 10, borderRadius: 5, marginRight: 8 },
  submit: {
    marginTop: spacing.md,
    flexDirection: "row",
    justifyContent: "center",
    alignItems: "center",
    gap: 8,
    backgroundColor: colors.primary,
    padding: 14,
    borderRadius: radius.md,
  },
});
