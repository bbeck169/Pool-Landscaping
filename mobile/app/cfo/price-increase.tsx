// Phase 36 · Feb-2026 — Mobile CFO Price-Increase Suggestions (P1.2).
//
// Web parity: `frontend/src/pages/admin/PricingInsights.jsx`.
// Backend: POST /api/cfo/price-increase-suggestions with { month: "YYYY-MM" }.
// Admin / super-admin only.
import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, RefreshControl, TextInput,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize, money } from "@/src/theme";
import { Card, Loading, EmptyState, PrimaryButton } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";
import { RoleGate } from "@/src/components/RoleGate";

function _currentMonth(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

export default function CfoPriceIncrease() {
  const [month, setMonth] = useState(_currentMonth());
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [err, setErr] = useState<string>("");

  const load = useCallback(async () => {
    setLoading(true); setErr("");
    try {
      const r: any = await api.post("/cfo/price-increase-suggestions", { month });
      setData(r);
    } catch (e: any) {
      setErr(e?.message || "Failed to generate suggestions.");
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [month]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const suggestions = Array.isArray(data?.suggestions)
    ? data.suggestions
    : Array.isArray(data?.items) ? data.items : [];

  return (
    <RoleGate level="strict_admin">
      <View style={styles.container} testID="cfo-price-increase-page">
        <Header title="Price Increase" />
        <ScrollView
          contentContainerStyle={styles.body}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={async () => {
              setRefreshing(true); await load(); setRefreshing(false);
            }} />
          }
        >
          <View style={styles.monthRow}>
            <Text style={styles.monthLabel}>Analysis month (YYYY-MM)</Text>
            <TextInput
              value={month}
              onChangeText={setMonth}
              placeholder="2026-02"
              style={styles.input}
              testID="cfo-price-increase-month-input"
            />
            <PrimaryButton
              label={loading ? "Analyzing…" : "Regenerate"}
              onPress={load}
              disabled={loading || !/^\d{4}-\d{2}$/.test(month)}
              testID="cfo-price-increase-regenerate"
            />
          </View>

          {loading ? (
            <Loading />
          ) : err ? (
            <EmptyState
              icon="warning-outline"
              title="Couldn't generate suggestions"
              subtitle={err}
              testID="cfo-price-increase-error"
            />
          ) : suggestions.length === 0 ? (
            <EmptyState
              icon="trending-up-outline"
              title="No price-increase candidates"
              subtitle="No services flagged as under-priced for this month."
              testID="cfo-price-increase-empty"
            />
          ) : (
            <>
              <Text style={styles.sectionTitle}>
                {suggestions.length} suggestion{suggestions.length === 1 ? "" : "s"}
              </Text>
              {suggestions.map((s: any, idx: number) => (
                <View
                  key={s.id || `${s.service}-${idx}`}
                  style={styles.row}
                  testID={`cfo-price-increase-row-${idx}`}
                >
                  <View style={styles.rowHead}>
                    <Text style={styles.service}>
                      {s.service_name || s.service || "—"}
                    </Text>
                    {typeof s.proposed_increase_pct === "number" && (
                      <Text style={styles.pct}>
                        +{s.proposed_increase_pct.toFixed(1)}%
                      </Text>
                    )}
                  </View>
                  <View style={styles.priceRow}>
                    <View>
                      <Text style={styles.priceLabel}>Current</Text>
                      <Text style={styles.priceValue}>
                        {money(((s.current_price_cents ?? s.current_cents) || 0) / 100)}
                      </Text>
                    </View>
                    <Ionicons name="arrow-forward" size={16} color={colors.muted} />
                    <View>
                      <Text style={styles.priceLabel}>Suggested</Text>
                      <Text style={[styles.priceValue, { color: colors.brand }]}>
                        {money(((s.suggested_price_cents ?? s.suggested_cents) || 0) / 100)}
                      </Text>
                    </View>
                  </View>
                  {s.rationale ? (
                    <Text style={styles.rationale} numberOfLines={3}>{s.rationale}</Text>
                  ) : null}
                </View>
              ))}
            </>
          )}
        </ScrollView>
      </View>
    </RoleGate>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.surface },
  body: { padding: spacing.lg, gap: spacing.sm, paddingBottom: spacing["3xl"] },
  monthRow: { gap: spacing.sm },
  monthLabel: { fontFamily: font.medium, fontSize: 10, textTransform: "uppercase", color: colors.muted, letterSpacing: 0.5 },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.sm,
    padding: spacing.sm, fontFamily: font.regular, fontSize: fontSize.md,
    backgroundColor: colors.surface,
  },
  sectionTitle: { fontFamily: font.semibold, fontSize: fontSize.md, color: colors.onSurface },
  row: {
    padding: spacing.md, borderRadius: radius.md, borderWidth: 1,
    borderColor: colors.border, backgroundColor: colors.surface, gap: spacing.sm,
  },
  rowHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  service: { fontFamily: font.semibold, fontSize: fontSize.md, color: colors.onSurface, flex: 1 },
  pct: { fontFamily: font.bold, fontSize: fontSize.md, color: colors.brand },
  priceRow: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  priceLabel: { fontFamily: font.medium, fontSize: 10, textTransform: "uppercase", color: colors.muted, letterSpacing: 0.5 },
  priceValue: { fontFamily: font.bold, fontSize: fontSize.md, color: colors.onSurface, marginTop: 2 },
  rationale: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
});
