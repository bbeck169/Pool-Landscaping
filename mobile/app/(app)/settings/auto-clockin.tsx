/**
 * Phase 20A.3 · Settings screen — Auto Clock-In toggle.
 * Default OFF. Tech-only. Safe in Expo Go.
 */
import React, { useEffect, useState } from "react";
import { View, Text, StyleSheet, Switch, Pressable, Alert, ScrollView } from "react-native";
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
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string>("");

  useEffect(() => {
    (async () => setEnabled(await isAutoClockinEnabled()))();
  }, []);

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

  if (user?.role !== "technician") {
    return (
      <View style={styles.root}>
        <Header title="Auto Clock-In" />
        <Text style={styles.msg}>Auto Clock-In is available to technicians.</Text>
      </View>
    );
  }

  return (
    <View style={styles.root}>
      <Header title="Auto Clock-In" />
      <ScrollView contentContainerStyle={{ padding: spacing.lg }}>
        <View style={styles.card} testID="auto-clockin-settings">
          <View style={styles.row}>
            <View style={{ flex: 1, paddingRight: spacing.md }}>
              <Text style={styles.title}>Automatically clock in on arrival</Text>
              <Text style={styles.sub}>
                Uses background GPS to detect when you arrive at a scheduled
                job's site. You can cancel within 10 seconds of the toast.
              </Text>
            </View>
            <Switch value={enabled} onValueChange={onToggle} disabled={busy}
                    testID="auto-clockin-toggle"/>
          </View>
        </View>

        <View style={styles.info}>
          <Ionicons name="information-circle-outline" size={16} color={colors.muted}/>
          <Text style={styles.infoText}>
            Background updates only run in native builds (EAS). Foreground GPS
            still clocks you in automatically while the app is open.
            {status ? `\n\nStatus: ${status}` : ""}
          </Text>
        </View>

        <Pressable style={styles.back} onPress={() => router.back()}>
          <Ionicons name="chevron-back" size={16} color={colors.muted}/>
          <Text style={styles.backText}>Back</Text>
        </Pressable>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  msg: { padding: spacing.lg, color: colors.muted, fontFamily: font.regular },
  card: { backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.lg,
          borderWidth: 1, borderColor: colors.border },
  row: { flexDirection: "row", alignItems: "center" },
  title: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  sub: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 4 },
  info: { flexDirection: "row", gap: spacing.sm, padding: spacing.md, marginTop: spacing.md,
          backgroundColor: colors.surface, borderRadius: radius.md,
          borderWidth: 1, borderColor: colors.border },
  infoText: { flex: 1, fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  back: { flexDirection: "row", alignItems: "center", gap: 4, marginTop: spacing.xl },
  backText: { fontFamily: font.semibold, color: colors.muted },
});
