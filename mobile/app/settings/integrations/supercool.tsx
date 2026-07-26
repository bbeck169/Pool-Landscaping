/**
 * Supercool AI Integration — status & connection management.
 * Route: /settings/integrations/supercool  (super_admin only)
 *
 * Port of frontend/src/pages/settings/integrations/SupercoolIntegrationPage.jsx
 *
 * - Connect / Disconnect / Refresh catalog buttons
 * - Status card with tool count
 * - Connect opens OAuth flow in system browser
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, Alert,
  RefreshControl,
} from "react-native";
import * as WebBrowser from "expo-web-browser";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import { Card, PrimaryButton, EmptyState, Loading } from "@/src/components/ui";

export default function SupercoolIntegration() {
  const { user } = useAuth();
  const [status, setStatus] = useState<any>(null);
  const [catalog, setCatalog] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [connecting, setConnecting] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [showCatalog, setShowCatalog] = useState(false);

  const loadStatus = useCallback(async () => {
    try {
      const s = await api.get("/integrations/supercool/status");
      setStatus(s);
    } catch (e: any) {
      Alert.alert("Error", e.message || "Could not load status");
    }
  }, []);

  const loadCatalog = useCallback(async () => {
    try {
      const c = await api.get("/integrations/supercool/catalog");
      setCatalog(c);
    } catch {
      setCatalog({ tools: [], fetched_at: null });
    }
  }, []);

  useEffect(() => {
    Promise.all([loadStatus(), loadCatalog()]).finally(() => setLoading(false));
  }, [loadStatus, loadCatalog]);

  const doConnect = async () => {
    setConnecting(true);
    try {
      const r = await api.post("/integrations/supercool/connect", {});
      if (r?.authorize_url) {
        await WebBrowser.openBrowserAsync(r.authorize_url);
        setTimeout(() => { loadStatus(); loadCatalog(); }, 1500);
      } else {
        Alert.alert("Error", "No authorization URL returned");
      }
    } catch (e: any) {
      Alert.alert("Connect failed", e.message || "Unknown error");
    } finally {
      setConnecting(false);
    }
  };

  const doDisconnect = async () => {
    Alert.alert("Disconnect Supercool?", "This will revoke the OAuth tokens.", [
      { text: "Cancel", style: "cancel" },
      {
        text: "Disconnect", style: "destructive", onPress: async () => {
          setDisconnecting(true);
          try {
            await api.post("/integrations/supercool/disconnect", {});
            await loadStatus();
            Alert.alert("Disconnected");
          } catch (e: any) {
            Alert.alert("Error", e.message);
          } finally {
            setDisconnecting(false);
          }
        },
      },
    ]);
  };

  const doRefreshCatalog = async () => {
    setRefreshing(true);
    try {
      await api.post("/integrations/supercool/refresh-catalog", {});
      await loadCatalog();
      Alert.alert("Catalog refreshed");
    } catch (e: any) {
      Alert.alert("Refresh failed", e.message);
    } finally {
      setRefreshing(false);
    }
  };

  if (user?.role !== "admin" && user?.role !== "super_admin") {
    return (
      <View style={s.root}>
        <Header title="Supercool Integration" back />
        <EmptyState icon="lock-closed-outline" title="Super Admin only" testID="supercool-locked" />
      </View>
    );
  }

  if (loading) {
    return (
      <View style={s.root}>
        <Header title="Supercool Integration" back />
        <Loading testID="supercool-loading" />
      </View>
    );
  }

  const connected = !!status?.connected;
  const toolCount = catalog?.tools?.length ?? 0;

  return (
    <View style={s.root}>
      <Header title="Supercool AI" back subtitle="Image & video integration" />
      <ScrollView
        contentContainerStyle={{ padding: spacing.lg, paddingBottom: 80 }}
        refreshControl={
          <RefreshControl refreshing={false} onRefresh={() => { loadStatus(); loadCatalog(); }} />
        }
      >
        {/* Status Card */}
        <Card style={s.statusCard} testID="supercool-status-card">
          <View style={s.statusRow}>
            <View style={[s.statusDot, { backgroundColor: connected ? "#22C55E" : "#EAB308" }]} />
            <Text style={s.statusText}>{connected ? "Connected" : "Not connected"}</Text>
          </View>
          {connected && (
            <Text style={s.toolCount} testID="supercool-tool-count">
              {toolCount} tool{toolCount !== 1 ? "s" : ""} available
            </Text>
          )}
          {status?.connected_at && (
            <Text style={s.hint}>
              Connected since {new Date(status.connected_at).toLocaleDateString()}
            </Text>
          )}
        </Card>

        {/* Actions */}
        <View style={{ gap: spacing.sm, marginTop: spacing.lg }}>
          {!connected ? (
            <PrimaryButton
              title="Connect Supercool"
              icon="link-outline"
              loading={connecting}
              onPress={doConnect}
              testID="supercool-connect-btn"
            />
          ) : (
            <>
              <PrimaryButton
                title="Refresh Tool Catalog"
                icon="refresh-outline"
                variant="outline"
                loading={refreshing}
                onPress={doRefreshCatalog}
                testID="supercool-refresh-btn"
              />
              <PrimaryButton
                title="Disconnect"
                icon="unlink-outline"
                variant="outline"
                loading={disconnecting}
                onPress={doDisconnect}
                testID="supercool-disconnect-btn"
              />
            </>
          )}
        </View>

        {/* Catalog */}
        {connected && toolCount > 0 && (
          <View style={{ marginTop: spacing.xl }}>
            <Pressable
              style={s.catalogHeader}
              onPress={() => setShowCatalog((v) => !v)}
              testID="supercool-catalog-toggle"
            >
              <Text style={s.sectionTitle}>Tool Catalog ({toolCount})</Text>
              <Ionicons
                name={showCatalog ? "chevron-up" : "chevron-down"}
                size={18}
                color={colors.muted}
              />
            </Pressable>
            {showCatalog &&
              (catalog?.tools || []).map((t: any, i: number) => (
                <View key={t.name || i} style={s.toolRow}>
                  <Ionicons name="construct-outline" size={16} color={colors.brand} />
                  <View style={{ flex: 1 }}>
                    <Text style={s.toolName}>{t.name}</Text>
                    {t.description ? (
                      <Text style={s.toolDesc} numberOfLines={2}>{t.description}</Text>
                    ) : null}
                  </View>
                </View>
              ))}
          </View>
        )}
      </ScrollView>
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  statusCard: { alignItems: "center", paddingVertical: spacing.xl },
  statusRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  statusDot: { width: 10, height: 10, borderRadius: 5 },
  statusText: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface },
  toolCount: { fontFamily: font.medium, fontSize: fontSize.base, color: colors.muted, marginTop: 4 },
  hint: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 6 },
  catalogHeader: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingVertical: spacing.sm,
  },
  sectionTitle: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  toolRow: {
    flexDirection: "row", alignItems: "flex-start", gap: spacing.sm,
    backgroundColor: colors.surface, borderRadius: radius.md,
    padding: spacing.md, marginBottom: spacing.xs,
    borderWidth: 1, borderColor: colors.border,
  },
  toolName: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  toolDesc: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
});
