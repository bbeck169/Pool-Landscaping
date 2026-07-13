import React from "react";
import { View, Text, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { PrimaryButton } from "@/src/components/ui";

export default function PaymentComplete() {
  const router = useRouter();
  return (
    <View style={styles.root}>
      <View style={styles.iconWrap}>
        <Ionicons name="checkmark-circle" size={72} color={colors.success} />
      </View>
      <Text style={styles.title}>Payment complete</Text>
      <Text style={styles.sub}>You can close this window and return to the app. Your invoice will update automatically.</Text>
      <View style={{ height: spacing.xl }} />
      <PrimaryButton title="Back to Invoices" onPress={() => router.replace("/(app)/quotes")} testID="payment-complete-back" />
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary, alignItems: "center", justifyContent: "center", padding: spacing.xl },
  iconWrap: { width: 110, height: 110, borderRadius: 55, backgroundColor: colors.success + "1A", alignItems: "center", justifyContent: "center", marginBottom: spacing.lg },
  title: { fontFamily: font.bold, fontSize: fontSize["2xl"], color: colors.onSurface },
  sub: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted, textAlign: "center", marginTop: spacing.sm, lineHeight: 22 },
});
