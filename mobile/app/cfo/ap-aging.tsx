// Phase 36 · Feb-2026 — Mobile CFO AP Aging (P1.2 CFO Deep-Dives).
//
// Web parity: `frontend/src/pages/admin/CFOReports.jsx` (AP aging slice).
// Backend: GET /api/cfo/ap-aging.
// Admin / super-admin only.
import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, RefreshControl,
} from "react-native";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize, money } from "@/src/theme";
import { Card, Loading, EmptyState } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";
import { RoleGate } from "@/src/components/RoleGate";

type Bucket = { label: string; total_cents: number };

const BUCKET_LABELS: Record<string, string> = {
  "0_30": "0–30 days",
  "31_60": "31–60 days",
  "61_90": "61–90 days",
  "90_plus": "90+ days",
};

export default function CfoApAging() {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [err, setErr] = useState<string>("");

  const load = useCallback(async () => {
    setLoading(true); setErr("");
    try {
      const r: any = await api.get("/cfo/ap-aging");
      setData(r);
    } catch (e: any) {
      setErr(e?.message || "Failed to load AP aging.");
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const buckets: Bucket[] = Object.entries(data?.buckets || {}).map(([k, v]: any) => ({
    label: BUCKET_LABELS[k] || k,
    total_cents: (v && v.total_cents) || 0,
  }));
  const rows = Array.isArray(data?.rows) ? data.rows : [];
  const total = buckets.reduce((sum, b) => sum + (b.total_cents || 0), 0);

  return (
    <RoleGate level="strict_admin">
      <View style={styles.container} testID="cfo-ap-aging-page">
        <Header title="AP Aging" />
        <ScrollView
          contentContainerStyle={styles.body}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={async () => {
              setRefreshing(true); await load(); setRefreshing(false);
            }} />
          }
        >
          {loading ? (
            <Loading />
          ) : err ? (
            <EmptyState
              icon="warning-outline"
              title="Couldn't load AP aging"
              subtitle={err}
              testID="cfo-ap-aging-error"
            />
          ) : (
            <>
              <Card style={styles.summary}>
                <Text style={styles.summaryLabel}>Total open</Text>
                <Text style={styles.summaryValue}>{money(total / 100)}</Text>
              </Card>
              {buckets.map((b) => (
                <View
                  key={b.label}
                  style={styles.bucketRow}
                  testID={`cfo-ap-bucket-${b.label.replace(/\s+/g, "-").toLowerCase()}`}
                >
                  <Text style={styles.bucketLabel}>{b.label}</Text>
                  <Text style={styles.bucketValue}>{money((b.total_cents || 0) / 100)}</Text>
                </View>
              ))}
              {rows.length === 0 ? null : (
                <View style={{ marginTop: spacing.md }}>
                  <Text style={styles.sectionTitle}>Open bills</Text>
                  {rows.map((r: any) => (
                    <View key={r.id} style={styles.billRow} testID={`cfo-ap-row-${r.id}`}>
                      <View style={{ flex: 1 }}>
                        <Text style={styles.vendor}>{r.vendor_name}</Text>
                        <Text style={styles.due}>Due {r.due_date || "—"}</Text>
                      </View>
                      <Text style={styles.billAmount}>
                        {money((r.amount_cents || 0) / 100)}
                      </Text>
                    </View>
                  ))}
                </View>
              )}
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
  summary: { gap: 4 },
  summaryLabel: { fontFamily: font.medium, fontSize: 11, textTransform: "uppercase", color: colors.muted, letterSpacing: 0.5 },
  summaryValue: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface },
  bucketRow: {
    flexDirection: "row", justifyContent: "space-between", alignItems: "center",
    padding: spacing.md, borderRadius: radius.md, borderWidth: 1,
    borderColor: colors.border, backgroundColor: colors.surface,
  },
  bucketLabel: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurface },
  bucketValue: { fontFamily: font.bold, fontSize: fontSize.md, color: colors.onSurface },
  sectionTitle: { fontFamily: font.semibold, fontSize: fontSize.md, color: colors.onSurface, marginBottom: spacing.sm },
  billRow: {
    flexDirection: "row", justifyContent: "space-between", alignItems: "center",
    padding: spacing.sm, borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  vendor: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurface },
  due: { fontFamily: font.regular, fontSize: 11, color: colors.muted, marginTop: 2 },
  billAmount: { fontFamily: font.bold, fontSize: fontSize.sm, color: colors.onSurface },
});
