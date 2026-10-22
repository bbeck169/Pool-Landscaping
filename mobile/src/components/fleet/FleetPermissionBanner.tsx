/**
 * TD-fleet-tracking-always-on (Option A) · non-blocking OS-permission reminder.
 *
 * Shows only while the emitter status is `no_permission` (OS denied location;
 * the OS wins, we never force it). Dismissible for the session; re-appears if
 * the status leaves and later returns to `no_permission`. Re-grant is picked up
 * by `useFleetEmitter`'s foreground check, so "Open Settings" → allow → return
 * resumes tracking without a relaunch.
 */
import React, { useEffect, useState } from "react";
import { View, Text, Pressable, StyleSheet, Linking } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { getEmitterStatus, onStatusChange } from "@/src/services/fleet/locationEmitter";
import { font } from "@/src/theme";

export default function FleetPermissionBanner() {
  const [status, setStatus] = useState(getEmitterStatus());
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => onStatusChange((s) => {
    setStatus(s);
    if (s !== "no_permission") setDismissed(false);
  }), []);

  if (status !== "no_permission" || dismissed) return null;

  return (
    <View style={s.wrap} testID="fleet-permission-banner" accessibilityRole="alert">
      <Ionicons name="location-outline" size={16} color={FG} />
      <Text style={s.text} testID="fleet-permission-banner-text">{"Location is off, so fleet tracking can't run."}</Text>
      <Pressable onPress={() => { Linking.openSettings().catch(() => {}); }} hitSlop={8} style={s.btn} testID="fleet-permission-banner-settings">
        <Text style={s.btnText}>Open Settings</Text>
      </Pressable>
      <Pressable onPress={() => setDismissed(true)} hitSlop={12} style={s.close} accessibilityLabel="Dismiss location reminder" testID="fleet-permission-banner-dismiss">
        <Ionicons name="close" size={16} color={FG} />
      </Pressable>
    </View>
  );
}

const FG = "#9A3412";
const s = StyleSheet.create({
  wrap: { flexDirection: "row", alignItems: "center", gap: 8, marginHorizontal: 12, marginTop: 6, paddingHorizontal: 12, paddingVertical: 8, borderRadius: 10, backgroundColor: "#FFF7ED", borderWidth: 1, borderColor: "#FED7AA" },
  text: { flex: 1, fontFamily: font.medium, fontSize: 12, color: FG },
  btn: { paddingHorizontal: 10, minHeight: 32, justifyContent: "center", borderRadius: 8, backgroundColor: "#FFEDD5" },
  btnText: { fontFamily: font.semibold, fontSize: 12, color: FG },
  close: { minWidth: 32, minHeight: 32, alignItems: "center", justifyContent: "center" },
});
