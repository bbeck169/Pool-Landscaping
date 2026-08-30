/**
 * Phase S2 · Soshie Hub — 3-tab shell (Brand Brain / Autopilot / Review Queue).
 * Route: /soshie — Admin only.
 * Mirrors frontend/src/pages/soshie/SoshieHub.jsx
 */
import React, { useState } from "react";
import { View, Text, StyleSheet, Pressable, ScrollView } from "react-native";
import { Redirect } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { useAuth } from "@/src/auth";
import { Header } from "@/src/components/widgets";
import { useOnline } from "@/src/offline";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import BrandBrainTab from "./BrandBrainTab";
import AutopilotTab from "./AutopilotTab";
import ReviewQueueTab from "./ReviewQueueTab";

type Tab = "brand-brain" | "autopilot" | "review-queue";

const TABS: { key: Tab; label: string; icon: string }[] = [
  { key: "brand-brain", label: "Brand Brain", icon: "sparkles-outline" },
  { key: "autopilot", label: "Autopilot", icon: "flash-outline" },
  { key: "review-queue", label: "Review", icon: "checkmark-circle-outline" },
];

function OfflineBanner() {
  return (
    <View style={s.offlineBanner} testID="soshie-offline-banner">
      <Ionicons name="cloud-offline" size={16} color="#92400E" />
      <Text style={s.offlineText}>
        {"You're offline — Soshie needs a connection"}
      </Text>
    </View>
  );
}

export default function SoshieHub() {
  const { user } = useAuth();
  const online = useOnline();
  const [tab, setTab] = useState<Tab>("brand-brain");

  const isAdmin = user?.role === "admin" || (user?.role as string) === "super_admin";
  if (!isAdmin) return <Redirect href="/(app)" />;

  return (
    <View style={s.root} testID="soshie-hub">
      <Header
        title="Soshie · Social Publishing"
        back
        subtitle="Brand memory, autopilot schedules & review queue"
      />

      {!online && <OfflineBanner />}

      {/* Segment tabs */}
      <View style={s.segment} testID="soshie-tabs">
        {TABS.map((t) => {
          const active = tab === t.key;
          return (
            <Pressable
              key={t.key}
              onPress={() => setTab(t.key)}
              style={[s.segBtn, active && s.segBtnActive]}
              testID={`soshie-tab-${t.key}`}
              accessibilityRole="tab"
              accessibilityLabel={t.label}
              accessibilityState={{ selected: active }}
            >
              <Ionicons
                name={t.icon as any}
                size={15}
                color={active ? "#fff" : colors.onSurfaceSecondary}
              />
              <Text
                style={[
                  s.segText,
                  { color: active ? "#fff" : colors.onSurfaceSecondary },
                ]}
              >
                {t.label}
              </Text>
            </Pressable>
          );
        })}
      </View>

      {/* Tab content */}
      <ScrollView
        style={s.content}
        contentContainerStyle={s.contentInner}
        showsVerticalScrollIndicator={false}
      >
        {tab === "brand-brain" && <BrandBrainTab disabled={!online} />}
        {tab === "autopilot" && <AutopilotTab disabled={!online} />}
        {tab === "review-queue" && <ReviewQueueTab disabled={!online} />}
      </ScrollView>
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  offlineBanner: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    backgroundColor: "#FEF3C7",
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm + 2,
  },
  offlineText: {
    fontFamily: font.medium,
    fontSize: fontSize.sm,
    color: "#92400E",
    flex: 1,
  },
  segment: {
    flexDirection: "row",
    marginHorizontal: spacing.lg,
    marginTop: spacing.md,
    backgroundColor: colors.surfaceTertiary,
    borderRadius: radius.md,
    padding: 3,
  },
  segBtn: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 4,
    paddingVertical: 9,
    borderRadius: radius.md - 2,
  },
  segBtnActive: {
    backgroundColor: colors.brand,
  },
  segText: {
    fontFamily: font.semibold,
    fontSize: 12,
  },
  content: { flex: 1 },
  contentInner: {
    padding: spacing.lg,
    paddingBottom: spacing["2xl"],
  },
});
