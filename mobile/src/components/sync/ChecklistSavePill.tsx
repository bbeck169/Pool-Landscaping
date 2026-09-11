/**
 * ChecklistSavePill — single unified status pill for the checklist screen.
 *
 * Shows exactly ONE state at any time:
 *   - "Saving..."               (blue, spinner)   — write in flight
 *   - "Save error — retrying"   (amber)           — retry in progress with count
 *   - "Save error — tap to retry" (red)           — retries exhausted
 *   - "Online · Synced"          (green)           — no pending writes
 *   - "Offline · Queued (N)"     (orange)          — offline + N queued
 */
import React from "react";
import { Pressable, Text, StyleSheet, ActivityIndicator } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { font, radius } from "@/src/theme";

export type SavePillState =
  | { kind: "saving" }
  | { kind: "retrying"; attempt: number; maxRetries: number; nextDelayMs?: number; totalElapsedMs?: number }
  | { kind: "exhausted"; onRetry: () => void; totalElapsedMs?: number }
  | { kind: "synced" }
  | { kind: "offline"; queuedCount: number };

interface Props {
  state: SavePillState;
  testID?: string;
}

export default function ChecklistSavePill({ state, testID }: Props) {
  const { bg, fg, label, icon, isSpinner, pressable, onPress, stateKey } = derive(state);

  const Tag: any = pressable ? Pressable : Pressable;

  return (
    <Tag
      testID={testID || "checklist-save-pill"}
      style={[s.pill, { backgroundColor: bg }]}
      onPress={onPress}
      disabled={!pressable}
      accessibilityRole={pressable ? "button" : undefined}
    >
      {isSpinner ? (
        <ActivityIndicator size={10} color={fg} testID="save-pill-spinner" />
      ) : (
        <Ionicons name={icon as any} size={11} color={fg} />
      )}
      <Text
        style={[s.text, { color: fg }]}
        numberOfLines={1}
        testID={`checklist-save-pill-state-${stateKey}`}
      >
        {label}
      </Text>
    </Tag>
  );
}

function derive(state: SavePillState) {
  switch (state.kind) {
    case "saving":
      return {
        bg: "#DBEAFE", fg: "#1E40AF",
        label: "Saving…",
        icon: "sync", isSpinner: true,
        pressable: false, onPress: undefined,
        stateKey: "saving",
      };
    case "retrying": {
      // Show "retrying in Xs" when we have delay info, else "retrying N/N".
      const delayLabel = state.nextDelayMs != null && state.nextDelayMs > 0
        ? `Save error — retrying in ${Math.ceil(state.nextDelayMs / 1000)}s`
        : `Save error — retrying ${state.attempt}/${state.maxRetries}`;
      return {
        bg: "#FEF3C7", fg: "#92400E",
        label: delayLabel,
        icon: "refresh", isSpinner: true,
        pressable: false, onPress: undefined,
        stateKey: "retrying",
      };
    }
    case "exhausted": {
      const elapsedLabel = state.totalElapsedMs != null
        ? `Save failed after ${Math.ceil(state.totalElapsedMs / 1000)}s — tap to retry`
        : "Save error — tap to retry";
      return {
        bg: "#FEE2E2", fg: "#991B1B",
        label: elapsedLabel,
        icon: "alert-circle", isSpinner: false,
        pressable: true, onPress: state.onRetry,
        stateKey: "exhausted",
      };
    }
    case "synced":
      return {
        bg: "#DCFCE7", fg: "#166534",
        label: "Online · Synced",
        icon: "cloud-done-outline", isSpinner: false,
        pressable: false, onPress: undefined,
        stateKey: "synced",
      };
    case "offline":
      return {
        bg: "#FED7AA", fg: "#9A3412",
        label: state.queuedCount > 0
          ? `Offline · Queued (${state.queuedCount})`
          : "Offline",
        icon: "cloud-offline-outline", isSpinner: false,
        pressable: false, onPress: undefined,
        stateKey: "offline",
      };
  }
}

const s = StyleSheet.create({
  pill: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: radius.pill,
    maxWidth: 260,
  },
  text: {
    fontFamily: font.semibold,
    fontSize: 10,
    flexShrink: 1,
  },
});
