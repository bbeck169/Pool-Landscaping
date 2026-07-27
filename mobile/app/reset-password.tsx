/**
 * Phase 34 · Reset Password screen
 * Accessed via deep link: /reset-password?token=<token>
 * POST /api/auth/reset-password { token, new_password }
 */
import React, { useState } from "react";
import { View, Text, StyleSheet, TextInput, Platform } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useLocalSearchParams, useRouter } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { PrimaryButton } from "@/src/components/ui";

export default function ResetPassword() {
  const router = useRouter();
  const { token } = useLocalSearchParams<{ token: string }>();
  const [pw, setPw] = useState("");
  const [confirm, setConfirm] = useState("");
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState("");

  const valid = pw.length >= 8 && pw === confirm;

  const submit = async () => {
    if (!valid) return;
    setLoading(true);
    setError("");
    try {
      await api.post("/auth/reset-password", { token, new_password: pw });
      setDone(true);
    } catch (e: any) {
      setError(e.message || "Reset failed. Link may have expired.");
    } finally {
      setLoading(false);
    }
  };

  if (done) {
    return (
      <View style={s.root} testID="reset-password-success">
        <View style={s.center}>
          <View style={s.successIcon}>
            <Ionicons name="checkmark-circle" size={56} color={colors.success} />
          </View>
          <Text style={s.successTitle}>Password updated</Text>
          <Text style={s.successSub}>You can now sign in with your new password.</Text>
          <View style={{ height: spacing.xl }} />
          <PrimaryButton title="Back to sign in" onPress={() => router.replace("/login")} testID="reset-go-login" />
        </View>
      </View>
    );
  }

  return (
    <View style={s.root} testID="reset-password-page">
      <View style={s.header}>
        <Text style={s.headerTitle}>Set New Password</Text>
      </View>
      <KeyboardAwareScrollView
        style={{ flex: 1 }}
        contentContainerStyle={s.content}
        bottomOffset={24}
        keyboardShouldPersistTaps="handled"
      >
        <Text style={s.intro}>Choose a strong new password (8+ characters).</Text>

        <Text style={s.label}>NEW PASSWORD</Text>
        <TextInput
          testID="reset-pw-field"
          style={s.input}
          placeholder="New password"
          placeholderTextColor={colors.muted}
          value={pw}
          onChangeText={setPw}
          secureTextEntry
          autoComplete="new-password"
          textContentType="newPassword"
        />

        <Text style={s.label}>CONFIRM PASSWORD</Text>
        <TextInput
          testID="reset-pw-confirm"
          style={s.input}
          placeholder="Confirm new password"
          placeholderTextColor={colors.muted}
          value={confirm}
          onChangeText={setConfirm}
          secureTextEntry
          autoComplete="new-password"
          textContentType="newPassword"
        />

        {pw.length > 0 && pw.length < 8 ? (
          <Text style={s.hint}>At least 8 characters required</Text>
        ) : null}
        {confirm.length > 0 && pw !== confirm ? (
          <Text style={s.hint}>Passwords do not match</Text>
        ) : null}
        {error ? <Text style={s.error} testID="reset-error">{error}</Text> : null}

        <View style={{ height: spacing.lg }} />
        <PrimaryButton title="Reset Password" icon="lock-closed-outline" onPress={submit} loading={loading} disabled={!valid} testID="reset-pw-submit" />
      </KeyboardAwareScrollView>
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  header: { paddingTop: 56, paddingHorizontal: spacing.lg, paddingBottom: spacing.md, borderBottomWidth: 1, borderBottomColor: colors.border },
  headerTitle: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface, textAlign: "center" },
  content: { padding: spacing.xl, paddingBottom: spacing["3xl"] },
  intro: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted, marginBottom: spacing.lg, lineHeight: 22 },
  label: { fontFamily: font.semibold, fontSize: 11, letterSpacing: 1, color: colors.onSurfaceSecondary, marginBottom: spacing.xs, marginTop: spacing.md },
  input: {
    borderWidth: 1.5, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: spacing.md, height: 52,
    backgroundColor: colors.surfaceSecondary,
    fontFamily: font.regular, fontSize: fontSize.lg, color: colors.onSurface,
    ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}),
  },
  hint: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.warning, marginTop: spacing.xs },
  error: { fontFamily: font.medium, fontSize: fontSize.base, color: colors.error, marginTop: spacing.sm },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: spacing.xl },
  successIcon: { marginBottom: spacing.lg },
  successTitle: { fontFamily: font.bold, fontSize: fontSize["2xl"], color: colors.onSurface },
  successSub: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted, marginTop: spacing.sm, textAlign: "center" },
});
