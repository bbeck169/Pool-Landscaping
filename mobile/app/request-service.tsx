import React, { useState } from "react";
import { View, Text, StyleSheet, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useRouter } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import { PrimaryButton, Sheet } from "@/src/components/ui";
import { Field } from "@/app/customer/new";
import { Selector } from "@/app/job/new";

const SERVICE_TYPES = ["Pool Cleaning", "Repair", "Landscaping", "Inspection", "Installation"];

export default function RequestService() {
  const router = useRouter();
  const [serviceType, setServiceType] = useState("Pool Cleaning");
  const [date, setDate] = useState("");
  const [notes, setNotes] = useState("");
  const [sheet, setSheet] = useState(false);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState("");

  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      await api.post("/service-requests", {
        service_type: serviceType,
        title: `${serviceType} Request`,
        scheduled_date: date || null,
        notes,
      });
      setDone(true);
    } catch (e: any) {
      setError(e.message || "Failed to submit request");
    } finally {
      setBusy(false);
    }
  };

  if (done) {
    return (
      <View style={styles.root}>
        <Header title="Request Sent" back />
        <View style={styles.doneWrap}>
          <View style={styles.doneIcon}>
            <Ionicons name="checkmark-circle" size={56} color={colors.success} />
          </View>
          <Text style={styles.doneTitle}>Request submitted!</Text>
          <Text style={styles.doneSub}>Our team will review your {serviceType.toLowerCase()} request and schedule a technician shortly.</Text>
          <View style={{ height: spacing.xl }} />
          <PrimaryButton title="Back to My Services" onPress={() => router.replace("/(app)/jobs")} testID="request-done-button" />
        </View>
      </View>
    );
  }

  return (
    <View style={styles.root}>
      <Header title="Request a Service" back />
      <KeyboardAwareScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }} bottomOffset={24} keyboardShouldPersistTaps="handled">
        <Text style={styles.intro}>Tell us what you need and we will schedule it for you.</Text>
        <Selector label="Service Type" value={serviceType} onPress={() => setSheet(true)} testID="request-select-service" />
        <Field label="Preferred Date (optional)" value={date} onChangeText={setDate} placeholder="YYYY-MM-DD" testID="request-date-input" />
        <Field label="Details" value={notes} onChangeText={setNotes} placeholder="Describe the issue or service needed…" multiline testID="request-notes-input" />
        {error ? <Text style={styles.error} testID="request-error">{error}</Text> : null}
        <View style={{ height: spacing.lg }} />
        <PrimaryButton title="Submit Request" icon="send-outline" onPress={submit} loading={busy} testID="submit-request-button" />
      </KeyboardAwareScrollView>

      <Sheet visible={sheet} onClose={() => setSheet(false)} title="Service Type" testID="request-service-sheet">
        {SERVICE_TYPES.map((s) => (
          <Pressable key={s} style={styles.opt} onPress={() => { setServiceType(s); setSheet(false); }} testID={`request-pick-${s}`}>
            <Text style={styles.optText}>{s}</Text>
            {serviceType === s ? <Ionicons name="checkmark" size={20} color={colors.brand} /> : null}
          </Pressable>
        ))}
      </Sheet>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  intro: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted, marginBottom: spacing.lg },
  error: { color: colors.error, fontFamily: font.medium, fontSize: fontSize.base, marginTop: spacing.sm },
  opt: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingVertical: spacing.md, borderBottomWidth: 1, borderBottomColor: colors.divider },
  optText: { fontFamily: font.medium, fontSize: fontSize.lg, color: colors.onSurface },
  doneWrap: { flex: 1, alignItems: "center", justifyContent: "center", padding: spacing.xl },
  doneIcon: { marginBottom: spacing.lg },
  doneTitle: { fontFamily: font.bold, fontSize: fontSize["2xl"], color: colors.onSurface, textAlign: "center" },
  doneSub: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted, textAlign: "center", marginTop: spacing.sm, lineHeight: 20 },
});
