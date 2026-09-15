import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, RefreshControl,
  TouchableOpacity, ActivityIndicator, Alert } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import AppTextInput from "@/src/components/ui/AppTextInput";

const FIELDS = [
  { key: "company_name", label: "Company name", kb: "default" as const },
  { key: "tagline", label: "Tagline", kb: "default" as const },
  { key: "service_area", label: "Service area", kb: "default" as const, placeholder: "e.g. Peoria & Vistancia, AZ" },
  { key: "phone", label: "Phone", kb: "phone-pad" as const },
  { key: "email", label: "Email", kb: "email-address" as const },
  { key: "website_url", label: "Website URL", kb: "url" as const },
  { key: "google_review_url", label: "Google review URL", kb: "url" as const },
  { key: "logo_url", label: "Logo URL", kb: "url" as const },
];

export default function BusinessCardSettings() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin" || user?.role === "super_admin";
  const [draft, setDraft] = useState<any>(null);
  const [saving, setSaving] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const c = await api.get("/tenants/business-card");
      setDraft(c);
    } catch {
      setDraft({});
    } finally {
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const save = async () => {
    if (!draft) return;
    setSaving(true);
    try {
      const patch: any = {};
      for (const f of FIELDS) patch[f.key] = draft[f.key] ?? null;
      const fresh = await api.patch("/tenants/business-card", patch);
      setDraft(fresh);
      showToast("Business card updated.");
    } catch (e: any) {
      Alert.alert("Error", e?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  if (!isAdmin) {
    return (
      <View style={s.root}>
        <Header title="Business Card" back />
        <View style={s.center}>
          <Ionicons name="lock-closed" size={32} color={colors.muted} />
          <Text style={s.centerText}>Admin only</Text>
        </View>
      </View>
    );
  }

  return (
    <View style={s.root}>
      <Header title="Business Card" subtitle="Your company card info" back />
      {!draft ? (
        <View style={s.center}><ActivityIndicator size="large" color={colors.brand} /></View>
      ) : (
        <ScrollView
          testID="business-card-settings-form"
          contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
        >
          {FIELDS.map((f) => (
            <View key={f.key} style={s.field}>
              <Text style={s.label}>{f.label}</Text>
              <AppTextInput
                testID={`business-card-settings-input-${f.key}`}
                style={s.input}
                value={draft[f.key] || ""}
                onChangeText={(v) => setDraft((d: any) => ({ ...d, [f.key]: v }))}
                placeholder={f.placeholder || ""}
                placeholderTextColor={colors.muted}
                keyboardType={f.kb}
                autoCapitalize="none"
                autoCorrect={false}
              />
            </View>
          ))}

          <TouchableOpacity
            style={[s.saveBtn, saving && { opacity: 0.6 }]}
            onPress={save}
            disabled={saving}
            testID="business-card-settings-save-btn"
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
  saveBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    backgroundColor: colors.brand, paddingVertical: 14, borderRadius: radius.md,
    marginTop: spacing.lg,
  },
  saveBtnText: { fontFamily: font.bold, fontSize: fontSize.base, color: "#fff" },
});
