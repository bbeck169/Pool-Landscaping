import React, { useState } from "react";
import { View, Text, StyleSheet } from "react-native";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useRouter } from "expo-router";

import { useAuth } from "@/src/auth";
import { colors, spacing, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import { PrimaryButton } from "@/src/components/ui";
import { Field } from "@/app/customer/new";

export default function Signup() {
  const router = useRouter();
  const { signup } = useAuth();
  const [form, setForm] = useState({ name: "", email: "", password: "", phone: "", address: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const set = (k: string) => (v: string) => setForm((f) => ({ ...f, [k]: v }));

  const submit = async () => {
    if (!form.name.trim() || !form.email.trim() || !form.password) {
      setError("Name, email and password are required");
      return;
    }
    const strong = form.password.length >= 8 && /[A-Z]/.test(form.password) && /[a-z]/.test(form.password) && /[0-9]/.test(form.password);
    if (!strong) {
      setError("Password must be 8+ characters with an uppercase, a lowercase and a number.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await signup({
        name: form.name,
        email: form.email.trim().toLowerCase(),
        password: form.password,
        phone: form.phone,
        address: form.address,
      });
      router.replace("/(app)");
    } catch (e: any) {
      setError(e.message || "Signup failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={styles.root}>
      <Header title="Create Account" back />
      <KeyboardAwareScrollView
        contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}
        bottomOffset={24}
        keyboardShouldPersistTaps="handled"
      >
        <Text style={styles.intro}>Sign up to view your service jobs and pay invoices online.</Text>
        <Field label="Full Name *" value={form.name} onChangeText={set("name")} placeholder="Your name" testID="signup-name-input" />
        <Field label="Email *" value={form.email} onChangeText={set("email")} placeholder="you@email.com" keyboardType="email-address" autoCapitalize="none" testID="signup-email-input" />
        <Field label="Password *" value={form.password} onChangeText={set("password")} placeholder="8+ chars, upper, lower & number" secureTextEntry testID="signup-password-input" />
        <Field label="Phone" value={form.phone} onChangeText={set("phone")} placeholder="480-555-0100" keyboardType="phone-pad" testID="signup-phone-input" />
        <Field label="Address" value={form.address} onChangeText={set("address")} placeholder="Street, City, State" testID="signup-address-input" />
        {error ? <Text style={styles.error} testID="signup-error">{error}</Text> : null}
        <View style={{ height: spacing.lg }} />
        <PrimaryButton title="Create Account" onPress={submit} loading={busy} testID="signup-submit-button" />
      </KeyboardAwareScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  intro: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted, marginBottom: spacing.lg },
  error: { color: colors.error, fontFamily: font.medium, fontSize: fontSize.base, marginTop: spacing.sm },
});
