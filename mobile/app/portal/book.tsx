/**
 * Phase 20B mobile A.2 · Customer appointment booking.
 */
import React, { useEffect, useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, Pressable, TextInput, Alert,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";

const SERVICE_TYPES = [
  "Pool Cleaning", "Weekly Pool Service", "Chemical Balance Only",
  "Landscape Maintenance", "Monthly Landscaping", "One-time Cleanup",
];

export default function PortalBook() {
  const router = useRouter();
  const [avail, setAvail] = useState<any>({ windows: [] });
  const [service, setService] = useState(SERVICE_TYPES[0]);
  const [pick, setPick] = useState<{ date: string; window: string } | null>(null);
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [confirmation, setConfirmation] = useState<any>(null);

  useEffect(() => {
    api.get("/portal/availability?date_range=14")
       .then(setAvail).catch(() => {});
  }, []);

  const submit = async () => {
    if (!pick) { Alert.alert("Pick a date & window first"); return; }
    setSubmitting(true);
    try {
      const r = await api.post("/portal/appointments", {
        service_type: service,
        preferred_date: pick.date,
        preferred_window: pick.window,
        notes,
      });
      setConfirmation(r);
    } catch (e: any) {
      Alert.alert("Booking failed", e?.message || "");
    } finally { setSubmitting(false); }
  };

  if (confirmation) {
    return (
      <View style={styles.root}>
        <Header title="Booked" />
        <View style={styles.confirmWrap}>
          <View style={styles.confirmCircle}>
            <Ionicons name="checkmark" size={40} color="#065F46" />
          </View>
          <Text style={styles.confirmTitle}>Request submitted</Text>
          <Text style={styles.confirmSub}>
            {confirmation.service_type} · {confirmation.preferred_date} ·{" "}
            {confirmation.preferred_window}
          </Text>
          <Text style={styles.confirmNote}>
            Our team will confirm within 24 hours.
          </Text>
          <Pressable style={styles.submitBtn}
                     onPress={() => router.push("/portal/appointments" as any)}
                     testID="portal-book-view-appts">
            <Text style={styles.submitText}>See my appointments</Text>
          </Pressable>
        </View>
      </View>
    );
  }

  return (
    <View style={styles.root}>
      <Header title="Book a Service"
              subtitle="Pick a day + window — we'll confirm within 24h." />
      <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: 120 }}>
        <Text style={styles.label}>Service type</Text>
        <View style={styles.serviceRow}>
          {SERVICE_TYPES.map((s) => (
            <Pressable key={s} onPress={() => setService(s)}
                       style={[styles.chip,
                               service === s ? styles.chipActive : null]}
                       testID={`portal-book-service-${s}`}>
              <Text style={[styles.chipText,
                            service === s ? { color: "#fff" } : null]}>
                {s}
              </Text>
            </Pressable>
          ))}
        </View>

        <Text style={styles.label}>Preferred window</Text>
        <View style={styles.windows}>
          {avail.windows.slice(0, 12).map((w: any) => (
            <Pressable key={`${w.date}-${w.window}`}
                       onPress={() => !w.full &&
                         setPick({ date: w.date, window: w.window })}
                       disabled={w.full}
                       style={[styles.window,
                               pick?.date === w.date && pick?.window === w.window
                                 ? styles.windowActive
                                 : null,
                               w.full ? styles.windowFull : null]}
                       testID={`portal-book-window-${w.date}-${w.window}`}>
              <Text style={[styles.windowTitle,
                            pick?.date === w.date && pick?.window === w.window
                              ? { color: "#fff" } : null]}>
                {w.label}
              </Text>
              <Text style={[styles.windowMeta,
                            pick?.date === w.date && pick?.window === w.window
                              ? { color: "rgba(255,255,255,.9)" } : null]}>
                {w.full ? "Full" : `${w.slots_remaining} left`}
              </Text>
            </Pressable>
          ))}
          {avail.windows.length === 0 && (
            <Text style={styles.emptyText}>No availability in the next 14 days.</Text>
          )}
        </View>

        <Text style={styles.label}>Notes (optional)</Text>
        <TextInput value={notes} onChangeText={setNotes}
                   multiline
                   placeholder="Gate code, pet on premises, particular problem area…"
                   placeholderTextColor={colors.muted}
                   style={styles.textArea}
                   testID="portal-book-notes" />

        <Pressable style={[styles.submitBtn,
                           submitting ? { opacity: 0.6 } : null]}
                   onPress={submit} disabled={submitting}
                   testID="portal-book-submit">
          <Text style={styles.submitText}>
            {submitting ? "Submitting…" : "Request appointment"}
          </Text>
        </Pressable>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  label: { fontFamily: font.bold, fontSize: fontSize.sm,
           color: colors.muted, textTransform: "uppercase",
           letterSpacing: 0.6, marginTop: spacing.lg, marginBottom: spacing.sm },
  serviceRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  chip: { paddingHorizontal: 14, paddingVertical: 8, borderRadius: 22,
          borderWidth: 1, borderColor: colors.border,
          backgroundColor: colors.surface },
  chipActive: { backgroundColor: colors.brand, borderColor: colors.brand },
  chipText: { fontFamily: font.semibold, fontSize: fontSize.sm,
              color: colors.onSurface },
  windows: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  window: { width: "48%", padding: spacing.md, borderRadius: radius.md,
            backgroundColor: colors.surface, borderWidth: 1,
            borderColor: colors.border },
  windowActive: { backgroundColor: colors.brand, borderColor: colors.brand },
  windowFull: { opacity: 0.4 },
  windowTitle: { fontFamily: font.semibold, fontSize: fontSize.sm,
                 color: colors.onSurface },
  windowMeta: { fontFamily: font.regular, fontSize: 11,
                color: colors.muted, marginTop: 2 },
  textArea: { backgroundColor: colors.surface, borderRadius: radius.md,
              padding: spacing.md, minHeight: 90,
              fontFamily: font.regular, fontSize: fontSize.base,
              color: colors.onSurface,
              borderWidth: 1, borderColor: colors.border,
              textAlignVertical: "top" },
  submitBtn: { backgroundColor: colors.brand, borderRadius: radius.lg,
               padding: spacing.lg, alignItems: "center",
               marginTop: spacing.xl },
  submitText: { color: "#fff", fontFamily: font.bold, fontSize: fontSize.base },
  emptyText: { color: colors.muted, textAlign: "center",
               width: "100%", padding: spacing.lg,
               fontFamily: font.regular, fontSize: fontSize.sm },
  confirmWrap: { padding: spacing.xl, alignItems: "center" },
  confirmCircle: { width: 80, height: 80, borderRadius: 40,
                   backgroundColor: "#ECFDF5", alignItems: "center",
                   justifyContent: "center", marginTop: spacing.xl,
                   marginBottom: spacing.lg },
  confirmTitle: { fontFamily: font.bold, fontSize: fontSize.xl,
                  color: colors.onSurface },
  confirmSub: { fontFamily: font.medium, fontSize: fontSize.base,
                color: colors.onSurface, marginTop: spacing.sm,
                textAlign: "center" },
  confirmNote: { fontFamily: font.regular, fontSize: fontSize.sm,
                 color: colors.muted, marginTop: spacing.sm,
                 textAlign: "center", marginBottom: spacing.xl },
});
