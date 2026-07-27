import React, { useState } from "react";
import { View, Text, StyleSheet, TextInput, Pressable, Platform } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useRouter } from "expo-router";

import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { PrimaryButton } from "@/src/components/ui";

export default function ForgotPassword() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [loading, setLoading] = useState(false);

  const submit = async () => {
    if (!email.trim()) return;
    setLoading(true);
    // TODO: When POST /api/auth/forgot-password ships, swap this for a
    // one-line fetch(...) call. Until then, show the neutral confirmation
    // immediately (UI-only stub — matches web behaviour).
    setTimeout(() => {
      setSubmitted(true);
      setLoading(false);
    }, 600);
  };

  return (
    <View style={styles.root} testID="forgot-password-page">
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} hitSlop={12} testID="forgot-password-back-to-login">
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.headerTitle} testID="forgot-password-title">
          Forgot Password
        </Text>
        <View style={{ width: 22 }} />
      </View>

      <KeyboardAwareScrollView
        style={{ flex: 1 }}
        contentContainerStyle={styles.content}
        bottomOffset={24}
        keyboardShouldPersistTaps="handled"
      >
        {submitted ? (
          <View style={styles.confirmWrap} testID="forgot-password-confirmation">
            <View style={styles.confirmIcon}>
              <Ionicons name="mail-outline" size={40} color={colors.brand} />
            </View>
            <Text style={styles.confirmTitle}>Check your email</Text>
            <Text style={styles.confirmBody}>
              If an account exists for that email, a reset link has been sent.
            </Text>
            <Pressable
              style={styles.backLink}
              onPress={() => router.replace("/login")}
              testID="forgot-password-back-to-login"
            >
              <Ionicons name="arrow-back" size={16} color={colors.brand} />
              <Text style={styles.backLinkText}>Back to sign in</Text>
            </Pressable>
          </View>
        ) : (
          <View testID="forgot-password-form">
            <Text style={styles.intro}>
              Enter the email address associated with your account and we&apos;ll send you a link to reset your password.
            </Text>

            <Text style={styles.label}>EMAIL</Text>
            <View style={styles.inputRow}>
              <Ionicons name="mail-outline" size={18} color={colors.muted} />
              <TextInput
                testID="forgot-password-email"
                style={styles.input}
                placeholder="you@company.com"
                placeholderTextColor={colors.muted}
                value={email}
                onChangeText={setEmail}
                autoCapitalize="none"
                keyboardType="email-address"
                autoCorrect={false}
                textContentType="emailAddress"
                autoComplete="email"
              />
            </View>

            <View style={{ height: spacing.xl }} />
            <PrimaryButton
              testID="forgot-password-submit"
              title="Send Reset Link"
              icon="send-outline"
              onPress={submit}
              loading={loading}
            />

            <Pressable
              style={styles.backLink}
              onPress={() => router.replace("/login")}
              testID="forgot-password-back-to-login"
            >
              <Ionicons name="arrow-back" size={16} color={colors.brand} />
              <Text style={styles.backLinkText}>Back to sign in</Text>
            </Pressable>
          </View>
        )}
      </KeyboardAwareScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    paddingTop: 56,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    backgroundColor: colors.surface,
  },
  headerTitle: {
    fontFamily: font.bold,
    fontSize: fontSize.lg,
    color: colors.onSurface,
  },
  content: {
    padding: spacing.xl,
    paddingBottom: spacing["3xl"],
  },
  intro: {
    fontFamily: font.regular,
    fontSize: fontSize.base,
    color: colors.muted,
    lineHeight: 22,
    marginBottom: spacing.xl,
  },
  label: {
    fontFamily: font.semibold,
    fontSize: 11,
    letterSpacing: 1,
    color: colors.onSurfaceSecondary,
    marginBottom: spacing.xs,
  },
  inputRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    borderWidth: 1.5,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    backgroundColor: colors.surfaceSecondary,
    height: 52,
  },
  input: {
    flex: 1,
    fontFamily: font.regular,
    fontSize: fontSize.lg,
    color: colors.onSurface,
    ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}),
  },
  backLink: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.sm,
    marginTop: spacing.xl,
  },
  backLinkText: {
    fontFamily: font.semibold,
    fontSize: fontSize.base,
    color: colors.brand,
  },
  confirmWrap: {
    alignItems: "center",
    paddingTop: spacing["2xl"],
  },
  confirmIcon: {
    width: 80,
    height: 80,
    borderRadius: 40,
    backgroundColor: colors.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: spacing.lg,
  },
  confirmTitle: {
    fontFamily: font.bold,
    fontSize: fontSize["2xl"],
    color: colors.onSurface,
    marginBottom: spacing.sm,
  },
  confirmBody: {
    fontFamily: font.regular,
    fontSize: fontSize.base,
    color: colors.muted,
    textAlign: "center",
    lineHeight: 22,
    paddingHorizontal: spacing.lg,
  },
});
