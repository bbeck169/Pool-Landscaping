// Phase 16 · Feb-2026 — AEO Auditor (mobile parity, read-focused).
//
// Enter a URL, tap "Scan", render the top-level `aeo_signals` object as a
// keyed list. Below that, a read-only history of the tenant's recent
// scans (from the visibility history endpoint).
import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TextInput, Pressable,
  ActivityIndicator, RefreshControl,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Card, EmptyState, PrimaryButton } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";
import { RoleGate } from "@/src/components/RoleGate";

type ScanResult = {
  aeo_signals?: Record<string, any>;
  score?: number | null;
  scanned_url?: string;
  scanned_at?: string;
};

type HistoryRow = {
  id: string;
  scanned_at?: string;
  target_url?: string;
  score?: number | null;
};

function _renderSignalValue(v: any): string {
  if (v == null) return "—";
  if (typeof v === "boolean") return v ? "✓" : "✗";
  if (typeof v === "number") return String(v);
  if (Array.isArray(v)) return `${v.length} items`;
  if (typeof v === "object") return JSON.stringify(v).slice(0, 40);
  return String(v).slice(0, 60);
}

export default function AeoAuditor() {
  const [url, setUrl] = useState("");
  const [scanning, setScanning] = useState(false);
  const [result, setResult] = useState<ScanResult | null>(null);
  const [errMsg, setErrMsg] = useState("");
  const [history, setHistory] = useState<HistoryRow[]>([]);
  const [refreshing, setRefreshing] = useState(false);

  const loadHistory = useCallback(async () => {
    try {
      const j: any = await api.get("/aeo/visibility/history?limit=15");
      setHistory((j?.items || j?.history || j || []).slice(0, 15));
    } catch {
      setHistory([]);
    }
  }, []);

  useFocusEffect(useCallback(() => { loadHistory(); }, [loadHistory]));

  const scan = async () => {
    if (!url.trim()) return;
    setScanning(true);
    setErrMsg("");
    try {
      const j: any = await api.post("/aeo/visibility/run-now", {
        target_url: url.trim(),
      });
      setResult({
        aeo_signals: j?.aeo_signals || j?.signals || {},
        score: j?.score ?? null,
        scanned_url: url.trim(),
        scanned_at: new Date().toISOString(),
      });
      await loadHistory();
    } catch (err: any) {
      setErrMsg(String(err?.message || err));
    } finally {
      setScanning(false);
    }
  };

  return (
    <RoleGate level="admin_plus">
      <View style={styles.container}>
        <Header title="AEO Auditor" />
        <ScrollView
          contentContainerStyle={styles.body}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={async () => {
              setRefreshing(true); await loadHistory(); setRefreshing(false);
            }} />
          }
        >
          <Card>
            <Text style={styles.sectionLabel}>Scan a URL</Text>
            <TextInput
              testID="aeo-auditor-url-input"
              value={url}
              onChangeText={setUrl}
              placeholder="https://example.com/services/pools"
              placeholderTextColor={colors.muted}
              autoCapitalize="none"
              keyboardType="url"
              style={styles.input}
            />
            <PrimaryButton
              testID="aeo-auditor-scan-btn"
              title={scanning ? "Scanning…" : "Scan now"}
              icon="search"
              onPress={scan}
              loading={scanning}
              disabled={!url.trim()}
            />
            {errMsg ? (
              <Text style={styles.err} testID="aeo-auditor-error">{errMsg}</Text>
            ) : null}
          </Card>

          {result ? (
            <Card>
              <View style={styles.rowBetween}>
                <Text style={styles.sectionLabel}>Signals</Text>
                {result.score != null ? (
                  <Text style={styles.scoreInline}>Score: {result.score}</Text>
                ) : null}
              </View>
              {Object.keys(result.aeo_signals || {}).length === 0 ? (
                <Text style={styles.hint}>Scan returned no signals.</Text>
              ) : (
                Object.entries(result.aeo_signals || {}).map(([k, v]) => (
                  <View key={k} style={styles.signalRow} testID={`aeo-signal-${k}`}>
                    <Text style={styles.signalKey}>{k}</Text>
                    <Text style={styles.signalVal}>{_renderSignalValue(v)}</Text>
                  </View>
                ))
              )}
            </Card>
          ) : null}

          <Card>
            <Text style={styles.sectionLabel}>Recent scans</Text>
            {history.length === 0 ? (
              <EmptyState
                icon="time-outline"
                title="No scan history yet"
                subtitle="Run your first scan to build history."
                testID="aeo-auditor-history-empty"
              />
            ) : (
              history.map((h) => (
                <View key={h.id} style={styles.histRow} testID={`aeo-history-${h.id}`}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.histUrl} numberOfLines={1}>
                      {h.target_url || "(url missing)"}
                    </Text>
                    <Text style={styles.histAt}>
                      {h.scanned_at ? new Date(h.scanned_at).toLocaleString() : "—"}
                    </Text>
                  </View>
                  <View style={styles.histBadge}>
                    <Text style={styles.histBadgeText}>{h.score ?? "—"}</Text>
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

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.surface },
  body: { padding: spacing.lg, gap: spacing.md, paddingBottom: spacing["3xl"] },
  sectionLabel: {
    fontFamily: font.semibold,
    fontSize: fontSize.base,
    color: colors.onSurface,
    marginBottom: spacing.sm,
  },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    padding: spacing.md, fontFamily: font.regular,
    fontSize: fontSize.base, color: colors.onSurface,
    marginBottom: spacing.md,
  },
  err: { marginTop: spacing.sm, color: colors.error, fontFamily: font.medium, fontSize: fontSize.sm },
  hint: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  signalRow: {
    flexDirection: "row", justifyContent: "space-between",
    paddingVertical: 6, borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.divider,
  },
  signalKey: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurface, flex: 1, marginRight: spacing.sm },
  signalVal: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  rowBetween: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  scoreInline: { fontFamily: font.semibold, color: colors.brand },
  histRow: {
    flexDirection: "row", alignItems: "center", gap: spacing.md,
    paddingVertical: 8,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.divider,
  },
  histUrl: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurface },
  histAt: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
  histBadge: {
    minWidth: 40, paddingHorizontal: 8, paddingVertical: 4,
    borderRadius: radius.pill, backgroundColor: colors.brandTertiary,
  },
  histBadgeText: { fontFamily: font.bold, fontSize: fontSize.sm, color: colors.onBrandTertiary, textAlign: "center" },
});
