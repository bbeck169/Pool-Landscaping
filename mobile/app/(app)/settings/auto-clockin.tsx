/**
 * Phase 20A.3 · Settings screen — Auto Clock-In toggle.
 * Default ON for technicians (first visit). Safe in Expo Go.
 */
import React, { useEffect, useState } from "react";
import { View, Text, StyleSheet, Switch, Pressable, Alert, ScrollView, ActivityIndicator } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { useAuth } from "@/src/auth";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import {
  isAutoClockinEnabled, setAutoClockinEnabled,
  startBackgroundAutoClockin, stopBackgroundAutoClockin,
} from "@/src/background/autoClockin";

export default function AutoClockinSettingsScreen() {
  const { user } = useAuth();
  const router = useRouter();
  const [enabled, setEnabled] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string>("");

  const role = String((user as any)?.role || "");

  useEffect(() => {
    (async () => {
      const val = await isAutoClockinEnabled(role);
      setEnabled(val);
      setLoaded(true);
    })();
  }, [role]);

  const onToggle = async (val: boolean) => {
    setBusy(true);
    try {
      if (val) {
        const r = await startBackgroundAutoClockin();
        if (!r.started) {
          Alert.alert(
            "Cannot enable",
            r.reason === "not_supported_in_expo_go"
              ? "Background clock-in requires a native build. Foreground auto-clock-in still works."
              : `Permission denied: ${r.reason}`,
          );
          setStatus(r.reason || "");
          setEnabled(false);
          await setAutoClockinEnabled(false);
          return;
        }
      } else {
        await stopBackgroundAutoClockin();
      }
      await setAutoClockinEnabled(val);
      setEnabled(val);
      setStatus(val ? "Running" : "Stopped");
    } finally { setBusy(false); }
  };

  if (role !== "technician") {
    return (
      <View style={styles.root}>
        <Header title="Auto Clock-In" />
        <View style={styles.gateWrap} testID="auto-clockin-role-gate">
          <Ionicons name="lock-closed" size={32} color={colors.muted} />
          <Text style={styles.gateText}>Auto Clock-In is available to technicians.</Text>
          <Pressable style={styles.gateBtn} onPress={() => router.back()} testID="auto-clockin-gate-back">
            <Text style={styles.gateBtnText}>Go back</Text>
          </Pressable>
        </View>
      </View>
    );
  }

  return (
    <View style={styles.root}>
      <Header title="Auto Clock-In" />
      <ScrollView contentContainerStyle={{ padding: spacing.lg }}>
        {/* ON/OFF status banner */}
        <View style={[styles.statusBanner, enabled ? styles.statusOn : styles.statusOff]} testID="auto-clockin-status-banner">
          <Ionicons
            name={enabled ? "checkmark-circle" : "close-circle"}
            size={20}
            color={enabled ? "#16A34A" : "#DC2626"}
          />
          <Text style={[styles.statusText, enabled ? styles.statusTextOn : styles.statusTextOff]}>
            Auto Clock-In is {enabled ? "ON" : "OFF"}
          </Text>
        </View>

        {!loaded ? (
          <View style={styles.loadingWrap}>
            <ActivityIndicator size="small" color={colors.brand} />
          </View>
        ) : (
          <View style={styles.card} testID="auto-clockin-settings">
            <View style={styles.row}>
              <View style={{ flex: 1, paddingRight: spacing.md }}>
                <Text style={styles.title}>Automatically clock in on arrival</Text>
                <Text style={styles.sub}>
                  Uses background GPS to detect when you arrive at a scheduled
                  job&apos;s site. You can cancel within 10 seconds of the toast.
                </Text>
              </View>
              <Switch
                value={enabled}
                onValueChange={onToggle}
                disabled={busy}
                trackColor={{ false: "#CBD5E1", true: colors.brand }}
                thumbColor="#fff"
                testID="auto-clockin-toggle"
              />
            </View>
          </View>
        )}

        <View style={styles.info}>
          <Ionicons name="information-circle-outline" size={16} color={colors.muted} />
          <Text style={styles.infoText}>
            Background updates only run in native builds (EAS). Foreground GPS
            still clocks you in automatically while the app is open.
            {"\n\n"}Enabled by default for all technicians. Your preference is
            saved locally on this device.
            {status ? `\n\nStatus: ${status}` : ""}
          </Text>
        </View>

        <Pressable style={styles.back} onPress={() => router.back()} testID="auto-clockin-back">
          <Ionicons name="chevron-back" size={16} color={colors.muted} />
          <Text style={styles.backText}>Back</Text>
        </Pressable>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  gateWrap: { flex: 1, alignItems: "center", justifyContent: "center", padding: spacing.xl },
  gateText: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted, marginTop: spacing.md, textAlign: "center" },
  gateBtn: { marginTop: spacing.xl, backgroundColor: colors.brand, paddingHorizontal: spacing.xl, paddingVertical: spacing.md, borderRadius: radius.md },
  gateBtnText: { fontFamily: font.bold, fontSize: fontSize.base, color: "#fff" },
  loadingWrap: { padding: spacing.xl, alignItems: "center" },
  statusBanner: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    paddingHorizontal: spacing.lg, paddingVertical: spacing.md,
    borderRadius: radius.lg, marginBottom: spacing.md,
    borderWidth: 1,
  },
  statusOn: { backgroundColor: "#DCFCE7", borderColor: "#86EFAC" },
  statusOff: { backgroundColor: "#FEE2E2", borderColor: "#FECACA" },
  statusText: { fontFamily: font.bold, fontSize: fontSize.base },
  statusTextOn: { color: "#16A34A" },
  statusTextOff: { color: "#DC2626" },
  card: {
    backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.lg,
    borderWidth: 1, borderColor: colors.border,
  },
  row: { flexDirection: "row", alignItems: "center" },
  title: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  sub: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 4 },
  info: {
    flexDirection: "row", gap: spacing.sm, padding: spacing.md, marginTop: spacing.md,
    backgroundColor: colors.surface, borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border,
  },
  infoText: { flex: 1, fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  back: { flexDirection: "row", alignItems: "center", gap: 4, marginTop: spacing.xl },
  backText: { fontFamily: font.semibold, color: colors.muted },
});
