/**
 * Communications Hub — Phase 4 · Mobile Parity.
 *
 * Four-card dashboard linking to Templates, Automations,
 * Sends History, and Test Send screens.
 */
import React, { useCallback, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
} from "react-native";
import { useRouter, useFocusEffect } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { Header } from "@/src/components/widgets";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";
import { listSends, listAutomations } from "@/src/api/comms";

type HubCard = {
  key: string;
  icon: string;
  label: string;
  desc: string;
  route: string;
  accent: string;
};

const CARDS: HubCard[] = [
  {
    key: "templates",
    icon: "mail-outline",
    label: "Templates",
    desc: "Browse email & SMS templates",
    route: "/(app)/comms/templates",
    accent: "#0284C7",
  },
  {
    key: "automations",
    icon: "flash-outline",
    label: "Automations",
    desc: "Trigger rules & test-fire",
    route: "/(app)/comms/automations",
    accent: "#7C3AED",
  },
  {
    key: "sends",
    icon: "paper-plane-outline",
    label: "Sends History",
    desc: "Every delivery attempt",
    route: "/(app)/comms/sends",
    accent: "#16A34A",
  },
  {
    key: "test-send",
    icon: "rocket-outline",
    label: "Test Send",
    desc: "Send a template to a customer now",
    route: "/(app)/comms/test-send",
    accent: "#EA580C",
  },
];

export default function CommsHubScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const [glance, setGlance] = useState<{ sends24h: number; activeAutos: number } | null>(null);

  // Load "At a glance" counts on focus. Non-blocking, best-effort.
  useFocusEffect(
    useCallback(() => {
      let cancelled = false;
      (async () => {
        try {
          const sinceMs = Date.now() - 24 * 60 * 60 * 1000;
          const [sends, autos] = await Promise.all([
            listSends({ limit: "500" }).catch(() => null),
            listAutomations().catch(() => null),
          ]);
          if (cancelled) return;
          const sendsRows =
            (sends as any)?.sends || (Array.isArray(sends) ? sends : []) || [];
          const autoRows =
            (autos as any)?.automations ||
            (autos as any)?.automation_rules ||
            (Array.isArray(autos) ? autos : []) ||
            [];
          const sends24h = Array.isArray(sendsRows)
            ? sendsRows.filter((r: any) => {
                const ts = Date.parse(r?.sent_at || r?.queued_at || "");
                return !isNaN(ts) && ts >= sinceMs;
              }).length
            : 0;
          setGlance({
            sends24h,
            activeAutos: Array.isArray(autoRows)
              ? autoRows.filter((r: any) => r?.active).length
              : 0,
          });
        } catch {
          if (!cancelled) setGlance({ sends24h: 0, activeAutos: 0 });
        }
      })();
      return () => { cancelled = true; };
    }, [])
  );

  return (
    <View testID="comms-hub" style={styles.root}>
      <Header title="Communications" subtitle="Monitor & manage comms" back />
      <ScrollView
        contentContainerStyle={[
          styles.grid,
          { paddingBottom: insets.bottom + 24 },
        ]}
        showsVerticalScrollIndicator={false}
      >
        {/* At a glance strip */}
        <View style={styles.glanceRow} testID="comms-hub-glance">
          <View style={styles.glancePill}>
            <Ionicons name="paper-plane-outline" size={13} color="#16A34A" />
            <Text style={styles.glancePillText}>
              {glance ? glance.sends24h : "—"} sent · 24h
            </Text>
          </View>
          <View style={styles.glancePill}>
            <Ionicons name="flash-outline" size={13} color="#7C3AED" />
            <Text style={styles.glancePillText}>
              {glance ? glance.activeAutos : "—"} active automations
            </Text>
          </View>
        </View>

        {CARDS.map((c) => (
          <TouchableOpacity
            key={c.key}
            testID={`comms-hub-${c.key}`}
            style={styles.card}
            activeOpacity={0.7}
            onPress={() => router.push(c.route as any)}
          >
            <View style={[styles.iconCircle, { backgroundColor: c.accent + "18" }]}>
              <Ionicons name={c.icon as any} size={24} color={c.accent} />
            </View>
            <Text style={styles.cardLabel}>{c.label}</Text>
            <Text style={styles.cardDesc}>{c.desc}</Text>
          </TouchableOpacity>
        ))}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  grid: {
    flexDirection: "row",
    flexWrap: "wrap",
    padding: spacing.lg,
    gap: spacing.md,
  },
  glanceRow: {
    width: "100%",
    flexDirection: "row",
    gap: spacing.sm,
    marginBottom: spacing.sm,
  },
  glancePill: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 999,
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.border,
  },
  glancePillText: {
    fontFamily: font.semibold,
    fontSize: 11,
    color: colors.onSurface,
  },
  card: {
    width: "47%",
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md,
    padding: spacing.lg,
    borderWidth: 1,
    borderColor: colors.border,
  },
  iconCircle: {
    width: 44,
    height: 44,
    borderRadius: 22,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: spacing.sm,
  },
  cardLabel: {
    fontFamily: font.semibold,
    fontSize: fontSize.lg,
    color: colors.onSurface,
    marginBottom: 2,
  },
  cardDesc: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
    lineHeight: 16,
  },
});
