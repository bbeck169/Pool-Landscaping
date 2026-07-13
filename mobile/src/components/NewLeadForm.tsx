import React, { useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, TextInput, Platform, Alert, Linking, ActivityIndicator } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import * as Location from "expo-location";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { PrimaryButton } from "@/src/components/ui";

const SOURCES = ["Door-to-door", "Referral", "Website", "Google", "Facebook", "Walk-in", "Phone", "Other"];
const blank = { name: "", phone: "", email: "", source: "Door-to-door", est_value: "", notes: "", address: "" };

export default function NewLeadForm({ onDone }: { onDone?: () => void }) {
  const [form, setForm] = useState({ ...blank });
  const [saving, setSaving] = useState(false);
  const [locating, setLocating] = useState(false);
  const [geo, setGeo] = useState<{ lat: number; lng: number } | null>(null);

  const set = (k: string, v: string) => setForm((f) => ({ ...f, [k]: v }));

  const attachLocation = async () => {
    setLocating(true);
    try {
      const perm = await Location.getForegroundPermissionsAsync();
      let status = perm.status;
      if (status !== "granted") {
        if (!perm.canAskAgain) {
          Alert.alert("Location is off", "Enable location to geo-tag this lead. You can still enter the address manually.", [
            { text: "Not now", style: "cancel" },
            { text: "Open Settings", onPress: () => Linking.openSettings() },
          ]);
          return;
        }
        const req = await Location.requestForegroundPermissionsAsync();
        status = req.status;
        if (status !== "granted") return;
      }
      const pos = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
      const lat = pos.coords.latitude, lng = pos.coords.longitude;
      setGeo({ lat, lng });
      try {
        const g = await Location.reverseGeocodeAsync({ latitude: lat, longitude: lng });
        const a = g?.[0];
        if (a) {
          const line = [[a.streetNumber, a.street].filter(Boolean).join(" "), a.city, a.region, a.postalCode].filter(Boolean).join(", ");
          if (line) setForm((f) => ({ ...f, address: line }));
        }
      } catch {}
    } catch {
      Alert.alert("Location error", "Could not get your current location.");
    } finally {
      setLocating(false);
    }
  };

  const submit = async () => {
    if (!form.name.trim()) return Alert.alert("Name required", "Please enter the lead's name.");
    setSaving(true);
    try {
      await api.post("/leads", {
        name: form.name.trim(),
        phone: form.phone.trim(),
        email: form.email.trim(),
        source: form.source,
        status: "new",
        notes: form.notes.trim(),
        est_value: parseFloat(form.est_value) || 0,
        address: form.address.trim(),
        lat: geo?.lat ?? null,
        lng: geo?.lng ?? null,
      });
      Alert.alert("Lead saved ✅", geo ? "Geo-tagged and added to the pipeline." : "The new lead was added to the pipeline.", [
        { text: "Add another", onPress: () => { setForm({ ...blank }); setGeo(null); } },
        { text: "Done", onPress: () => { setForm({ ...blank }); setGeo(null); onDone?.(); } },
      ]);
    } catch (e: any) {
      Alert.alert("Could not save", e.message);
    } finally {
      setSaving(false);
    }
  };

  const fields: [string, string, string][] = [
    ["name", "Full name *", "default"],
    ["phone", "Phone", "phone-pad"],
    ["email", "Email", "email-address"],
    ["est_value", "Estimated value ($)", "decimal-pad"],
  ];

  return (
    <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }} keyboardShouldPersistTaps="handled">
      {fields.map(([k, lbl, kt]) => (
        <View key={k} style={{ marginBottom: spacing.md }}>
          <Text style={styles.label}>{lbl}</Text>
          <TextInput
            style={styles.input}
            value={(form as any)[k]}
            onChangeText={(v) => set(k, v)}
            keyboardType={kt as any}
            autoCapitalize={k === "email" ? "none" : "sentences"}
            placeholderTextColor={colors.muted}
            testID={`newlead-${k}`}
          />
        </View>
      ))}

      <Text style={styles.label}>Address</Text>
      <TextInput
        style={styles.input}
        value={form.address}
        onChangeText={(v) => set("address", v)}
        placeholder="123 Palm St, Surprise, AZ"
        placeholderTextColor={colors.muted}
        testID="newlead-address"
      />
      <Pressable style={[styles.locBtn, geo && styles.locBtnDone]} onPress={attachLocation} disabled={locating} testID="newlead-attach-location">
        {locating ? (
          <ActivityIndicator color={geo ? "#16A34A" : colors.brand} size="small" />
        ) : (
          <Ionicons name={geo ? "location" : "location-outline"} size={16} color={geo ? "#16A34A" : colors.brand} />
        )}
        <Text style={[styles.locBtnText, geo && { color: "#16A34A" }]}>
          {locating ? "Getting location…" : geo ? "📍 Location attached — tap to refresh" : "Attach my current location"}
        </Text>
      </Pressable>

      <Text style={[styles.label, { marginTop: spacing.md }]}>Source</Text>
      <View style={styles.sourceRow}>
        {SOURCES.map((s) => {
          const active = form.source === s;
          return (
            <Pressable key={s} onPress={() => set("source", s)} style={[styles.sourceChip, active && styles.sourceChipActive]} testID={`newlead-source-${s}`}>
              <Text style={[styles.sourceText, { color: active ? "#fff" : colors.onSurfaceSecondary }]}>{s}</Text>
            </Pressable>
          );
        })}
      </View>

      <Text style={[styles.label, { marginTop: spacing.md }]}>Notes</Text>
      <TextInput
        style={[styles.input, styles.textArea]}
        value={form.notes}
        onChangeText={(v) => set("notes", v)}
        multiline
        placeholder="What does the prospect need?"
        placeholderTextColor={colors.muted}
        testID="newlead-notes"
      />

      <View style={{ height: spacing.lg }} />
      <PrimaryButton title="Save Lead" icon="magnet-outline" loading={saving} onPress={submit} testID="newlead-submit" />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  label: { fontFamily: font.semibold, fontSize: 11, letterSpacing: 0.8, color: colors.onSurfaceSecondary, marginBottom: spacing.xs, textTransform: "uppercase" },
  input: { backgroundColor: colors.surface, borderWidth: 1.5, borderColor: colors.border, borderRadius: radius.md, paddingHorizontal: spacing.md, height: 50, fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}) },
  textArea: { height: 110, paddingTop: spacing.md, textAlignVertical: "top" },
  locBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, marginTop: spacing.sm, height: 46, borderRadius: radius.md, borderWidth: 1.5, borderColor: colors.border, backgroundColor: colors.surface },
  locBtnDone: { borderColor: "#16A34A", backgroundColor: "#F0FDF4" },
  locBtnText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.brand },
  sourceRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  sourceChip: { paddingHorizontal: spacing.md, height: 38, borderRadius: radius.pill, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  sourceChipActive: { backgroundColor: colors.brand, borderColor: colors.brand },
  sourceText: { fontFamily: font.semibold, fontSize: fontSize.sm },
});
