// Phase 16 · Feb-2026 — AI Visibility dashboard (mobile parity, read).
//
// KPI cards + latest 10 probes as mobile cards + "Run scan now" with a
// cooldown state pulled from the dashboard endpoint (falls back to a
// local 60s cooldown if the backend doesn't report one).
import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, RefreshControl,
} from "react-native";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Card, EmptyState, PrimaryButton } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";
import { RoleGate } from "@/src/components/RoleGate";

type Probe = {
  id?: string;
  provider?: string;
  brand_mentioned?: boolean;
  score?: number | null;
  query?: string;
  ran_at?: string;
};

type Dashboard = {
  summary?: {
    avg_score?: number;
    brand_mentions?: number;
    providers_checked?: number;
    cooldown_seconds?: number;
    est_cost_usd?: number;
  };
  latest?: Probe[];
};

export default function AeoVisibility() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [running, setRunning] = useState(false);
  const [cooldownLeft, setCooldownLeft] = useState(0);
  const timerRef = useRef<any>(null);

  const load = useCallback(async () => {
    try {
      const j: any = await api.get("/aeo/visibility/dashboard");
      setData(j || null);
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  useEffect(() => () => { if (timerRef.current) clearInterval(timerRef.current); }, []);

  const run = async () => {
    setRunning(true);
    try {
      await api.post("/aeo/visibility/run-now", {});
      await load();
      // Start a soft cooldown clock.
      const seconds = data?.summary?.cooldown_seconds || 60;
      setCooldownLeft(seconds);
      if (timerRef.current) clearInterval(timerRef.current);
      timerRef.current = setInterval(() => {
        setCooldownLeft((s) => {
          if (s <= 1) { clearInterval(timerRef.current); return 0; }
          return s - 1;
        });
      }, 1000);
    } catch {
      // silent — user just sees the button re-enable.
    } finally {
      setRunning(false);
    }
  };

  const summary = data?.summary || {};
  const latest = (data?.latest || []).slice(0, 10);

  return (
    <RoleGate level="admin_plus">
      <View style={styles.container}>
        <Header title="AI Visibility" />
        <ScrollView
          contentContainerStyle={styles.body}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={async () => {
              setRefreshing(true); await load(); setRefreshing(false);
            }} />
          }
        >
          <View style={styles.kpiRow}>
            <Kpi label="Avg score" value={summary.avg_score != null ? String(Math.round(summary.avg_score)) : "—"} tid="kpi-avg-score" />
            <Kpi label="Brand mentions" value={String(summary.brand_mentions ?? "—")} tid="kpi-brand-mentions" />
            <Kpi label="Providers" value={String(summary.providers_checked ?? "—")} tid="kpi-providers" />
          </View>

          <Card>
            <Text style={styles.sectionLabel}>Run a new visibility probe</Text>
            <Text style={styles.hint}>
              Estimated cost per run:{" "}
              <Text style={{ color: colors.onSurface, fontFamily: font.semibold }}>
                ${(summary.est_cost_usd ?? 0.05).toFixed(2)}
              </Text>
            </Text>
            <PrimaryButton
              title={
                cooldownLeft > 0
                  ? `Cooldown ${cooldownLeft}s`
                  : running
                  ? "Running…"
                  : "Run scan now"
              }
              icon="rocket-outline"
              onPress={run}
              loading={running}
              disabled={running || cooldownLeft > 0}
              testID="aeo-visibility-run-btn"
            />
          </Card>

          <Card>
            <Text style={styles.sectionLabel}>Latest probes</Text>
            {latest.length === 0 ? (
              <EmptyState
                icon="pulse-outline"
                title="No probes yet"
                subtitle="Run a scan to see visibility across AI answer engines."
                testID="aeo-visibility-empty"
              />
            ) : (
              latest.map((p, i) => (
                <View key={p.id || i} style={styles.probeRow} testID={`aeo-probe-${p.id || i}`}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.probeQuery} numberOfLines={1}>
                      {p.query || "(query hidden)"}
                    </Text>
                    <Text style={styles.probeMeta}>
                      {p.provider || "?"} · {p.ran_at ? new Date(p.ran_at).toLocaleString() : "—"}
                    </Text>
                  </View>
                  <View style={[styles.mentionPill, {
                    backgroundColor: p.brand_mentioned ? "#DCFCE7" : colors.surfaceTertiary,
                  }]}>
                    <Text style={{
                      color: p.brand_mentioned ? colors.success : colors.muted,
                      fontFamily: font.semibold, fontSize: fontSize.sm,
                    }}>{p.brand_mentioned ? "Mentioned" : "Absent"}</Text>
                  </View>
                </View>
              ))
            )}
          </Card>
        </ScrollView>
      </View>
    </RoleGate>
  );
}

function Kpi({ label, value, tid }: { label: string; value: string; tid?: string }) {
  return (
    <View style={styles.kpi} testID={tid}>
      <Text style={styles.kpiLabel}>{label}</Text>
      <Text style={styles.kpiValue}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.surface },
  body: { padding: spacing.lg, gap: spacing.md, paddingBottom: spacing["3xl"] },
  kpiRow: { flexDirection: "row", gap: spacing.sm },
  kpi: {
    flex: 1, padding: spacing.md,
    borderRadius: radius.md, borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  kpiLabel: { fontFamily: font.medium, fontSize: 10, color: colors.muted, textTransform: "uppercase", letterSpacing: 0.4 },
  kpiValue: { fontFamily: font.bold, fontSize: 22, color: colors.onSurface, marginTop: 4 },
  sectionLabel: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface, marginBottom: spacing.sm },
  hint: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginBottom: spacing.md },
  probeRow: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    paddingVertical: 8,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.divider,
  },
  probeQuery: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurface },
  probeMeta: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
  mentionPill: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: radius.pill },
});
