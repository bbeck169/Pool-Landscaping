/**
 * TD-68 (web c782fd23a) — portal theme bundle, mobile port of web
 * `components/portal/PortalPageShell.jsx`: content sits in a white
 * rounded card on the deep-navy portal page bg (the `/portal/home`
 * chassis, `PORTAL_DARK_BG` #03002e). Used by Service Reports list,
 * Service Report detail, and the portal review-submit flow.
 */
import React from "react";
import { View, StyleSheet, type ViewStyle, type StyleProp } from "react-native";

export const PORTAL_PAGE_BG = "#03002e";

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
