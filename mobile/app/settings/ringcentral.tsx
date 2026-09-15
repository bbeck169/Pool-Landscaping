/**
 * Phase 41.5c · Feb-2026 — Mobile RingCentral settings screen.
 *
 * Native parity for the web ``/settings/ringcentral`` form
 * (``frontend/src/pages/aiops/AiOpsPages.jsx::RingCentralSettings``).
 * Two endpoints, admin/super_admin only:
 *   • GET  /api/settings/ringcentral  → { webhook_url, account_id, configured }
 *     (``api_key`` is intentionally NOT returned by the backend — the
 *     API-key field starts empty and is only submitted when the user
 *     types a fresh value)
 *   • PUT  /api/settings/ringcentral  → accepts a partial patch of
 *     { webhook_url?, api_key?, account_id? } and returns the same
 *     shape as GET.
 *
 * No new endpoints. No SMS/RingOut/webhook tooling — that surface
 * stays on the web ``/admin/settings/ringcentral`` page and is not in
 * scope for this ticket.
 */
import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, ActivityIndicator, Alert } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import AppTextInput from "@/src/components/ui/AppTextInput";

type RingCentralConfig = {
  webhook_url?: string | null;
  account_id?: string | null;
  configured?: boolean;
};

export default function RingCentralSettings() {
  const { user } = useAuth();
  // Mirror the web ``<AdminOnly>`` route guard verbatim.
  const isAdmin = user?.role === "admin" || (user?.role as any) === "super_admin";

  const [draft, setDraft] = useState<RingCentralConfig | null>(null);
  const [apiKeyInput, setApiKeyInput] = useState("");
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    if (!isAdmin) return;
    try {
      const c = await api.get("/settings/ringcentral");
      setDraft(c || {});
    } catch {
      setDraft({});
    }
    // ``api_key`` is never returned by the backend, so keep the
    // input blank on (re)load — typing anything counts as a rotation.
    setApiKeyInput("");
  }, [isAdmin]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const save = async () => {
    if (!draft) return;
    setSaving(true);
    try {
      // Only send fields that were actually touched. ``api_key`` is
      // only submitted when the user typed something — otherwise the
      // backend keeps the existing (masked) value.
      const patch: Record<string, string> = {};
      if (draft.webhook_url !== undefined && draft.webhook_url !== null) {
        patch.webhook_url = draft.webhook_url;
      }
      if (draft.account_id !== undefined && draft.account_id !== null) {
        patch.account_id = draft.account_id;
      }
      if (apiKeyInput.trim() !== "") {
        patch.api_key = apiKeyInput;
      }
      const fresh = await api.put("/settings/ringcentral", patch);
      setDraft(fresh || {});
      setApiKeyInput("");
      showToast("RingCentral settings updated.");
    } catch (e: any) {
      Alert.alert("Error", e?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  if (!isAdmin) {
    return (
      <View style={s.root} testID="ringcentral-settings-role-gate">
        <Header title="RingCentral" back />
        <View style={s.center}>
          <Ionicons name="lock-closed" size={32} color={colors.muted} />
          <Text style={s.centerText}>Admin only</Text>
        </View>
      </View>
    );
  }

  return (
    <View style={s.root} testID="ringcentral-settings-screen">
      <Header title="RingCentral" subtitle="Inbound call tracking + auto-lead capture" back />
      {!draft ? (
        <View style={s.center}>
          <ActivityIndicator size="large" color={colors.brand}
                             testID="ringcentral-settings-loading" />
        </View>
      ) : (
        <ScrollView
          testID="ringcentral-settings-form"
          contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}
          keyboardShouldPersistTaps="handled"
        >
          <View style={s.field}>
            <Text style={s.label}>Webhook URL</Text>
            <AppTextInput
              testID="ringcentral-settings-input-webhook_url"
              style={s.input}
              value={draft.webhook_url || ""}
              onChangeText={(v) => setDraft((d) => ({ ...(d || {}), webhook_url: v }))}
              placeholder="https://…/api/ringcentral/webhook"
              placeholderTextColor={colors.muted}
              keyboardType="url"
              autoCapitalize="none"
              autoCorrect={false}
            />
          </View>

          <View style={s.field}>
            <Text style={s.label}>Account ID</Text>
            <AppTextInput
              testID="ringcentral-settings-input-account_id"
              style={s.input}
              value={draft.account_id || ""}
              onChangeText={(v) => setDraft((d) => ({ ...(d || {}), account_id: v }))}
              placeholder="e.g. ~1234567890"
              placeholderTextColor={colors.muted}
              autoCapitalize="none"
              autoCorrect={false}
            />
          </View>

          <View style={s.field}>
            <Text style={s.label}>API key</Text>
            <AppTextInput
              testID="ringcentral-settings-input-api_key"
              style={s.input}
              value={apiKeyInput}
              onChangeText={setApiKeyInput}
              placeholder={draft.configured ? "•••••••• (leave blank to keep current)" : "Paste API key"}
              placeholderTextColor={colors.muted}
              secureTextEntry
              autoCapitalize="none"
              autoCorrect={false}
            />
            <Text style={s.hint}
                  testID={draft.configured
                    ? "ringcentral-settings-configured"
                    : "ringcentral-settings-not-configured"}>
              {draft.configured
                ? "API key on file. Type a new value to rotate."
                : "Not configured yet — webhook still accepts payloads and creates call_logs."}
            </Text>
          </View>

          <TouchableOpacity
            style={[s.saveBtn, saving && { opacity: 0.6 }]}
            onPress={save}
            disabled={saving}
            testID="ringcentral-settings-save-btn"
          >
            <Ionicons name="checkmark" size={18} color="#fff" />
            <Text style={s.saveBtnText}>{saving ? "Saving\u2026" : "Save Changes"}</Text>
          </TouchableOpacity>
        </ScrollView>
      )}
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: spacing.md },
  centerText: { fontFamily: font.medium, fontSize: fontSize.lg, color: colors.muted },
  field: { marginBottom: spacing.md },
  label: {
    fontFamily: font.bold, fontSize: 11, textTransform: "uppercase",
    letterSpacing: 0.8, color: colors.muted, marginBottom: spacing.xs,
  },
  input: {
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    borderRadius: radius.md, paddingHorizontal: spacing.md, paddingVertical: spacing.md,
    fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface,
  },
  hint: {
    fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted,
    marginTop: spacing.xs,
  },
  saveBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    backgroundColor: colors.brand, paddingVertical: 14, borderRadius: radius.md,
    marginTop: spacing.lg,
  },
  saveBtnText: { fontFamily: font.bold, fontSize: fontSize.base, color: "#fff" },
});
