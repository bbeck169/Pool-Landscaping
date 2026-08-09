/**
 * Phase Lottie-web · Feb-2026 — Web fallback for the walkie live panel.
 *
 * The native ``LivePanel.tsx`` imports ``react-native-webrtc``, a
 * dev-client-only module whose CommonJS bundle unconditionally pulls
 * in ``event-target-shim/index`` — a specifier absent from the
 * package's exports map, which halts the Expo web Metro bundle.
 * Since Phase 52.1c documented "no live streaming on Expo web
 * preview" (see mobile/EXPO_GO_RUNBOOK.md), this web variant renders
 * a friendly disabled banner. Native (iOS/Android) picks the
 * ``.tsx`` sibling and is untouched.
 */
import React from "react";
import { StyleSheet, Text, TouchableOpacity, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { colors, spacing, fontSize, radius } from "@/src/theme";

export function liveModeKey(channelId: string): string {
  return `walkie_live_mode_${channelId}`;
}
export function pttModeKey(channelId: string): string {
  return `walkie_ptt_mode_${channelId}`;
}
export function buildSignalingUrl(channelId: string, token: string): string {
  return `ws:/api/ws/walkie/${channelId}?token=${encodeURIComponent(token || "")}`;
}

export default function LivePanel({
  channel: _channel,
  user: _user,
  onExit,
}: {
  channel: { id: string };
  user: { id: string };
  onExit?: () => void;
}) {
  return (
    <View style={styles.panel} testID="walkie-live-panel">
      <View style={styles.row}>
        <Ionicons name="radio-outline" size={16} color={colors.onSurfaceSecondary} />
        <Text style={styles.title} testID="walkie-live-status">
          Live sessions require the dev-client build
        </Text>
        <TouchableOpacity onPress={onExit} testID="walkie-live-exit" style={styles.exit}>
          <Ionicons name="close" size={16} color={colors.onSurfaceSecondary} />
        </TouchableOpacity>
      </View>
      <Text style={styles.body}>
        WebRTC live channels aren't available in the Expo web preview.
        Open the native dev-client to join a live session — async
        walkie clips still work here.
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  panel: {
    padding: spacing.md,
    gap: spacing.xs,
    borderTopWidth: 1,
    borderTopColor: colors.borderMuted,
    backgroundColor: colors.surfaceElevated,
    borderRadius: radius.md,
  },
  row: { flexDirection: "row", alignItems: "center", gap: 6 },
  title: {
    fontSize: fontSize.sm,
    fontWeight: "600",
    color: colors.onSurface,
    flex: 1,
  },
  exit: { padding: 4 },
  body: { fontSize: fontSize.xs || 11, color: colors.onSurfaceSecondary },
});
