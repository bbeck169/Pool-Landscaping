import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, RefreshControl,
  TouchableOpacity, ActivityIndicator, Alert, KeyboardAvoidingView, Platform } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useLocalSearchParams, useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import AppTextInput from "@/src/components/ui/AppTextInput";

const READINGS = [
  { k: "fc", label: "FC (ppm)", range: "Target 1\u20134" },
  { k: "ph", label: "pH", range: "Target 7.4\u20137.6" },
  { k: "ta", label: "TA (ppm)", range: "Target 80\u2013120" },
  { k: "cya", label: "CYA (ppm)", range: "Target 30\u201350" },
  { k: "salt", label: "Salt (ppm)", range: "Optional" },
];

function bandColor(val: number, k: string): string {
  if (k === "fc") return val < 1 ? "#DC2626" : val <= 4 ? "#16A34A" : "#EAB308";
  if (k === "ph") return val < 7.2 ? "#DC2626" : val <= 7.8 ? "#16A34A" : "#EAB308";
  if (k === "ta") return val < 60 ? "#DC2626" : val <= 140 ? "#16A34A" : "#EAB308";
  if (k === "cya") return val < 20 ? "#DC2626" : val <= 70 ? "#16A34A" : "#EAB308";
  return "#16A34A";
}

export default function CustomerChemistry() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const [customer, setCustomer] = useState<any>(null);
  const [volume, setVolume] = useState("15000");
  const [readings, setReadings] = useState<Record<string, string>>({ fc: "", ph: "", ta: "", cya: "", salt: "" });
  const [rec, setRec] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const c = await api.get(`/customers/${id}`);
      setCustomer(c);
    } catch {}
    finally { setRefreshing(false); }
  }, [id]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const recommend = async () => {
    setBusy(true);
    setError("");
    setRec(null);
    try {
      const cleaned: Record<string, number> = {};
      Object.entries(readings).forEach(([k, v]) => {
        if (v !== "" && v !== null) cleaned[k] = Number(v);
      });
      const result = await api.post("/chemicals/dosing-recommendation", {
        volume_gal: Number(volume) || 15000,
        readings: cleaned,
      });
      setRec(result);
    } catch (e: any) {
      setError(e?.message || "Failed to get recommendation");
    } finally {
      setBusy(false);
    }
  };

  const hasReadings = Object.values(readings).some((v) => v.trim() !== "");

  return (
    <View style={s.root}>
      <Header
        title="Chemistry"
        subtitle={customer?.name || "Pool chemistry"}
        back
      />
      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : undefined}
        style={{ flex: 1 }}
      >
        <ScrollView
          testID="customer-chemistry-page"
          contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
          keyboardShouldPersistTaps="handled"
        >
          {/* Volume */}
          <View style={s.card}>
            <Text style={s.sectionLabel}>POOL VOLUME</Text>
            <View style={s.volumeRow}>
              <AppTextInput
                style={s.volumeInput}
                value={volume}
                onChangeText={setVolume}
                keyboardType="numeric"
                testID="chemistry-volume-input"
              />
              <Text style={s.volumeUnit}>gallons</Text>
            </View>
          </View>

          {/* Readings */}
          <View style={s.card}>
            <Text style={s.sectionLabel}>WATER READINGS</Text>
            {READINGS.map((r) => (
              <View key={r.k} style={s.readingRow}>
                <View style={{ flex: 1 }}>
                  <Text style={s.readingLabel}>{r.label}</Text>
                  <Text style={s.readingRange}>{r.range}</Text>
                </View>
                <AppTextInput
                  style={[
                    s.readingInput,
                    readings[r.k]
                      ? { borderColor: bandColor(Number(readings[r.k]), r.k) }
                      : {},
                  ]}
                  value={readings[r.k]}
                  onChangeText={(v) => setReadings((prev) => ({ ...prev, [r.k]: v }))}
                  keyboardType="decimal-pad"
                  placeholder="\u2014"
                  placeholderTextColor={colors.muted}
                  testID={`chemistry-reading-${r.k}`}
                />
              </View>
            ))}
          </View>

          {/* Recommend button */}
          <TouchableOpacity
            style={[s.recBtn, (!hasReadings || busy) && { opacity: 0.5 }]}
            onPress={recommend}
            disabled={!hasReadings || busy}
            testID="chemistry-recommend-btn"
          >
            {busy ? (
              <ActivityIndicator size="small" color="#fff" />
            ) : (
              <>
                <Ionicons name="flask" size={18} color="#fff" />
                <Text style={s.recBtnText}>Get Dosing Recommendation</Text>
              </>
            )}
          </TouchableOpacity>

          {error ? (
            <View style={s.errorBanner} testID="chemistry-error">
              <Ionicons name="alert-circle" size={16} color="#991B1B" />
              <Text style={s.errorText}>{error}</Text>
            </View>
          ) : null}

          {/* Recommendation results */}
          {rec ? (
            <View style={s.recCard} testID="chemistry-recommendation">
              <View style={s.recHeader}>
                <Ionicons name="sparkles" size={18} color={colors.brand} />
                <Text style={s.recTitle}>Dosing Recommendation</Text>
              </View>
              {rec.summary ? <Text style={s.recSummary}>{rec.summary}</Text> : null}
              {(rec.dosages || rec.items || []).map((d: any, i: number) => (
                <View key={i} style={s.dosageRow} testID={`chemistry-dosage-${i}`}>
                  <View style={s.dosageIcon}>
                    <Ionicons name="flask-outline" size={14} color={colors.brand} />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={s.dosageName}>{d.chemical || d.name}</Text>
                    {d.reason ? <Text style={s.dosageReason}>{d.reason}</Text> : null}
                  </View>
                  <Text style={s.dosageAmount}>
                    {d.amount || d.dose} {d.unit || "oz"}
                  </Text>
                </View>
              ))}
              {rec.estimated_cost != null ? (
                <View style={s.costRow}>
                  <Text style={s.costLabel}>Estimated cost</Text>
                  <Text style={s.costValue}>${Number(rec.estimated_cost).toFixed(2)}</Text>
                </View>
              ) : null}
            </View>
          ) : null}
        </ScrollView>
      </KeyboardAvoidingView>
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  card: {
    backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.lg,
    borderWidth: 1, borderColor: colors.border, marginBottom: spacing.md,
  },
  sectionLabel: {
    fontFamily: font.bold, fontSize: 10, textTransform: "uppercase",
    letterSpacing: 1, color: colors.muted, marginBottom: spacing.md,
  },
  volumeRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  volumeInput: {
    flex: 1, backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border,
    borderRadius: radius.md, paddingHorizontal: spacing.md, paddingVertical: spacing.md,
    fontFamily: font.semibold, fontSize: fontSize.lg, color: colors.onSurface,
  },
  volumeUnit: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted },
  readingRow: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingVertical: spacing.sm, borderBottomWidth: 1, borderBottomColor: colors.divider,
  },
  readingLabel: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  readingRange: { fontFamily: font.regular, fontSize: 11, color: colors.muted },
  readingInput: {
    width: 80, backgroundColor: colors.surfaceSecondary, borderWidth: 1.5, borderColor: colors.border,
    borderRadius: radius.md, paddingHorizontal: spacing.sm, paddingVertical: 8,
    fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface, textAlign: "center",
  },
  recBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    backgroundColor: colors.brand, paddingVertical: 16, borderRadius: radius.md, marginBottom: spacing.md,
  },
  recBtnText: { fontFamily: font.bold, fontSize: fontSize.base, color: "#fff" },
  errorBanner: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    padding: spacing.md, borderRadius: radius.md,
    backgroundColor: "#FEE2E2", borderWidth: 1, borderColor: "#FCA5A5",
    marginBottom: spacing.md,
  },
  errorText: { fontFamily: font.medium, fontSize: fontSize.sm, color: "#991B1B", flex: 1 },
  recCard: {
    backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.lg,
    borderWidth: 1, borderColor: colors.brand + "44",
  },
  recHeader: { flexDirection: "row", alignItems: "center", gap: spacing.sm, marginBottom: spacing.md },
  recTitle: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  recSummary: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurfaceSecondary, marginBottom: spacing.md, lineHeight: 20 },
  dosageRow: {
    flexDirection: "row", alignItems: "center", gap: spacing.md,
    paddingVertical: spacing.sm, borderBottomWidth: 1, borderBottomColor: colors.divider,
  },
  dosageIcon: {
    width: 30, height: 30, borderRadius: radius.sm, backgroundColor: colors.brandTertiary,
    alignItems: "center", justifyContent: "center",
  },
  dosageName: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  dosageReason: { fontFamily: font.regular, fontSize: 11, color: colors.muted, marginTop: 1 },
  dosageAmount: { fontFamily: font.bold, fontSize: fontSize.base, color: colors.brand },
  costRow: {
    flexDirection: "row", justifyContent: "space-between", alignItems: "center",
    paddingTop: spacing.md, marginTop: spacing.sm, borderTopWidth: 1, borderTopColor: colors.divider,
  },
  costLabel: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted },
  costValue: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
});
