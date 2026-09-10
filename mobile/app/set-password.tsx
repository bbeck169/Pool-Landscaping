/**
 * Set Password screen — reached when a customer's first login uses
 * a temporary password and the backend returns
 * `{ status: "password_reset_required", reset_token, ... }`.
 *
 * UX: "Set your permanent password" (distinct from the regular
 * forgot-password flow).
 *
 * After successful reset, silently re-logins with the new password
 * and redirects to /(app). No dead-end "success, log in again" screen.
 */
import React, { useState, useRef } from "react";
import {
  View, Text, StyleSheet, TextInput, Pressable, Platform,
  Alert,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useLocalSearchParams, useRouter } from "expo-router";

import { useAuth } from "@/src/auth";
import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { PrimaryButton } from "@/src/components/ui";

export default function SetPasswordScreen() {
  const router = useRouter();
  const { login } = useAuth();
  const params = useLocalSearchParams<{
    reset_token?: string;
    email?: string;
    ttl?: string;
  }>();

  const resetToken = params.reset_token || "";
  const emailHint = params.email || "";
  const ttlMin = Number(params.ttl) || 15;

  const [pw, setPw] = useState("");
  const [pwConfirm, setPwConfirm] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const confirmRef = useRef<TextInput>(null);

  const handleSubmit = async () => {
    setError("");
    if (!pw || pw.length < 6) {
      setError("Password must be at least 6 characters.");
      return;
    }
    if (pw !== pwConfirm) {
      setError("Passwords don't match.");
      return;
    }
    if (!resetToken) {
      setError("Reset token is missing. Please sign in again.");
      return;
    }

    setLoading(true);
    try {
      // Step 1: Reset the password.
      const res = await api.post("/auth/reset-password", {
        token: resetToken,
        new_password: pw,
      });

      if (!res?.ok) {
        setError(res?.message || "Password reset failed.");
        setLoading(false);
        return;
      }

      // Step 2: Silently re-login with the new password.
      if (emailHint) {
        try {
          const loginResult = await login(emailHint, pw);
          if (loginResult?.kind === "success") {
            router.replace("/(app)");
            return;
          }
          // If login returns another fork (unlikely but safe), fall back
          // to manual sign-in.
        } catch {
          // Silent re-login failed — user will manually sign in.
        }
      }

      // Fallback: navigate back to login with a success message.
      router.replace("/login");
    } catch (e: any) {
      const msg = e?.message || e?.detail || "";
      const isExpired =
        typeof msg === "string" &&
        (msg.toLowerCase().includes("expired") ||
         msg.toLowerCase().includes("invalid") ||
         msg.toLowerCase().includes("token"));

      if (isExpired) {
        setError("");
        Alert.alert(
          "Link expired",
          "Your reset link has expired. Sign in again to get a fresh one.",
          [
            {
              text: "Back to sign in",
              onPress: () => router.replace("/login"),
            },
          ],
        );
      } else {
        setError(msg || "Something went wrong. Please try again.");
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <View style={s.root} testID="set-password-screen">
      <KeyboardAwareScrollView
        style={s.scroll}
        contentContainerStyle={s.content}
        bottomOffset={24}
        keyboardShouldPersistTaps="handled"
      >
        {/* Header */}
        <View style={s.iconWrap}>
          <Ionicons name="key" size={32} color={colors.brand} />
        </View>
        <Text style={s.eyebrow}>FIRST-TIME SETUP</Text>
        <Text style={s.heading} testID="set-password-heading">
          Set your permanent password
        </Text>
        <Text style={s.subtext}>
          Your account was created with a temporary password. Choose a new
          password you{"'"}ll remember — you{"'"}ll be signed in automatically.
        </Text>

        {emailHint ? (
          <View style={s.emailChip} testID="set-password-email-hint">
            <Ionicons name="mail-outline" size={14} color={colors.muted} />
            <Text style={s.emailChipText}>{emailHint}</Text>
          </View>
        ) : null}

        {/* New password */}
        <Text style={s.label}>NEW PASSWORD</Text>
        <View style={s.inputRow}>
          <Ionicons name="lock-closed-outline" size={18} color={colors.muted} />
          <TextInput
            testID="set-password-input"
            style={s.input}
            placeholder="At least 6 characters"
            placeholderTextColor={colors.muted}
            value={pw}
            onChangeText={setPw}
            secureTextEntry={!showPw}
            returnKeyType="next"
            onSubmitEditing={() => confirmRef.current?.focus()}
          />
          <Pressable onPress={() => setShowPw((v) => !v)} hitSlop={10} testID="set-password-toggle-visibility">
            <Ionicons name={showPw ? "eye-off-outline" : "eye-outline"} size={18} color={colors.muted} />
          </Pressable>
        </View>

        {/* Confirm password */}
        <Text style={s.label}>CONFIRM PASSWORD</Text>
        <View style={s.inputRow}>
          <Ionicons name="checkmark-circle-outline" size={18} color={colors.muted} />
          <TextInput
            ref={confirmRef}
            testID="set-password-confirm-input"
            style={s.input}
            placeholder="Re-enter your password"
            placeholderTextColor={colors.muted}
            value={pwConfirm}
            onChangeText={setPwConfirm}
            secureTextEntry={!showPw}
            returnKeyType="done"
            onSubmitEditing={handleSubmit}
          />
        </View>

        {/* Strength hint */}
        {pw.length > 0 && pw.length < 6 ? (
          <Text style={s.hint} testID="set-password-weak-hint">
            <Ionicons name="alert-circle" size={12} color="#D97706" /> Password too short
          </Text>
        ) : null}

        {/* Error */}
        {error ? (
          <Text style={s.error} testID="set-password-error">{error}</Text>
        ) : null}

        {/* TTL notice */}
        <Text style={s.ttlNotice}>
          This link is valid for {ttlMin} minutes. After that you{"'"}ll need to sign in again.
        </Text>

        <View style={{ height: spacing.lg }} />
        <PrimaryButton
          testID="set-password-submit"
          title={loading ? "Setting password…" : "Set password & sign in"}
          icon={loading ? undefined : "arrow-forward"}
          onPress={handleSubmit}
          loading={loading}
          disabled={loading || !pw || !pwConfirm}
        />

        {/* Back to login */}
        <Pressable
          style={s.backLink}
          onPress={() => router.replace("/login")}
          testID="set-password-back-to-login"
        >
          <Text style={s.backLinkText}>
            <Ionicons name="arrow-back" size={13} color={colors.brand} /> Back to sign in
          </Text>
        </Pressable>
      </KeyboardAwareScrollView>
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  scroll: { flex: 1 },
  content: { padding: spacing.xl, paddingTop: 80, paddingBottom: 60 },
  iconWrap: {
    width: 56, height: 56, borderRadius: 28,
    backgroundColor: colors.brand + "14",
    alignItems: "center", justifyContent: "center",
    marginBottom: spacing.lg,
  },
  eyebrow: { fontFamily: font.semibold, fontSize: 11, letterSpacing: 1.5, color: colors.muted, marginBottom: spacing.xs },
  heading: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface, marginBottom: spacing.sm },
  subtext: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted, lineHeight: 21, marginBottom: spacing.lg },
  emailChip: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: spacing.md, paddingVertical: 6,
    borderRadius: radius.sm, borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.surfaceSecondary,
    alignSelf: "flex-start", marginBottom: spacing.lg,
  },
  emailChipText: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurface },
  label: {
    fontFamily: font.semibold, fontSize: 11, letterSpacing: 1,
    color: colors.onSurfaceSecondary, marginBottom: spacing.xs, marginTop: spacing.md,
  },
  inputRow: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    borderWidth: 1.5, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: spacing.md, backgroundColor: colors.surfaceSecondary, height: 52,
  },
  input: {
    flex: 1, fontFamily: font.regular, fontSize: fontSize.lg, color: colors.onSurface,
    ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}),
  },
  hint: { fontFamily: font.medium, fontSize: fontSize.sm, color: "#D97706", marginTop: spacing.sm },
  error: { fontFamily: font.medium, fontSize: fontSize.base, color: colors.error, marginTop: spacing.md },
  ttlNotice: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: spacing.lg, lineHeight: 18 },
  backLink: { alignItems: "center", marginTop: spacing.xl },
  backLinkText: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.brand },
});
