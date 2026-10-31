import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, Pressable, ActivityIndicator, Alert, Linking } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import * as Location from "expo-location";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { askAlwaysPermission } from "@/src/lib/askAlwaysPermission";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";

const fmtTime = (iso?: string | null) => {
  if (!iso) return "";
  try { return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }); } catch { return ""; }
};

export default function ClockInCard({ onChange }: { onChange?: () => void } = {}) {
  const { user } = useAuth();
  const [status, setStatus] = useState<any>({ clocked_in: false, clocked_out: false, timesheet: null });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try { setStatus(await api.get("/attendance/today")); }
    catch { /* keep last */ }
    finally { setLoading(false); }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  // Location is REQUIRED to clock in/out. Returns coords or null (and prompts the user).
  const getLocationOrPrompt = async (): Promise<{ lat: number; lng: number } | null> => {
    const perm = await Location.getForegroundPermissionsAsync();
    let stat = perm.status;
    if (stat !== "granted") {
      if (!perm.canAskAgain) {
        Alert.alert("Location required", "Clocking in/out needs your location so we can verify where you started and finished. Please enable location for this app.", [
          { text: "Cancel", style: "cancel" },
          { text: "Open Settings", onPress: () => Linking.openSettings() },
        ]);
        return null;
      }
      const req = await Location.requestForegroundPermissionsAsync();
      stat = req.status;
      if (stat !== "granted") {
        Alert.alert("Location required", "You must allow location to clock in or out.");
        return null;
      }
    }
    try {
      const pos = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
      return { lat: pos.coords.latitude, lng: pos.coords.longitude };
    } catch {
      Alert.alert("Location unavailable", "Couldn't get your location. Move to an open area and try again.");
      return null;
    }
  };

  const punch = async (kind: "clock-in" | "clock-out") => {
    setBusy(true);
    try {
      const coords = await getLocationOrPrompt();
      if (!coords) return; // blocked without GPS
      await api.post(`/attendance/${kind}`, coords);
      if (kind === "clock-in") askAlwaysPermission(user).catch(() => {}); // β-core 3
      await load();
      onChange?.();
    } catch (e: any) {
      Alert.alert("Error", e.message || "Could not update your timesheet.");
    } finally {
      setBusy(false);
    }
  };

  if (loading) return null;

  const ts = status.timesheet;
  const done = status.clocked_out;
  const active = status.clocked_in && !status.clocked_out;

  return (
    <View style={[styles.card, active && styles.cardActive, done && styles.cardDone]} testID="clock-card">
      <View style={styles.row}>
        <View style={[styles.iconWrap, { backgroundColor: done ? "#16A34A" : active ? "#0EA5E9" : colors.brand }]}>
          <Ionicons name={done ? "checkmark-done" : active ? "time" : "log-in-outline"} size={20} color="#fff" />
        </View>
        <View style={{ flex: 1 }}>
          {done ? (
            <>
              <Text style={styles.title}>Clocked out · {ts?.hours ?? 0} h today</Text>
              <Text style={styles.meta}>In {fmtTime(ts?.clock_in_at)} · Out {fmtTime(ts?.clock_out_at)}</Text>
            </>
          ) : active ? (
            <>
              <Text style={styles.title}>Clocked in at {fmtTime(ts?.clock_in_at)}</Text>
              <Text style={styles.meta}>Location stamped · tap to clock out when done</Text>
            </>
          ) : (
            <>
              <Text style={styles.title}>Not clocked in</Text>
              <Text style={styles.meta}>Clock in to start your day (location required)</Text>
            </>
          )}
        </View>
      </View>
      {!done ? (
        <Pressable
          style={[styles.btn, active ? styles.btnOut : styles.btnIn, busy && { opacity: 0.7 }]}
          onPress={() => punch(active ? "clock-out" : "clock-in")}
          disabled={busy}
          testID={active ? "clock-out-btn" : "clock-in-btn"}
        >
          {busy ? <ActivityIndicator color="#fff" size="small" /> : <Ionicons name={active ? "log-out-outline" : "log-in-outline"} size={18} color="#fff" />}
          <Text style={styles.btnText}>{busy ? "Saving…" : active ? "Clock Out" : "Clock In"}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: { backgroundColor: colors.surface, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.border, padding: spacing.md, marginHorizontal: spacing.lg, marginTop: spacing.md, gap: spacing.md },
  cardActive: { borderColor: "#0EA5E9" },
  cardDone: { borderColor: "#16A34A" },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  iconWrap: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center" },
  title: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  meta: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 1 },
  btn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, height: 46, borderRadius: radius.md },
  btnIn: { backgroundColor: colors.brand },
  btnOut: { backgroundColor: "#0EA5E9" },
  btnText: { fontFamily: font.semibold, fontSize: fontSize.base, color: "#fff" },
});
