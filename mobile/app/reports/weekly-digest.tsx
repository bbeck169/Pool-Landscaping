// Phase 16 · Feb-2026 — Weekly Digest settings + preview (Manager+).
import React, { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Alert } from "react-native";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Card, Loading, PrimaryButton } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";
import { RoleGate } from "@/src/components/RoleGate";
import AppTextInput from "@/src/components/ui/AppTextInput";

const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

type Settings = {
  enabled?: boolean;
  recipients?: string[];
  day_of_week?: number;
  hour?: number;
};

type Preview = {
  top?: { department?: string; total?: number }[];
  bottom?: { department?: string; total?: number }[];
  generated_at?: string;
};

export default function WeeklyDigest() {
  const [settings, setSettings] = useState<Settings>({});
  const [dowIdx, setDowIdx] = useState(1);
  const [hour, setHour] = useState(9);
  const [enabled, setEnabled] = useState(true);
  const [recipients, setRecipients] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const j: any = await api.get("/admin/weekly-digest/settings").catch(() => null);
      if (j) {
        setSettings(j);
        setEnabled(j.enabled ?? true);
        setDowIdx(j.day_of_week ?? 1);
        setHour(j.hour ?? 9);
        setRecipients((j.recipients || []).join(", "));
      }
    } catch { /* silent */ }
    setLoading(false);
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const save = async () => {
    setSaving(true);
    try {
      const body = {
        enabled,
        day_of_week: dowIdx,
        hour,
        recipients: recipients.split(",").map((s) => s.trim()).filter(Boolean),
      };
      await api.post("/admin/weekly-digest/settings", body);
      showToast("Weekly digest settings saved.");
    } catch (err: any) {
      Alert.alert("Save failed", String(err?.message || err));
    } finally {
      setSaving(false);
    }
  };

  const runPreview = async () => {
    setPreviewing(true);
    try {
      const j: any = await api.post("/admin/weekly-digest/preview", {});
      setPreview(j || null);
    } catch (err: any) {
      Alert.alert("Preview failed", String(err?.message || err));
    } finally {
      setPreviewing(false);
    }
  };

  return (
    <RoleGate level="admin_plus">
      <View style={styles.container}>
        <Header title="Weekly digest" />
        {loading ? (
          <Loading />
        ) : (
          <ScrollView contentContainerStyle={styles.body}>
            <Card>
              <Text style={styles.sectionLabel}>Recipients</Text>
              <AppTextInput
                testID="digest-recipients"
                value={recipients}
                onChangeText={setRecipients}
                placeholder="ops@company.com, owner@company.com"
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
                        <Text
                          key={d}
                          testID={`digest-dow-${i}`}
                          onPress={() => setDowIdx(i)}
                          style={[styles.dowChip, on && styles.dowChipOn]}
                        >{d}</Text>
                      );
                    })}
                  </ScrollView>
                </View>
                <View style={{ width: 80, marginLeft: spacing.md }}>
                  <Text style={styles.sectionLabel}>Hour</Text>
                  <AppTextInput
                    testID="digest-hour"
                    value={String(hour)}
                    onChangeText={(v) => setHour(Math.max(0, Math.min(23, parseInt(v || "0", 10))))}
                    keyboardType="number-pad"
                    style={styles.input}
                  />
                </View>
              </View>
              <View style={styles.rowBetween}>
                <Text style={styles.sectionLabel}>Enabled</Text>
                <Text
                  testID="digest-enabled-toggle"
                  onPress={() => setEnabled((v) => !v)}
                  style={[styles.toggle, enabled ? styles.toggleOn : styles.toggleOff]}
                >{enabled ? "ON" : "OFF"}</Text>
              </View>
              <View style={{ height: spacing.md }} />
              <PrimaryButton title={saving ? "Saving…" : "Save settings"} onPress={save} loading={saving} testID="digest-save" />
            </Card>

            <Card>
              <View style={styles.rowBetween}>
                <Text style={styles.sectionLabel}>Preview</Text>
                <PrimaryButton
                  variant="outline"
                  title={previewing ? "Loading…" : "Preview"}
                  onPress={runPreview}
                  loading={previewing}
                  testID="digest-preview-btn"
                />
              </View>
              {preview ? (
                <>
                  <Text style={styles.subLabel}>🏅 Top departments</Text>
                  {(preview.top || []).slice(0, 3).map((row, i) => (
                    <Text key={i} style={styles.leaderRow} testID={`digest-top-${i}`}>
                      {["🥇", "🥈", "🥉"][i] || "•"} {row.department || "—"} — ${(row.total || 0).toFixed(2)}
                    </Text>
                  ))}
                  <View style={{ height: spacing.sm }} />
                  <Text style={styles.subLabel}>Bottom departments</Text>
                  {(preview.bottom || []).slice(0, 3).map((row, i) => (
                    <Text key={i} style={[styles.leaderRow, { color: colors.muted }]} testID={`digest-bottom-${i}`}>
                      · {row.department || "—"} — ${(row.total || 0).toFixed(2)}
                    </Text>
                  ))}
                </>
              ) : (
                <Text style={styles.hint}>Tap Preview to render this week&apos;s digest.</Text>
              )}
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
  subLabel: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface, marginTop: spacing.sm },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    padding: spacing.md, fontFamily: font.regular, fontSize: fontSize.base,
    color: colors.onSurface, marginBottom: spacing.md,
  },
  rowBetween: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  dowChip: { paddingHorizontal: 10, paddingVertical: 6, borderRadius: radius.pill, backgroundColor: colors.surfaceSecondary, fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurfaceSecondary, marginRight: 6 },
  dowChipOn: { backgroundColor: colors.brand, color: "#FFFFFF" },
  toggle: { paddingHorizontal: 12, paddingVertical: 4, borderRadius: radius.pill, fontFamily: font.bold, fontSize: fontSize.sm },
  toggleOn: { backgroundColor: "#DCFCE7", color: colors.success },
  toggleOff: { backgroundColor: colors.surfaceSecondary, color: colors.muted },
  leaderRow: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, marginTop: 4 },
  hint: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
});
