/**
 * FLEET-B · Fleet Pause Toggle
 *
 * "Pause tracking for this shift" toggle.
 * When enabled, the emitter is stopped. When disabled, it restarts.
 */
import React, { useEffect, useState } from "react";
import { View, Text, StyleSheet, Switch } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import {
  isPaused,
  setPaused,
  startEmitter,
  getEmitterStatus,
  onStatusChange,
  type EmitterStatus,
} from "@/src/services/fleet/locationEmitter";
import { font, fontSize, spacing, radius, colors } from "@/src/theme";

export default function FleetPauseToggle() {
  const [paused, setPausedState] = useState(false);
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState<EmitterStatus>(getEmitterStatus());

  useEffect(() => {
    isPaused().then((v) => {
      setPausedState(v);
      setLoading(false);
    });
    const unsub = onStatusChange((s) => setStatus(s));
    return unsub;
  }, []);

  const toggle = async (value: boolean) => {
    setPausedState(value);
    await setPaused(value);
    if (!value) {
      // Resume — restart emitter
      await startEmitter();
    }
  };

  if (loading) return null;

  return (
    <View style={s.container} testID="fleet-pause-toggle-row">
      <View style={s.iconWrap}>
        <Ionicons name="location-outline" size={18} color={colors.brand} />
      </View>
      <View style={s.textWrap}>
        <Text style={s.title}>Fleet Tracking</Text>
        <Text style={s.subtitle}>
          {paused
            ? "Paused for this shift"
            : status === "active"
            ? "Actively sharing location"
            : status === "not_in_fleet"
            ? "Not enrolled — ask admin"
            : "Enabled"}
        </Text>
      </View>
      <Switch
        testID="fleet-pause-toggle"
        value={!paused}
        onValueChange={(v) => toggle(!v)}
        trackColor={{ false: colors.surfaceTertiary, true: "#86EFAC" }}
        thumbColor={!paused ? "#16A34A" : "#A1A1AA"}
      />
    </View>
  );
}

const s = StyleSheet.create({
  container: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.md,
  },
  iconWrap: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: colors.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
  },
  textWrap: {
    flex: 1,
  },
  title: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.onSurface,
  },
  subtitle: {
    fontFamily: font.regular,
    fontSize: 11,
    color: colors.muted,
    marginTop: 1,
  },
});
