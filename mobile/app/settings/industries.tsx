/**
 * Settings → Industries — full-page multi-select for tenant industries.
 *
 * Phase D · Multi-industry mobile parity.
 * Admin/super_admin only (layout gate).
 */
import React from "react";
import { View, StyleSheet, ScrollView } from "react-native";
import { Header } from "@/src/components/widgets";
import IndustriesSettings from "@/src/components/settings/IndustriesSettings";
import { colors, spacing } from "@/src/theme";

export default function IndustriesSettingsScreen() {
  return (
    <View style={s.root} testID="settings-industries-screen">
      <Header title="Industries" subtitle="Select the industries your business serves" back />
      <ScrollView
        contentContainerStyle={s.content}
        showsVerticalScrollIndicator={false}
      >
        <IndustriesSettings />
      </ScrollView>
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  content: {
    padding: spacing.lg,
    paddingBottom: spacing["3xl"],
  },
});
