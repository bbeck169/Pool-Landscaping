import React, { useState, useEffect } from "react";
import { View, Text, StyleSheet, TextInput, Pressable, Platform, ActivityIndicator } from "react-native";
import { Image } from "expo-image";
import { LinearGradient } from "expo-linear-gradient";
import { Ionicons } from "@expo/vector-icons";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useRouter, useLocalSearchParams } from "expo-router";

import { useAuth } from "@/src/auth";
import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize, IMAGES } from "@/src/theme";
import { PrimaryButton } from "@/src/components/ui";
import BrandLogo from "@/src/components/BrandLogo";
import AIAvatar from "@/src/components/ai/AIAvatar";
import { isPreviewOrDev } from "@/src/utils/env";
// Feb-2026 · Phase 1 offline — skip the login screen when a fresh
// cached JWT (<24h) + a cached ``/me`` payload exist.  The tech
// can start their day in airplane mode and still see today's route.
import { getFreshCachedJwt } from "@/src/lib/offline/jwtCache";
import { getCachedMe } from "@/src/lib/offline/cache";
import { storage } from "@/src/utils/storage";

export default function Login() {
  const { login, finalizeAccountChoice } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  // Feb 2026 · Demo-login P0 hotfix — see pages/Login.jsx for the
  // full rationale. Build-time ``EXPO_PUBLIC_ENV`` is baked into
  // the bundle at ``eas build`` time and leaks to production;
  // fetch ``app_env`` from ``/api/config/public`` instead. Default
  // null → hide the demo tiles (fail-closed).
  //
  // Feb 2026 · Hotfix #3 (mobile parity with web) — belt-and-
  // suspenders. Even when the server reports demo tiles are
  // allowed, refuse to render them unless the app is talking to a
  // preview / dev backend host. Prevents a wrong-env prod backend
  // (``SHOW_DEMO_LOGINS=true`` + ``APP_ENV=preview`` seeded in
  // ``.env``) from overriding the gate. Prefers the new
  // ``/config/features.demo_logins_enabled`` flag when present.
  const [demoServerAllowed, setDemoServerAllowed] = useState<boolean | null>(null);

  // Task 6b · Deep-link "link revoked" banner.
  const searchParams = useLocalSearchParams<{ reason?: string }>();
  const [linkRevokedBanner, setLinkRevokedBanner] = useState(false);
  useEffect(() => {
    if (searchParams?.reason === "link_revoked") {
      setLinkRevokedBanner(true);
    }
  }, [searchParams?.reason]);

  // Task 4 · Multi-account chooser state.
  const [chooser, setChooser] = useState<{
    email: string;
    choices: { account_id: string; role: string; display: string }[];
    choice_token: string;
  } | null>(null);

  // Feb-2026 · Phase 1 offline — on mount, if there's a still-fresh
  // JWT (<24h) + a cached ``/me`` payload, hydrate AsyncStorage and
  // bounce to (app).  This lets a tech open the app offline first
  // thing in the morning and land on today's route without a
  // password prompt.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const token = await getFreshCachedJwt();
        if (!token) return;
        const cachedUser = await getCachedMe();
        if (!cachedUser?.id) return;
        // Prime the AuthProvider's storage keys — its boot effect
        // reads AsyncStorage(USER_KEY) + SecureStore(TOKEN_KEY), so
        // hydrating those is enough to skip the login screen on
        // the very next tick.
        await storage.setItem("pool_crm_user", JSON.stringify(cachedUser));
        if (cancelled) return;
        router.replace("/(app)");
      } catch {
        // Silent — fall through to normal manual sign-in.
      }
    })();
    return () => { cancelled = true; };
  }, [router]);
  useEffect(() => {
    let cancelled = false;
    (api as any)
      .get("/config/features")
      .then((r: any) => {
        if (cancelled) return;
        if (r && typeof r.demo_logins_enabled === "boolean") {
          setDemoServerAllowed(r.demo_logins_enabled);
          return;
        }
        // Legacy fallback for older backends.
        return (api as any).get("/config/public").then((rr: any) => {
          if (cancelled) return;
          const v = String(rr?.app_env || "").toLowerCase();
          setDemoServerAllowed(!!v && v !== "production");
        });
      })
      .catch(() => {
        if (cancelled) return;
        setDemoServerAllowed(false); // fail-closed
      });
    return () => { cancelled = true; };
  }, []);
  const hostAllowed = React.useMemo(() => isPreviewOrDev(), []);
  const showDemoTiles = hostAllowed && demoServerAllowed === true;
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
      const result = await login(em, pw);
      if (result?.kind === "choice") {
        // Task 4 — multi-account: show the chooser instead of navigating.
        setChooser({
          email: result.email,
          choices: result.choices,
          choice_token: result.choice_token,
        });
        return;
      }
      if (result?.kind === "password_reset_required") {
        // Temp password fork — navigate to set-password screen.
        router.push({
          pathname: "/set-password",
          params: {
            reset_token: result.reset_token,
            email: em,
            ttl: String(result.token_ttl_minutes || 15),
          },
        });
        return;
      }
      setLinkRevokedBanner(false);
      router.replace("/(app)");
    } catch (err: any) {
      setError(err.message || "Login failed");
    } finally {
      setLoading(false);
    }
  };

  // Task 4 — handle account selection from the chooser.
  const pickAccount = async (accountId: string) => {
    if (!chooser) return;
    setError("");
    setLoading(true);
    try {
      const result = await finalizeAccountChoice(chooser.choice_token, accountId);
      if (result?.kind === "password_reset_required") {
        // Temp password fork after chooser selection.
        setChooser(null);
        router.push({
          pathname: "/set-password",
          params: {
            reset_token: result.reset_token,
            email: chooser.email,
            ttl: String(result.token_ttl_minutes || 15),
          },
        });
        return;
      }
      setChooser(null);
      setLinkRevokedBanner(false);
      router.replace("/(app)");
    } catch (err: any) {
      setError(err.message || "Could not sign in to that account");
    } finally {
      setLoading(false);
    }
  };

  const cancelChooser = () => {
    setChooser(null);
    setError("");
    setPassword("");
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
            <BrandLogo size="lg" testID="login-logo-full" onPress={null} />
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
        {/* Task 6b · "Link revoked" banner — shown when deep link includes ?reason=link_revoked */}
        {linkRevokedBanner ? (
          <View style={styles.revokedBanner} testID="link-revoked-banner">
            <View style={{ flexDirection: "row", alignItems: "center", gap: 8, flex: 1 }}>
              <Ionicons name="shield-outline" size={18} color="#92400E" />
              <Text style={styles.revokedBannerText}>
                This link has been revoked. Please contact your service provider for a new link.
              </Text>
            </View>
            <Pressable onPress={() => setLinkRevokedBanner(false)} hitSlop={8} testID="dismiss-revoked-banner">
              <Ionicons name="close" size={16} color="#92400E" />
            </Pressable>
          </View>
        ) : null}

        {/* Task 4 · Account Chooser — shown when backend returns multi_account_choice_required */}
        {chooser ? (
          <View testID="account-chooser-screen">
            <Text style={styles.eyebrow}>ACCOUNT</Text>
            <Text style={[styles.heading, { fontSize: 14 }]} testID="account-chooser-heading">
              Which account?
            </Text>
            <Text style={styles.chooserSubhead}>
              We found two accounts for this email.{"\n"}Pick one to continue.
            </Text>

            {chooser.choices.map((c) => (
              <Pressable
                key={c.account_id}
                style={({ pressed }) => [
                  styles.chooserCard,
                  pressed && { backgroundColor: colors.surfaceSecondary },
                ]}
                onPress={() => pickAccount(c.account_id)}
                disabled={loading}
                testID={`account-choice-${c.account_id}`}
              >
                <Ionicons
                  name={c.role === "customer" ? "person-outline" : "briefcase-outline"}
                  size={20}
                  color={colors.brand}
                />
                <Text style={styles.chooserCardText} numberOfLines={2}>
                  {c.display}
                </Text>
                <Ionicons name="chevron-forward" size={16} color={colors.muted} />
              </Pressable>
            ))}

            {loading ? (
              <ActivityIndicator style={{ marginTop: spacing.lg }} color={colors.brand} />
            ) : null}

            {error ? (
              <Text style={styles.error} testID="account-chooser-error">
                {error}
              </Text>
            ) : null}

            <Pressable
              onPress={cancelChooser}
              style={styles.chooserCancelLink}
              testID="account-chooser-cancel"
            >
              <Text style={styles.forgotText}>Not you? Log out.</Text>
            </Pressable>
          </View>
        ) : (
        /* Normal login form */
        <View testID="login-form-container">
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

        {/* Phase 39 · Feb-2026 — Terms of Service link. Routes to the
            top-level ``/terms`` (public re-export of
            ``portal/terms.tsx``) so pre-auth customers can read the
            document without being bounced by the portal auth gate. */}
        <View style={styles.termsRow}>
          <Text style={styles.termsText}>
            By signing in, you agree to our{" "}
            <Text
              style={styles.termsLink}
              onPress={() => router.push("/terms")}
              testID="login-terms-link"
            >
              Terms of Service
            </Text>
            .
          </Text>
        </View>

        {showDemoTiles ? (
          <View style={styles.demoSection} testID="demo-login-section">
            <Text style={styles.demoSectionTitle}>DEMO ACCOUNTS</Text>
            <Text style={styles.demoSectionSub}>Tap to sign in instantly</Text>
            {/* Phase 50 · Feb-2026 — Lana AI greeter above the demo
                grid. Idle Lottie loop signals that the AI employees
                are already active. Mirrors the web login treatment. */}
            <View style={styles.lanaGreeter} testID="login-lana-greeter">
              <AIAvatar size={40} testID="login-lana-avatar" />
              <View style={{ flex: 1, minWidth: 0 }}>
                <Text style={styles.lanaGreeterTitle}>
                  Lana &amp; your AI team are online
                </Text>
                <Text style={styles.lanaGreeterSub}>
                  Sign in to see them animate across the app.
                </Text>
              </View>
            </View>
            <View style={styles.demoList}>
              {([
                { label: "Super Admin", email: "super@aquaterra.com", icon: "shield" as const },
                { label: "Admin", email: "manager@aquaterra.com", icon: "person-circle" as const },
                { label: "Customer", email: "customer@aquaterra.com", icon: "people" as const },
                { label: "Landscape Tech", email: "landscaper@aquaterra.com", icon: "construct" as const },
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
        </View>
        )}
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
  lanaGreeter: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    padding: spacing.sm + 2,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surfaceSecondary,
    marginBottom: spacing.sm,
  },
  lanaGreeterTitle: {
    fontFamily: font.semibold,
    fontSize: fontSize.base,
    color: colors.onSurface,
  },
  lanaGreeterSub: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
    marginTop: 1,
  },
  // Task 4 · Account chooser styles
  chooserSubhead: {
    fontFamily: font.regular,
    fontSize: fontSize.base,
    color: colors.muted,
    marginBottom: spacing.xl,
    lineHeight: 20,
  },
  chooserCard: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.lg,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
    marginBottom: spacing.sm,
  },
  chooserCardText: {
    flex: 1,
    fontFamily: font.semibold,
    fontSize: fontSize.base,
    color: colors.onSurface,
  },
  chooserCancelLink: {
    alignItems: "center",
    marginTop: spacing.xl,
  },
  // Task 6b · Link revoked banner
  revokedBanner: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    backgroundColor: "#FEF3C7",
    borderColor: "#FDE68A",
    borderWidth: 1,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.md,
    marginBottom: spacing.lg,
  },
  revokedBannerText: {
    flex: 1,
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: "#92400E",
    lineHeight: 18,
  },
});
