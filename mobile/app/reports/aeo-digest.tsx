// Phase 16 · Feb-2026 — AEO PDF digest settings + preview (Manager+).
//
// Preview opens a signed PDF URL in the system browser via expo-web-browser.
import React, { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, TextInput, Alert, Pressable } from "react-native";
import * as WebBrowser from "expo-web-browser";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Card, Loading, PrimaryButton } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";
import { RoleGate } from "@/src/components/RoleGate";

const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

export default function AeoDigest() {
  const [enabled, setEnabled] = useState(true);
  const [dowIdx, setDowIdx] = useState(1);
  const [hour, setHour] = useState(9);
  const [recipients, setRecipients] = useState("");
  const [includeNeg, setIncludeNeg] = useState(true);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [previewing, setPreviewing] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const j: any = await api.get("/aeo/digest/settings");
      setEnabled(j?.enabled ?? true);
      setDowIdx(j?.day_of_week ?? 1);
      setHour(j?.hour ?? 9);
      setRecipients((j?.recipients || []).join(", "));
      setIncludeNeg(j?.include_negative_snippets ?? true);
    } catch { /* silent */ }
    setLoading(false);
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const save = async () => {
    setSaving(true);
    try {
      await api.post("/aeo/digest/settings", {
        enabled,
        day_of_week: dowIdx,
        hour,
        recipients: recipients.split(",").map((s) => s.trim()).filter(Boolean),
        include_negative_snippets: includeNeg,
      });
      Alert.alert("Saved", "AEO digest settings saved.");
    } catch (err: any) {
      Alert.alert("Save failed", String(err?.message || err));
    } finally {
      setSaving(false);
    }
  };

  const runPreview = async () => {
    setPreviewing(true);
    try {
      const j: any = await api.post("/aeo/digest/preview", {});
      const url = j?.signed_pdf_url || j?.url;
      if (!url) throw new Error("No PDF URL returned.");
      await WebBrowser.openBrowserAsync(url);
    } catch (err: any) {
      Alert.alert("Preview failed", String(err?.message || err));
    } finally {
      setPreviewing(false);
    }
  };

  return (
    <RoleGate level="admin_plus">
      <View style={styles.container}>
        <Header title="AEO PDF digest" />
        {loading ? (
          <Loading />
        ) : (
          <ScrollView contentContainerStyle={styles.body}>
            <Card>
              <Text style={styles.sectionLabel}>Recipients</Text>
              <TextInput
                testID="aeo-digest-recipients"
                value={recipients}
                onChangeText={setRecipients}
                placeholder="owner@company.com, marketing@company.com"
                placeholderTextColor={colors.muted}
                autoCapitalize="none"
                keyboardType="email-address"
                style={styles.input}
              />
              <View style={styles.rowBetween}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.sectionLabel}>Day of week</Text>
                  <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 6 }}>
                    {DOW.map((d, i) => {
                      const on = dowIdx === i;
                      return (
                        <Text key={d} testID={`aeo-digest-dow-${i}`} onPress={() => setDowIdx(i)}
                              style={[styles.dowChip, on && styles.dowChipOn]}>{d}</Text>
                      );
                    })}
                  </ScrollView>
                </View>
                <View style={{ width: 80, marginLeft: spacing.md }}>
                  <Text style={styles.sectionLabel}>Hour</Text>
                  <TextInput
                    testID="aeo-digest-hour"
                    value={String(hour)}
                    onChangeText={(v) => setHour(Math.max(0, Math.min(23, parseInt(v || "0", 10))))}
                    keyboardType="number-pad"
                    style={styles.input}
                  />
                </View>
              </View>
              <View style={styles.rowBetween}>
                <Text style={styles.sectionLabel}>Include negative snippets</Text>
                <Text testID="aeo-digest-neg-toggle" onPress={() => setIncludeNeg((v) => !v)}
                      style={[styles.toggle, includeNeg ? styles.toggleOn : styles.toggleOff]}>
                  {includeNeg ? "ON" : "OFF"}
                </Text>
              </View>
              <View style={styles.rowBetween}>
                <Text style={styles.sectionLabel}>Digest enabled</Text>
                <Text testID="aeo-digest-enabled-toggle" onPress={() => setEnabled((v) => !v)}
                      style={[styles.toggle, enabled ? styles.toggleOn : styles.toggleOff]}>
                  {enabled ? "ON" : "OFF"}
                </Text>
              </View>
              <View style={{ height: spacing.md }} />
              <PrimaryButton title={saving ? "Saving…" : "Save settings"} onPress={save} loading={saving} testID="aeo-digest-save" />
              <View style={{ height: spacing.xs }} />
              <PrimaryButton variant="outline" title={previewing ? "Opening…" : "Preview PDF"}
                              icon="document-text-outline" onPress={runPreview} loading={previewing}
                              testID="aeo-digest-preview" />
            </Card>
          </ScrollView>
        )}
      </View>
    </RoleGate>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.surface },
  body: { padding: spacing.lg, gap: spacing.md, paddingBottom: spacing["3xl"] },
  sectionLabel: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface, marginBottom: spacing.sm },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    padding: spacing.md, fontFamily: font.regular, fontSize: fontSize.base,
    color: colors.onSurface, marginBottom: spacing.md,
  },
  rowBetween: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginTop: spacing.sm },
  dowChip: { paddingHorizontal: 10, paddingVertical: 6, borderRadius: radius.pill, backgroundColor: colors.surfaceSecondary, fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurfaceSecondary, marginRight: 6 },
  dowChipOn: { backgroundColor: colors.brand, color: "#FFFFFF" },
  toggle: { paddingHorizontal: 12, paddingVertical: 4, borderRadius: radius.pill, fontFamily: font.bold, fontSize: fontSize.sm },
  toggleOn: { backgroundColor: "#DCFCE7", color: colors.success },
  toggleOff: { backgroundColor: colors.surfaceSecondary, color: colors.muted },
});
