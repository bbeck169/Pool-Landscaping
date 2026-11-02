/**
 * TD-68 (web c782fd23a) — portal theme bundle, mobile port of web
 * `components/portal/PortalPageShell.jsx`: content sits in a white
 * rounded card on the portal page bg. Used by Service Reports list,
 * Service Report detail, the portal review-submit flow, and the
 * /portal/home page root.
 *
 * Nov-2026 · full-light portal page (operator pick b, mobile-only): the
 * page bg moves from navy #03002e to colors.surfaceSecondary #F4F4F5, the
 * same light page as every other portal screen (invoices, appointments…).
 * No dark mode. Card unchanged (white + border + soft shadow).
 */
import React from "react";
import { View, StyleSheet, type ViewStyle, type StyleProp } from "react-native";

import { colors } from "@/src/theme";

export const PORTAL_PAGE_BG = colors.surfaceSecondary; // #F4F4F5

export const portalShellCard: ViewStyle = {
  backgroundColor: "#FFFFFF",
  borderRadius: 24,
  borderWidth: 1,
  borderColor: "#E5E7EB",
  padding: 20,
  shadowColor: "#000",
  shadowOpacity: 0.18,
  shadowRadius: 16,
  shadowOffset: { width: 0, height: 8 },
  elevation: 6,
};

export default function PortalPageShell({
  children,
  style,
  testID = "portal-page-shell-card",
}: {
  children: React.ReactNode;
  style?: StyleProp<ViewStyle>;
  testID?: string;
}) {
  return (
    <View style={[styles.card, style]} testID={testID}>
      {children}
    </View>
  );
}

const styles = StyleSheet.create({ card: portalShellCard });
