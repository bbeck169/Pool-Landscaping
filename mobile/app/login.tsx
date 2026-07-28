import React, { useState } from "react";
import { View, Text, StyleSheet, TextInput, Pressable, Platform } from "react-native";
import { Image } from "expo-image";
import { LinearGradient } from "expo-linear-gradient";
import { Ionicons } from "@expo/vector-icons";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useRouter } from "expo-router";

import { useAuth } from "@/src/auth";
import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize, IMAGES } from "@/src/theme";
import { PrimaryButton } from "@/src/components/ui";
import BrandLogo from "@/src/components/BrandLogo";

export default function Login() {
  const { login } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  // Phase 30 · Feb 2026 — demo-accounts UI removed unconditionally. Manual
  // sign-in still works for the seed accounts; the ``SHOW_DEMO_LOGINS``
  // env flag + ``/config/public`` field are intentionally left alone so
  // nothing else in the codebase breaks.

  const submit = async (e?: string, p?: string) => {
    const em = (e ?? email).trim().toLowerCase();
    const pw = p ?? password;
    if (!em || !pw) {
      setError("Please enter email and password");
      return;
    }
    setError("");
    setLoading(true);
    try {
      await login(em, pw);
      router.replace("/(app)");
    } catch (err: any) {
      setError(err.message || "Login failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <View style={styles.root}>
      <View style={styles.hero}>
        <Image source={{ uri: IMAGES.loginHero }} style={StyleSheet.absoluteFill} contentFit="cover" />
        <LinearGradient colors={["rgba(0,40,65,0.35)", "rgba(20,30,40,0.55)"]} style={StyleSheet.absoluteFill} />
        <View style={styles.heroTop}>
          {/* Phase 33 · Feb 2026 — logo + two-line brand header
              stacked vertically, centered. Layout order:
                [logo] → [Welcome to] → [Pool & Landscaping ... LLC].
              Replaces the previous water-icon badge on the left. */}
          <View style={{ width: "80%", marginBottom: spacing.md }}>
            <BrandLogo size="lg" testID="login-logo-full" />
          </View>
          <Text style={styles.brand}>
            <Text style={styles.brandLine1}>Welcome to{"\n"}</Text>
            <Text style={styles.brandLine2}>Pool & Landscaping of Vistancia LLC</Text>
          </Text>
        </View>
        <View style={styles.heroBottom}>
          {/* Phase 31 · Feb 2026 — marketing tagline removed. The
              two-line brand header at the top carries the entire
              top-of-screen message now. ``heroBottom`` is kept as an
              empty flex row so the hero column's ``space-between``
              layout still pushes the brand header to the top. */}
        </View>
      </View>

      <KeyboardAwareScrollView
        style={styles.formWrap}
        contentContainerStyle={styles.formContent}
        bottomOffset={24}
        keyboardShouldPersistTaps="handled"
      >
        <Text style={styles.eyebrow}>WELCOME BACK</Text>
        {/* Phase 31 · Feb 2026 — heading font size halved from the
            theme's ``fontSize["2xl"]`` (24pt) to 12pt inline. Same
            treatment as the Line-2 brand tweak: keep the shared style
            for family/color/weight/spacing but override just the size
            so downstream refactors of ``styles.heading`` don't
            undo this. */}
        <Text style={[styles.heading, { fontSize: 12 }]}
              testID="login-heading">
          Sign in to your console
        </Text>

        <Text style={styles.label}>EMAIL</Text>
        <View style={styles.inputRow}>
          <Ionicons name="mail-outline" size={18} color={colors.muted} />
          <TextInput
            testID="login-email-input"
            style={styles.input}
            placeholder="you@company.com"
            placeholderTextColor={colors.muted}
            value={email}
            onChangeText={setEmail}
            autoCapitalize="none"
            keyboardType="email-address"
            autoCorrect={false}
          />
        </View>

        <Text style={styles.label}>PASSWORD</Text>
        <View style={styles.inputRow}>
          <Ionicons name="lock-closed-outline" size={18} color={colors.muted} />
          <TextInput
            testID="login-password-input"
            style={styles.input}
            placeholder="••••••••"
            placeholderTextColor={colors.muted}
            value={password}
            onChangeText={setPassword}
            secureTextEntry={!showPw}
          />
          <Pressable onPress={() => setShowPw((s) => !s)} hitSlop={10} testID="login-toggle-password">
            <Ionicons name={showPw ? "eye-off-outline" : "eye-outline"} size={18} color={colors.muted} />
          </Pressable>
        </View>

        <Pressable
          style={styles.forgotLink}
          onPress={() => router.push("/forgot-password")}
          testID="login-forgot-password-link"
        >
          <Text style={styles.forgotText}>Forgot password?</Text>
        </Pressable>

        {error ? (
          <Text style={styles.error} testID="login-error">
            {error}
          </Text>
        ) : null}

        <View style={{ height: spacing.lg }} />
        <PrimaryButton testID="login-submit-button" title="Sign in" icon="arrow-forward" onPress={() => submit()} loading={loading} />

        <Pressable style={styles.signupLink} onPress={() => router.push("/signup")} testID="go-to-signup">
          <Text style={styles.signupText}>
            New customer? <Text style={styles.signupBold}>Create an account</Text>
          </Text>
        </Pressable>

        {process.env.EXPO_PUBLIC_ENV === "preview" ? (
          <View style={styles.demoSection} testID="demo-login-section">
            <Text style={styles.demoSectionTitle}>DEMO ACCOUNTS</Text>
            <Text style={styles.demoSectionSub}>Tap to sign in instantly</Text>
            <View style={styles.demoList}>
              {([
                { label: "Super Admin", email: "super@aquaterra.com", icon: "shield" as const },
                { label: "Admin", email: "manager@aquaterra.com", icon: "person-circle" as const },
                { label: "Customer", email: "customer@aquaterra.com", icon: "people" as const },
                { label: "Pool Tech", email: "mike@aquaterra.com", icon: "construct" as const },
              ] as const).map((acct, i, arr) => (
                <Pressable
                  key={acct.email}
                  style={[styles.demoRow, i < arr.length - 1 && styles.demoRowBorder]}
                  onPress={() => submit(acct.email, "password123")}
                  testID={`demo-login-${acct.label.toLowerCase().replace(/\s+/g, "-")}-btn`}
                >
                  <View style={{ flexDirection: "row", alignItems: "center", gap: 10 }}>
                    <Ionicons name={acct.icon} size={20} color={colors.brand} />
                    <View>
                      <Text style={styles.demoLabel}>{acct.label}</Text>
                      <Text style={styles.demoEmail}>{acct.email}</Text>
                    </View>
                  </View>
                  <Ionicons name="arrow-forward-circle" size={22} color={colors.brand} />
                </Pressable>
              ))}
            </View>
          </View>
        ) : null}

        {/* Phase 30 · Feb 2026 — DEMO ACCOUNTS block removed
            unconditionally. Manual sign-in above still authenticates the
            three seed accounts — only the visual shortcuts are gone. */}
      </KeyboardAwareScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  hero: { height: 300, justifyContent: "space-between", paddingTop: 56 },
  heroTop: { flexDirection: "column", alignItems: "center", gap: spacing.md, paddingHorizontal: spacing.xl },
  logoBadge: {
    width: 44,
    height: 44,
    borderRadius: 12,
    backgroundColor: "#fff",
    alignItems: "center",
    justifyContent: "center",
  },
  brand: { fontFamily: font.bold, fontSize: fontSize.lg, color: "#fff", lineHeight: 20, textAlign: "center" },
  // Phase 30 · Feb 2026 — two-line brand header. Line 2 is exactly half
  // the size of Line 1 (28 → 14) per the spec. ``lineHeight`` on Line 1
  // is tightened so Line 2 sits directly below with only natural
  // line-height as separation. Phase 33 · centered under the logo.
  brandLine1: { fontFamily: font.bold, fontSize: 28, color: "#fff", lineHeight: 30, textAlign: "center" },
  brandLine2: { fontFamily: font.bold, fontSize: 14, color: "#fff", lineHeight: 18, textAlign: "center" },
  heroBottom: { padding: spacing.xl, paddingBottom: spacing.xl },
  heroTitle: { fontFamily: font.bold, fontSize: 26, color: "#fff", lineHeight: 30 },
  heroSub: { fontFamily: font.regular, fontSize: fontSize.base, color: "rgba(255,255,255,0.9)", marginTop: spacing.sm, lineHeight: 19 },
  formWrap: { flex: 1, marginTop: -20 },
  formContent: {
    backgroundColor: colors.surface,
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    padding: spacing.xl,
    paddingBottom: spacing["3xl"],
    minHeight: "100%",
  },
  eyebrow: { fontFamily: font.semibold, fontSize: 11, letterSpacing: 1.5, color: colors.muted, marginBottom: spacing.xs },
  heading: { fontFamily: font.bold, fontSize: fontSize["2xl"], color: colors.onSurface, marginBottom: spacing.lg },
  label: {
    fontFamily: font.semibold,
    fontSize: 11,
    letterSpacing: 1,
    color: colors.onSurfaceSecondary,
    marginBottom: spacing.xs,
    marginTop: spacing.md,
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
  forgotLink: { alignSelf: "flex-end", marginTop: spacing.sm },
  forgotText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.brand },
  error: { color: colors.error, fontFamily: font.medium, fontSize: fontSize.base, marginTop: spacing.md },
  signupLink: { alignItems: "center", marginTop: spacing.lg },
  signupText: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted },
  signupBold: { fontFamily: font.semibold, color: colors.brand },
  demoList: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    overflow: "hidden",
    marginTop: spacing.sm,
  },
  demoRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: spacing.lg,
    height: 52,
    backgroundColor: colors.surfaceSecondary,
  },
  demoRowBorder: { borderBottomWidth: 1, borderBottomColor: colors.border },
  demoLabel: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  demoEmail: {
    fontFamily: Platform.select({ ios: "Menlo", android: "monospace", default: "monospace" }),
    fontSize: fontSize.sm,
    color: colors.muted,
  },
  demoSection: {
    marginTop: spacing.xl,
    paddingTop: spacing.lg,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  demoSectionTitle: {
    fontFamily: font.bold, fontSize: 11, letterSpacing: 1.5,
    color: colors.brand, marginBottom: 2,
  },
  demoSectionSub: {
    fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted,
    marginBottom: spacing.sm,
  },
});
