// Phase 17 · Feb-2026 — QBO mobile connection status + sync (Manager+).
import React, { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, RefreshControl, Alert } from "react-native";
import { router, useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Card, EmptyState, PrimaryButton } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";
import { RoleGate } from "@/src/components/RoleGate";

export default function QboIndex() {
  const [conns, setConns] = useState<any[]>([]);
  const [configured, setConfigured] = useState(false);
  const [lastRun, setLastRun] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const c: any = await api.get("/qbo/connections");
      setConns(c?.connections || []);
      setConfigured(!!c?.configured);
      const r: any = await api.get("/qbo/sync/runs?limit=1").catch(() => ({}));
      setLastRun((r?.runs || [])[0] || null);
    } finally {
      setLoading(false);
    }
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const active = conns[0];

  const runSync = async () => {
    if (!active) return;
    setSyncing(true);
    try {
      await api.post("/qbo/sync/run-now", { qbo_connection_id: active.qbo_connection_id, force_full: false });
      Alert.alert("Sync started", "Pulling latest from QuickBooks…");
      await load();
    } catch (err: any) {
      Alert.alert("Failed", String(err?.message || err));
    } finally {
      setSyncing(false);
    }
  };

  return (
    <RoleGate level="admin_plus">
      <View style={styles.container}>
        <Header title="QuickBooks Online" />
        <ScrollView
          contentContainerStyle={styles.body}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => {
            setRefreshing(true); await load(); setRefreshing(false);
          }} />}
        >
          {!configured ? (
            <EmptyState
              icon="settings-outline"
              title="QuickBooks not configured"
              subtitle="Set QBO_CLIENT_ID / SECRET / REDIRECT_URI on the server, then open the desktop QuickBooks page to connect."
              testID="qbo-mobile-unconfigured"
            />
          ) : !active ? (
            <EmptyState
              icon="cloud-outline"
              title="Not connected"
              subtitle="Connect from the desktop app first."
              testID="qbo-mobile-not-connected"
            />
          ) : (
            <>
              <Card>
                <Text style={styles.company}>{active.qbo_company_name || "QuickBooks company"}</Text>
                <Text style={styles.meta}>
                  Realm {active.qbo_realm_id} · {active.environment}
                </Text>
                <View style={{ height: spacing.md }} />
                <PrimaryButton
                  title={syncing ? "Syncing…" : "Sync now"}
                  icon="refresh-outline"
                  onPress={runSync}
                  loading={syncing}
                  testID="qbo-mobile-sync-now"
                />
              </Card>
              {lastRun ? (
                <Card>
                  <Text style={styles.sectionLabel}>Last run</Text>
                  <Text style={styles.line}>Status: <Text style={styles.strong}>{lastRun.status}</Text></Text>
                  <Text style={styles.line}>Duration: {lastRun.duration_ms || 0} ms</Text>
                  <Text style={styles.line}>Started: {(lastRun.started_at || "").slice(0, 19)}</Text>
                  <Text style={styles.line}>Trigger: {lastRun.triggered_by}</Text>
                </Card>
              ) : null}
              <PrimaryButton
                variant="outline"
                title="Browse QuickBooks data"
                icon="folder-open-outline"
                onPress={() => router.push("/qbo/data")}
                testID="qbo-mobile-browse-btn"
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
  body: { padding: spacing.lg, gap: spacing.md, paddingBottom: spacing["3xl"] },
  company: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface },
  meta: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 4 },
  sectionLabel: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface, marginBottom: spacing.sm },
  line: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, marginTop: 4 },
  strong: { fontFamily: font.semibold },
});
