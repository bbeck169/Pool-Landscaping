import React, { useState } from "react";
import { View, Text, StyleSheet, TextInput, Platform } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useRouter } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import { PrimaryButton } from "@/src/components/ui";
import { FileUpload } from "@/src/components/files";

const MIN_LEN = 10;
const MAX_LEN = 2000;

export default function RequestService() {
  const router = useRouter();
  const [details, setDetails] = useState("");
  const [date, setDate] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState("");
  const [createdId, setCreatedId] = useState<string | null>(null);
  const [uploadedCount, setUploadedCount] = useState(0);

  const charCount = details.length;
  const isValid = charCount >= MIN_LEN && charCount <= MAX_LEN;

  const submit = async () => {
    if (!isValid) return;
    setBusy(true);
    setError("");
    try {
      const res = await api.post("/customer-portal/service-requests", {
        request_details: details,
        preferred_date: date || undefined,
      });
      // Capture created request id (accept any shape the backend returns)
      const rid = res?.id || res?.request_id || res?.appointment_id || res?.message_id || res?.message?.id || null;
      setCreatedId(rid);
      setDone(true);
    } catch (e: any) {
      setError(e.message || "Failed to submit request");
    } finally {
      setBusy(false);
    }
  };

  if (done) {
    return (
      <View style={s.root}>
        <Header title="Request Sent" back />
        <KeyboardAwareScrollView
          contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}
          keyboardShouldPersistTaps="handled"
        >
          <View style={s.doneWrap}>
            <View style={s.doneIcon}>
              <Ionicons name="checkmark-circle" size={56} color={colors.success} />
            </View>
            <Text style={s.doneTitle}>Request submitted!</Text>
            <Text style={s.doneSub}>
              Our team will review your request and get back to you shortly.
            </Text>
          </View>

          {/* F2c.1 — Photo upload (only when we have a created request id) */}
          {createdId ? (
            <View style={s.photoCard} testID="booking-photo-upload-section">
              <View style={s.photoCardHeader}>
                <Ionicons name="camera-outline" size={18} color={colors.brand} />
                <Text style={s.photoCardTitle}>Add Photos</Text>
              </View>
              <Text style={s.photoCardSub}>
                Help us understand the job better — attach up to 5 photos or videos.
              </Text>
              <FileUpload
                purpose="portal_booking_photo"
                linkedEntityType="booking_request"
                linkedEntityId={createdId}
                accept="image/*,video/mp4"
                multiple
                maxFiles={5}
                onUploaded={() => setUploadedCount((c) => c + 1)}
              />
              {uploadedCount > 0 ? (
                <Text style={s.uploadedNote} testID="booking-photo-count">
                  {uploadedCount} file{uploadedCount > 1 ? "s" : ""} attached
                </Text>
              ) : null}
            </View>
          ) : null}

          <View style={{ height: spacing.xl }} />
          <PrimaryButton
            title="Done"
            onPress={() => router.replace("/portal/home" as any)}
            testID="request-done-button"
          />
        </KeyboardAwareScrollView>
      </View>
    );
  }

  return (
    <View style={s.root}>
      <Header title="Request a Service" back />
      <KeyboardAwareScrollView
        contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}
        bottomOffset={24}
        keyboardShouldPersistTaps="handled"
      >
        <Text style={s.intro}>
          Tell us what you need and we&apos;ll schedule it for you.
        </Text>

        <Text style={s.label}>WHAT SERVICE DO YOU NEED?</Text>
        <TextInput
          testID="rs-details"
          style={s.textArea}
          placeholder="Describe what you need — e.g., green pool, broken sprinkler, tree trim, etc."
          placeholderTextColor={colors.muted}
          value={details}
          onChangeText={(t) => setDetails(t.slice(0, MAX_LEN))}
          multiline
          numberOfLines={6}
          textAlignVertical="top"
        />
        <View style={s.counterRow}>
          <Text
            style={[s.counterText, charCount < MIN_LEN && charCount > 0 ? { color: colors.warning } : null]}
            testID="rs-details-count"
          >
            {charCount}/{MAX_LEN}
          </Text>
          {charCount > 0 && charCount < MIN_LEN ? (
            <Text style={s.hintText} testID="rs-details-hint">
              At least {MIN_LEN} characters required
            </Text>
          ) : null}
        </View>

        <Text style={s.label}>PREFERRED DATE (OPTIONAL)</Text>
        <View style={s.inputRow}>
          <Ionicons name="calendar-outline" size={18} color={colors.muted} />
          <TextInput
            testID="rs-date"
            style={s.input}
            placeholder="YYYY-MM-DD"
            placeholderTextColor={colors.muted}
            value={date}
            onChangeText={setDate}
            autoCapitalize="none"
            {...(Platform.OS === "web" ? {} : {})}
          />
        </View>

        {error ? <Text style={s.error} testID="request-error">{error}</Text> : null}

        <View style={{ height: spacing.lg }} />
        <PrimaryButton
          testID="rs-submit"
          title="Submit Request"
          icon="send-outline"
          onPress={submit}
          loading={busy}
          disabled={!isValid}
        />
      </KeyboardAwareScrollView>
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  intro: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted, marginBottom: spacing.lg, lineHeight: 22 },
  label: {
    fontFamily: font.semibold, fontSize: 11, letterSpacing: 1,
    color: colors.onSurfaceSecondary, marginBottom: spacing.xs, marginTop: spacing.md,
  },
  textArea: {
    backgroundColor: colors.surface, borderRadius: radius.md,
    padding: spacing.md, minHeight: 140,
    fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface,
    borderWidth: 1.5, borderColor: colors.border, textAlignVertical: "top",
    ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}),
  },
  counterRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: spacing.xs },
  counterText: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  hintText: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.warning },
  inputRow: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    borderWidth: 1.5, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: spacing.md, backgroundColor: colors.surface, height: 52,
  },
  input: {
    flex: 1, fontFamily: font.regular, fontSize: fontSize.lg, color: colors.onSurface,
    ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}),
  },
  error: { color: colors.error, fontFamily: font.medium, fontSize: fontSize.base, marginTop: spacing.sm },
  doneWrap: { alignItems: "center", justifyContent: "center", paddingVertical: spacing.xl },
  doneIcon: { marginBottom: spacing.lg },
  doneTitle: { fontFamily: font.bold, fontSize: fontSize["2xl"], color: colors.onSurface, textAlign: "center" },
  doneSub: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted, textAlign: "center", marginTop: spacing.sm, lineHeight: 20 },
  photoCard: {
    backgroundColor: colors.surface, borderRadius: radius.md,
    padding: spacing.lg, marginTop: spacing.xl,
    borderWidth: 1, borderColor: colors.border,
  },
  photoCardHeader: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm, marginBottom: 4,
  },
  photoCardTitle: { fontFamily: font.bold, fontSize: fontSize.base, color: colors.onSurface },
  photoCardSub: {
    fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginBottom: spacing.md,
  },
  uploadedNote: {
    fontFamily: font.medium, fontSize: fontSize.sm, color: colors.success, marginTop: spacing.sm,
  },
});
