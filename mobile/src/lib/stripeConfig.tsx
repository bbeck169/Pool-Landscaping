/**
 * stripeConfig.tsx — Phase K23 · Central Stripe-not-configured fallback UI.
 *
 * Provides:
 *   - `StripeUnconfiguredNotice` — placeholder card when Stripe isn't wired.
 *   - Shared across portal + admin payment surfaces.
 */
import React from "react";
import { View, Text, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { spacing, radius, font, fontSize } from "@/src/theme";

/**
 * Neutral placeholder card rendered in place of card-capture UI
 * when the backend reports `stripe_configured === false` or the
 * publishable key is missing.
 */
export function StripeUnconfiguredNotice({
  style,
  message,
  testID,
}: {
  style?: any;
  message?: string;
  testID?: string;
}) {
  return (
    <View
      style={[s.container, style]}
      testID={testID || "stripe-unconfigured-notice"}
    >
      <View style={s.iconWrap}>
        <Ionicons name="alert-circle-outline" size={28} color="#B45309" />
      </View>
      <Text style={s.title}>Stripe payments not configured</Text>
      <Text style={s.message}>
        {message || "Contact support to enable card payments."}
      </Text>
    </View>
  );
}

/**
 * Compact inline variant for embedding inside tiles / cards.
 */
export function StripeUnconfiguredBanner({
  style,
  testID,
}: {
  style?: any;
  testID?: string;
}) {
  return (
    <View
      style={[s.banner, style]}
      testID={testID || "stripe-unconfigured-banner"}
    >
      <Ionicons name="alert-circle-outline" size={16} color="#B45309" />
      <Text style={s.bannerText}>
        Stripe not configured — card actions unavailable.
      </Text>
    </View>
  );
}

const s = StyleSheet.create({
  container: {
    alignItems: "center",
    justifyContent: "center",
    gap: 10,
    backgroundColor: "#FFFBEB",
    borderWidth: 1,
    borderColor: "#FDE68A",
    borderRadius: radius.lg,
    padding: spacing.xl,
    marginBottom: spacing.md,
  },
  iconWrap: {
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: "#FEF3C7",
    alignItems: "center",
    justifyContent: "center",
  },
  title: {
    fontFamily: font.semibold,
    fontSize: fontSize.base,
    color: "#92400E",
    textAlign: "center",
  },
  message: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: "#B45309",
    textAlign: "center",
    lineHeight: 20,
    paddingHorizontal: spacing.md,
  },
  banner: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    backgroundColor: "#FFFBEB",
    borderWidth: 1,
    borderColor: "#FDE68A",
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm + 2,
  },
  bannerText: {
    flex: 1,
    fontFamily: font.medium,
    fontSize: fontSize.sm,
    color: "#92400E",
    lineHeight: 18,
  },
});
