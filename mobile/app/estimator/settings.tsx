import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, TextInput, Platform, Alert } from "react-native";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import { Loading, PrimaryButton } from "@/src/components/ui";

export default function EstimateSettings() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [overhead, setOverhead] = useState("15");
  const [margin, setMargin] = useState("30");

  const load = useCallback(async () => {
    try {
      const s = await api.get("/estimates/settings");
      setOverhead(String(s.overhead_pct ?? 15));
      setMargin(String(s.margin_pct ?? 30));
    } catch {}
    finally { setLoading(false); }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const save = async () => {
    setSaving(true);
    try {
      await api.put("/estimates/settings", { overhead_pct: parseFloat(overhead) || 0, margin_pct: parseFloat(margin) || 0 });
      Alert.alert("Saved", "Default overhead and margin updated.");
    } catch (e: any) { Alert.alert("Error", e.message || "Could not save."); }
    finally { setSaving(false); }
  };

  if (loading) return <Loading testID="estimate-settings-loading" />;

  return (
    <View style={styles.root}>
      <Header title="Estimate Defaults" back subtitle="Applied to new estimates" />
      <View style={{ padding: spacing.lg }}>
        <Text style={styles.hint}>Set your company overhead recovery and target profit margin. New estimates start with these values.</Text>
        <Text style={styles.label}>Default overhead %</Text>
        <TextInput style={styles.input} value={overhead} onChangeText={(v) => setOverhead(v.replace(/[^0-9.]/g, ""))} keyboardType="decimal-pad" testID="settings-overhead" />
        <Text style={styles.label}>Default profit margin %</Text>
        <TextInput style={styles.input} value={margin} onChangeText={(v) => setMargin(v.replace(/[^0-9.]/g, ""))} keyboardType="decimal-pad" testID="settings-margin" />
        <View style={{ height: spacing.lg }} />
        <PrimaryButton title="Save Defaults" icon="checkmark" loading={saving} onPress={save} testID="settings-save" />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  hint: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted, marginBottom: spacing.sm, lineHeight: 20 },
  label: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurfaceSecondary, marginBottom: spacing.xs, marginTop: spacing.md },
  input: { backgroundColor: colors.surface, borderWidth: 1.5, borderColor: colors.border, borderRadius: radius.md, paddingHorizontal: spacing.md, height: 48, fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}) },
});
