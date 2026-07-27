/**
 * Phase 34 · Change Password (in-app, for logged-in users)
 * POST /api/auth/change-password { current_password, new_password }
 */
import React, { useState } from "react";
import { View, Text, StyleSheet, TextInput, Platform, Alert } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useRouter } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import { PrimaryButton } from "@/src/components/ui";

export default function ChangePassword() {
  const router = useRouter();
  const [current, setCurrent] = useState("");
  const [newPw, setNewPw] = useState("");
  const [confirm, setConfirm] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const valid = current.length > 0 && newPw.length >= 8 && newPw === confirm;

  const submit = async () => {
    if (!valid) return;
    setLoading(true);
    setError("");
    try {
      await api.post("/auth/change-password", {
        current_password: current,
        new_password: newPw,
      });
      Alert.alert("Password changed", "Your password has been updated.", [
        { text: "OK", onPress: () => router.back() },
      ]);
    } catch (e: any) {
      setError(e.message || "Failed to change password. Check your current password.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <View style={s.root} testID="change-password-page">
      <Header title="Change Password" back />
      <KeyboardAwareScrollView
        style={{ flex: 1 }}
        contentContainerStyle={s.content}
        bottomOffset={24}
        keyboardShouldPersistTaps="handled"
      >
        <Text style={s.label}>CURRENT PASSWORD</Text>
        <TextInput
          testID="change-pw-current"
          style={s.input}
          placeholder="Current password"
          placeholderTextColor={colors.muted}
          value={current}
          onChangeText={setCurrent}
          secureTextEntry
          autoComplete="current-password"
          textContentType="password"
        />

        <Text style={s.label}>NEW PASSWORD</Text>
        <TextInput
          testID="change-pw-new"
          style={s.input}
          placeholder="New password (8+ chars)"
          placeholderTextColor={colors.muted}
          value={newPw}
          onChangeText={setNewPw}
          secureTextEntry
          autoComplete="new-password"
          textContentType="newPassword"
        />

        <Text style={s.label}>CONFIRM NEW PASSWORD</Text>
        <TextInput
          testID="change-pw-confirm"
          style={s.input}
          placeholder="Confirm new password"
          placeholderTextColor={colors.muted}
          value={confirm}
          onChangeText={setConfirm}
          secureTextEntry
          autoComplete="new-password"
          textContentType="newPassword"
        />

        {newPw.length > 0 && newPw.length < 8 ? (
          <Text style={s.hint}>At least 8 characters required</Text>
        ) : null}
        {confirm.length > 0 && newPw !== confirm ? (
          <Text style={s.hint}>Passwords do not match</Text>
        ) : null}
        {error ? <Text style={s.error} testID="change-pw-error">{error}</Text> : null}

        <View style={{ height: spacing.xl }} />
        <PrimaryButton
          title="Update Password"
          icon="lock-closed-outline"
          onPress={submit}
          loading={loading}
          disabled={!valid}
          testID="change-pw-submit"
        />
      </KeyboardAwareScrollView>
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  content: { padding: spacing.xl, paddingBottom: spacing["3xl"] },
  label: { fontFamily: font.semibold, fontSize: 11, letterSpacing: 1, color: colors.onSurfaceSecondary, marginBottom: spacing.xs, marginTop: spacing.md },
  input: {
    borderWidth: 1.5, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: spacing.md, height: 52,
    backgroundColor: colors.surface,
    fontFamily: font.regular, fontSize: fontSize.lg, color: colors.onSurface,
    ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}),
  },
  hint: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.warning, marginTop: spacing.xs },
  error: { fontFamily: font.medium, fontSize: fontSize.base, color: colors.error, marginTop: spacing.sm },
});
