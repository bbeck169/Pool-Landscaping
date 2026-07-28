import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Alert } from 'react-native';
import { Ionicons } from "@expo/vector-icons";
import * as WebBrowser from "expo-web-browser";
import { useFocusEffect } from "expo-router";
import Constants from "expo-constants";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import { Loading, PrimaryButton, Card } from "@/src/components/ui";

const BASE = process.env.EXPO_PUBLIC_BACKEND_URL || (Constants.expoConfig?.extra as any)?.backendUrl || "";

export default function PaymentMethod() {
  const [method, setMethod] = useState<{ has_method: boolean; label: string; type: string } | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setMethod(await api.get("/payments/method"));
    } catch {}
    setLoading(false);
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const addMethod = async () => {
    setBusy(true);
    try {
      const returnUrl = `${BASE}/portal/payment-method`;
      const { url, session_id } = await api.post("/payments/setup-session", { return_url: returnUrl });
      const res = await WebBrowser.openAuthSessionAsync(url, returnUrl);
      // Confirm regardless of how the browser closed (webhook may be absent in dev).
      if (session_id) {
        try {
          const s = await api.get(`/payments/setup-status/${session_id}`);
          if (s.saved) Alert.alert("Saved ✅", "Your payment method is now on file.");
        } catch {}
      }
      await load();
    } catch (e: any) {
      Alert.alert("Could not start setup", e.message);
    } finally {
      setBusy(false);
    }
  };

  if (loading) return <View style={styles.root}><Header title="Payment Method" back /><Loading /></View>;

  const has = method?.has_method;

  return (
    <View style={styles.root}>
      <Header title="Payment Method" back subtitle="Card or bank (ACH) on file" />
      <ScrollView contentContainerStyle={{ padding: spacing.lg }}>
        {!has ? (
          <View style={styles.banner}>
            <Ionicons name="alert-circle" size={20} color="#B45309" />
            <Text style={styles.bannerText}>A payment method on file is required so we can process your service payments automatically.</Text>
          </View>
        ) : null}

        <Card style={styles.methodCard}>
          <View style={[styles.iconWrap, { backgroundColor: has ? "#DCFCE7" : colors.surfaceSecondary }]}>
            <Ionicons name={method?.type === "ach" ? "business-outline" : "card-outline"} size={26} color={has ? colors.success : colors.muted} />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.methodTitle}>{has ? method?.label : "No payment method on file"}</Text>
            <Text style={styles.methodSub}>{has ? "Saved securely" : "Add a card or bank account to continue"}</Text>
          </View>
          {has ? <Ionicons name="checkmark-circle" size={22} color={colors.success} /> : null}
        </Card>

        <View style={{ height: spacing.lg }} />
        <PrimaryButton title={has ? "Update payment method" : "Add card or bank (ACH)"} icon="lock-closed" loading={busy} onPress={addMethod} testID="add-payment-method" />
        <Text style={styles.secure}>🔒 Payments are handled securely. We never store your card or bank details.</Text>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  banner: { flexDirection: "row", gap: spacing.sm, alignItems: "flex-start", backgroundColor: "#FFFBEB", borderWidth: 1, borderColor: "#FDE68A", borderRadius: radius.md, padding: spacing.md, marginBottom: spacing.lg },
  bannerText: { flex: 1, fontFamily: font.medium, fontSize: fontSize.sm, color: "#92400E", lineHeight: 19 },
  methodCard: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  iconWrap: { width: 48, height: 48, borderRadius: 24, alignItems: "center", justifyContent: "center" },
  methodTitle: { fontFamily: font.semibold, fontSize: fontSize.lg, color: colors.onSurface },
  methodSub: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
  secure: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, textAlign: "center", marginTop: spacing.lg, lineHeight: 18 },
});
