// Phase 38 · Feb-2026 — Mobile OptimizeRoute (P1.4).
//
// Web parity: `frontend/src/pages/dispatch/OptimizeRouteModal.jsx`.
// Backend:
//   POST /api/dispatch/route/optimize  (dry-run preview)
//   POST /api/dispatch/route/apply     (persist new order)
//
// Screen flow: params `tech_user_id` + `day` come in via
// `router.push({ pathname: "/dispatch/optimize", params: { tech, day } })`.
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, RefreshControl,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { router, useLocalSearchParams } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Card, Loading, EmptyState, PrimaryButton } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";
import { RoleGate } from "@/src/components/RoleGate";
import { showConfirm } from "@/src/components/ConfirmModal";

function _fmtKm(n: any): string {
  if (n == null || Number.isNaN(Number(n))) return "—";
  return `${Number(n).toFixed(2)} km`;
}

export default function OptimizeRoutePage() {
  const { tech, day, techName } = useLocalSearchParams<{
    tech: string; day: string; techName?: string;
  }>();
  const [loading, setLoading] = useState(true);
  const [preview, setPreview] = useState<any>(null);
  const [applying, setApplying] = useState(false);
  const [err, setErr] = useState<string>("");

  const load = useCallback(async () => {
    if (!tech || !day) return;
    setLoading(true); setErr("");
    try {
      const r: any = await api.post("/dispatch/route/optimize", {
        tech_user_id: tech, route_date: day,
      });
      setPreview(r);
    } catch (e: any) {
      setErr(e?.body?.detail || e?.message || "Failed to compute route");
      setPreview(null);
    } finally {
      setLoading(false);
    }
  }, [tech, day]);

  useEffect(() => { load(); }, [load]);

  const apply = useCallback(() => {
    if (!preview) return;
    const stops = (preview.ordered_jobs || []).length;
    showConfirm({
      title: `Apply new route order?`,
      description: `Persists ${stops} stops in the new sequence for ${techName || tech} on ${day}. Existing hand-order will be overwritten.`,
      confirmLabel: "Apply order",
      testID: "dispatch-optimize-apply-confirm",
      onConfirm: async () => {
        setApplying(true);
        try {
          const ids = (preview.ordered_jobs || []).map((j: any) => j.job_id);
          await api.post("/dispatch/route/apply", {
            tech_user_id: tech, route_date: day, ordered_job_ids: ids,
          });
          router.back();
        } catch { /* ignore */ } finally { setApplying(false); }
      },
    });
  }, [preview, tech, day, techName]);

  const legs = preview?.proposed_legs || preview?.legs || [];
  const skipped = preview?.skipped || [];
  const savings = preview?.savings_km ?? preview?.savings ?? null;

  return (
    <RoleGate level="strict_admin">
      <View style={styles.container} testID="dispatch-optimize-page">
        <Header title="Optimize Route" />
        <ScrollView
          contentContainerStyle={styles.body}
          refreshControl={<RefreshControl refreshing={false} onRefresh={load} />}
        >
          {loading ? (
            <Loading />
          ) : err ? (
            <EmptyState icon="warning-outline" title="Couldn't compute" subtitle={err} testID="dispatch-optimize-error" />
          ) : (
            <>
              <Card style={styles.summary}>
                <Text style={styles.tech}>{techName || tech}</Text>
                <Text style={styles.day}>Route date · {day}</Text>
                <View style={styles.savings}>
                  <Text style={styles.savingsLabel}>Estimated savings</Text>
                  <Text style={[styles.savingsValue, savings > 0 && { color: colors.success }]}>
                    {_fmtKm(savings)}
                  </Text>
                </View>
              </Card>

              <Text style={styles.section}>Proposed order ({legs.length} legs)</Text>
              {legs.length === 0 ? (
                <Text style={styles.emptyText}>No proposed legs — route already optimal.</Text>
              ) : (
                legs.map((l: any, i: number) => (
                  <View key={i} style={styles.leg} testID={`dispatch-optimize-leg-${i}`}>
                    <Text style={styles.legIdx}>{i + 1}</Text>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.legName}>{l.customer_name || l.name || "—"}</Text>
                      <Text style={styles.legDist}>
                        Leg {_fmtKm(l.leg_km)} · Cum {_fmtKm(l.cumulative_km)}
                      </Text>
                    </View>
                  </View>
                ))
              )}

              {skipped.length > 0 && (
                <View style={styles.skipped} testID="dispatch-optimize-skipped">
                  <Text style={styles.skippedHead}>Skipped ({skipped.length})</Text>
                  {skipped.map((s: any, i: number) => (
                    <Text key={i} style={styles.skippedItem}>
                      • {s.customer_name || s.reason || "—"}
                    </Text>
                  ))}
                </View>
              )}

              <PrimaryButton
                label={applying ? "Applying…" : "Apply order"}
                onPress={apply}
                disabled={applying || legs.length === 0}
                testID="dispatch-optimize-apply"
              />
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
  summary: { gap: spacing.xs },
  tech: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  day: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  savings: {
    flexDirection: "row", justifyContent: "space-between", alignItems: "center",
    marginTop: spacing.sm, paddingTop: spacing.sm,
    borderTopWidth: 1, borderTopColor: colors.border,
  },
  savingsLabel: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted },
  savingsValue: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  section: { fontFamily: font.semibold, fontSize: fontSize.md, color: colors.onSurface, marginTop: spacing.sm },
  emptyText: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, fontStyle: "italic" },
  leg: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    padding: spacing.sm, borderRadius: radius.sm, borderWidth: 1,
    borderColor: colors.border, backgroundColor: colors.surface,
  },
  legIdx: {
    width: 28, height: 28, borderRadius: 14, textAlign: "center",
    lineHeight: 28, fontFamily: font.bold, fontSize: fontSize.sm,
    backgroundColor: colors.brandTertiary, color: colors.brand,
  },
  legName: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface },
  legDist: { fontFamily: font.regular, fontSize: 11, color: colors.muted, marginTop: 2 },
  skipped: {
    padding: spacing.md, borderRadius: radius.sm,
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1, borderColor: colors.border, gap: 4,
  },
  skippedHead: { fontFamily: font.bold, fontSize: 11, color: colors.warning || colors.muted, letterSpacing: 0.5 },
  skippedItem: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
});
