// Phase 2 · Feb-2026 — Mobile Route Replay share screen.
//
// Dispatchers pick tech + date, tap "Generate share link", copy to
// clipboard, and revoke if needed. This mobile screen intentionally
// does NOT render the public replay itself — the customer opens the
// link in a browser and lands on `PublicReplayPage` on the web.
import React, { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, Alert } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import * as Clipboard from "expo-clipboard";
import { useFocusEffect, useLocalSearchParams } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Loading } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";

type ShareRow = {
  share_id: string;
  user_id: string;
  replay_date: string;
  expires_at: string;
  view_count: number;
  status: string;
};

function _publicUrl(shareId: string): string {
  const base = (process.env.EXPO_PUBLIC_WEB_BASE_URL || "").replace(/\/$/, "");
  if (base) return `${base}/replay/${shareId}`;
  return `/replay/${shareId}`;
}

export default function ShareReplay() {
  const params = useLocalSearchParams<{ userId?: string; date?: string }>();
  const [techId, setTechId] = useState<string>(params.userId || "");
  const [date, setDate] = useState<string>(params.date ||
    new Date().toISOString().slice(0, 10));

  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [revoking, setRevoking] = useState(false);
  const [active, setActive] = useState<ShareRow | null>(null);

  const refresh = useCallback(async () => {
    if (!techId || !date) { setLoading(false); return; }
    setLoading(true);
    try {
      const res = await api.get(
        `/gps/replay/shares?user_id=${encodeURIComponent(techId)}&date=${encodeURIComponent(date)}`,
      );
      const first = ((res as any)?.items || []).find(
        (r: ShareRow) => r.status === "active");
      setActive(first || null);
    } catch {
      setActive(null);
    } finally {
      setLoading(false);
    }
  }, [techId, date]);

  useFocusEffect(useCallback(() => { refresh(); }, [refresh]));
  useEffect(() => { refresh(); }, [refresh]);

  const create = async () => {
    if (!techId || !date) {
      Alert.alert("Missing tech or date", "Open this screen from Driver Activity.");
      return;
    }
    setCreating(true);
    try {
      const res = await api.post("/gps/replay/share",
                                  { user_id: techId, replay_date: date });
      setActive({
        share_id: (res as any).share_id,
        user_id: techId,
        replay_date: date,
        expires_at: (res as any).expires_at,
        view_count: 0,
        status: "active",
      });
    } catch (e: any) {
      Alert.alert("Failed to create share", e?.message || "Try again");
    } finally {
      setCreating(false);
    }
  };

  const copy = async () => {
    if (!active) return;
    const url = _publicUrl(active.share_id);
    try {
      await Clipboard.setStringAsync(url);
      Alert.alert("Link copied", url);
    } catch {
      Alert.alert("Copy failed", url);
    }
  };

  const revoke = async () => {
    if (!active) return;
    setRevoking(true);
    try {
      await api.post(`/gps/replay/share/${active.share_id}/revoke`);
      setActive(null);
    } catch (e: any) {
      Alert.alert("Failed to revoke", e?.message || "Try again");
    } finally {
      setRevoking(false);
    }
  };

  const url = active ? _publicUrl(active.share_id) : "";

  return (
    <View style={styles.root} testID="mobile-share-replay">
      <Header title="Share replay" back subtitle="Public 24-hour link" />
      <ScrollView contentContainerStyle={{ padding: spacing.lg }}>
        <View style={styles.metaCard} testID="mobile-share-replay-meta">
          <Text style={styles.metaLabel}>Technician</Text>
          <Text style={styles.metaValue}>{techId || "—"}</Text>
          <Text style={[styles.metaLabel, { marginTop: spacing.sm }]}>Date</Text>
          <Text style={styles.metaValue}>{date}</Text>
        </View>

        {loading ? (
          <Loading testID="mobile-share-replay-loading" />
        ) : !active ? (
          <Pressable
            testID="mobile-share-replay-create"
            onPress={create}
            disabled={creating}
            style={[styles.primaryBtn, creating && styles.disabled]}
          >
            <Ionicons name="link-outline" size={16} color={colors.onBrandPrimary} />
            <Text style={styles.primaryBtnText}>
              {creating ? "Creating…" : "Generate share link"}
            </Text>
          </Pressable>
        ) : (
          <>
            <View style={styles.urlBox} testID="mobile-share-replay-url">
              <Text style={styles.urlText} numberOfLines={2} selectable>{url}</Text>
            </View>
            <Text style={styles.helpText}>
              Expires {new Date(active.expires_at).toLocaleString()}
              {" · "}{active.view_count} views
            </Text>

            <Pressable
              testID="mobile-share-replay-copy"
              onPress={copy}
              style={[styles.primaryBtn, { marginTop: spacing.md }]}
            >
              <Ionicons name="copy-outline" size={16} color={colors.onBrandPrimary} />
              <Text style={styles.primaryBtnText}>Copy link</Text>
            </Pressable>

            <Pressable
              testID="mobile-share-replay-revoke"
              onPress={revoke}
              disabled={revoking}
              style={[styles.revokeBtn, revoking && styles.disabled]}
            >
              <Ionicons name="shield-outline" size={16} color="#B91C1C" />
              <Text style={styles.revokeBtnText}>
                {revoking ? "Revoking…" : "Revoke link"}
              </Text>
            </Pressable>
          </>
        )}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  metaCard: {
    padding: spacing.md, borderRadius: radius.lg,
    backgroundColor: colors.surface,
    borderWidth: 1, borderColor: colors.border,
    marginBottom: spacing.lg,
  },
  metaLabel: {
    fontFamily: font.medium, fontSize: fontSize.xs, color: colors.muted,
    textTransform: "uppercase", letterSpacing: 0.5,
  },
  metaValue: {
    fontFamily: font.semibold, fontSize: fontSize.base,
    color: colors.onSurface, marginTop: 2,
  },
  urlBox: {
    padding: spacing.md, borderRadius: radius.md,
    backgroundColor: colors.surfaceMuted, borderWidth: 1,
    borderColor: colors.border,
  },
  urlText: {
    fontFamily: font.regular, fontSize: fontSize.sm,
    color: colors.onSurface,
  },
  helpText: {
    fontFamily: font.regular, fontSize: fontSize.xs,
    color: colors.muted, marginTop: spacing.xs,
  },
  primaryBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: spacing.xs, backgroundColor: colors.brand, paddingVertical: spacing.md,
    borderRadius: radius.md,
  },
  primaryBtnText: {
    fontFamily: font.semibold, fontSize: fontSize.base,
    color: colors.onBrandPrimary,
  },
  revokeBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: spacing.xs, backgroundColor: "transparent",
    borderWidth: 1, borderColor: "#FECACA",
    paddingVertical: spacing.md, borderRadius: radius.md,
    marginTop: spacing.md,
  },
  revokeBtnText: {
    fontFamily: font.semibold, fontSize: fontSize.sm, color: "#B91C1C",
  },
  disabled: { opacity: 0.6 },
});
