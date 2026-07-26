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

export default function Login() {
  const { login } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [showDemoLogins, setShowDemoLogins] = useState(true);

  // Gate demo logins on /api/config/public flag (mirrors web Login.jsx)
  React.useEffect(() => {
    let live = true;
    (async () => {
      try {
        const cfg = await api.get("/config/public");
        if (live && typeof cfg?.show_demo_logins === "boolean") {
          setShowDemoLogins(cfg.show_demo_logins);
        }
      } catch { /* default: show */ }
    })();
    return () => { live = false; };
  }, []);

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

  const demo = (role: "admin" | "technician" | "customer") => {
    const em =
      role === "admin" ? "admin@aquaterra.com" : role === "technician" ? "mike@aquaterra.com" : "customer@aquaterra.com";
    setEmail(em);
    setPassword("password123");
    submit(em, "password123");
  };

  const DEMOS: { role: "admin" | "technician" | "customer"; label: string; email: string }[] = [
    { role: "admin", label: "Admin", email: "admin@aquaterra.com" },
    { role: "technician", label: "Technician", email: "mike@aquaterra.com" },
    { role: "customer", label: "Customer", email: "customer@aquaterra.com" },
  ];

  return (
    <View style={styles.root}>
      <View style={styles.hero}>
        <Image source={{ uri: IMAGES.loginHero }} style={StyleSheet.absoluteFill} contentFit="cover" />
        <LinearGradient colors={["rgba(0,40,65,0.35)", "rgba(20,30,40,0.55)"]} style={StyleSheet.absoluteFill} />
        <View style={styles.heroTop}>
          <View style={styles.logoBadge}>
            <Ionicons name="water" size={22} color={colors.brand} />
          </View>
          <Text style={styles.brand}>Pool & Landscaping{"\n"}of Vistancia</Text>
        </View>
        <View style={styles.heroBottom}>
          <Text style={styles.heroTitle}>Run your pool & landscape crew like clockwork.</Text>
          <Text style={styles.heroSub}>Schedule jobs, dispatch technicians, send quotes, and collect payments — all in one control room.</Text>
        </View>
      </View>

      <KeyboardAwareScrollView
        style={styles.formWrap}
        contentContainerStyle={styles.formContent}
        bottomOffset={24}
        keyboardShouldPersistTaps="handled"
      >
        <Text style={styles.eyebrow}>WELCOME BACK</Text>
        <Text style={styles.heading}>Sign in to your console</Text>

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

        <Text style={[styles.eyebrow, { marginTop: spacing.xl }]}>DEMO ACCOUNTS</Text>
        {showDemoLogins ? (
        <View style={styles.demoList}>
          {DEMOS.map((d, i) => (
            <Pressable
              key={d.role}
              style={[styles.demoRow, i < DEMOS.length - 1 && styles.demoRowBorder]}
              onPress={() => demo(d.role)}
              testID={`demo-${d.role}-button`}
            >
              <Text style={styles.demoLabel}>{d.label}</Text>
              <Text style={styles.demoEmail}>{d.email}</Text>
            </Pressable>
          ))}
        </View>
        ) : (
          <Text style={{ fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: spacing.xs }}>
            Demo logins are disabled on this environment.
          </Text>
        )}
      </KeyboardAwareScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  hero: { height: 300, justifyContent: "space-between", paddingTop: 56 },
  heroTop: { flexDirection: "row", alignItems: "center", gap: spacing.md, paddingHorizontal: spacing.xl },
  logoBadge: {
    width: 44,
    height: 44,
    borderRadius: 12,
    backgroundColor: "#fff",
    alignItems: "center",
    justifyContent: "center",
  },
  brand: { fontFamily: font.bold, fontSize: fontSize.lg, color: "#fff", lineHeight: 20 },
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
});
