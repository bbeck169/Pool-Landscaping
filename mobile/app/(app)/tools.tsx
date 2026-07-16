/**
 * Phase 42 · Tools Hub — thin wrapper around the shared body.
 *
 * All layout, filter, and personalization logic lives in
 * `ToolsMenuBody`. This file just supplies the screen chrome (Header +
 * background). Phase 43 pointed the global dropdown at the same body
 * so both surfaces stay in lock-step.
 */
import React from "react";
import { View, StyleSheet } from "react-native";
import { Header } from "@/src/components/widgets";
import { useAuth } from "@/src/auth";
import { colors } from "@/src/theme";
import { ToolsMenuBody } from "@/src/components/tools/ToolsMenuBody";
import { sectionsForRole } from "@/src/components/tools/sections";

export default function ToolsHub() {
  const { user } = useAuth();
  const role = (user?.role as string) || "";
  const isAdmin = role === "admin" || role === "super_admin";
  const sections = sectionsForRole(role);
  const totalTiles = sections.reduce((a, s) => a + s.tiles.length, 0);

  return (
    <View style={styles.root}>
      <Header
        title="Tools"
        subtitle={
          isAdmin
            ? "Everything you can do — one screen"
            : `${totalTiles} tools available to you`
        }
      />
      <ToolsMenuBody variant="tab" />
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
});
