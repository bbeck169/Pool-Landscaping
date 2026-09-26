/**
 * ARPermissionGate — web stub.
 *
 * AR features require a native device. On web, show a placeholder
 * directing the user to the mobile app.
 */
import React from "react";
import { View, Text, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { colors, spacing, font, fontSize } from "@/src/theme";

interface Props {
  onGranted: () => void;
  placeholder?: React.ReactNode;
}

export default function ARPermissionGate(_props: Props) {
  return (
    <View style={styles.wrap} testID="ar-gate-web-stub">
      <Ionicons name="cube-outline" size={40} color={colors.arBlue} />
      <Text style={styles.title}>AR Ruler</Text>
      <Text style={styles.text}>
        AR measurement requires a physical device with a camera.{"\n"}
        Open this screen in the mobile app to use the AR Ruler.
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    padding: spacing.xl,
    gap: spacing.md,
    backgroundColor: colors.arNavy,
  },
  title: {
    fontFamily: font.bold,
    fontSize: 24,
    color: "#fff",
  },
  text: {
    fontFamily: font.regular,
    fontSize: fontSize.base,
    color: "rgba(255,255,255,0.6)",
    textAlign: "center",
    lineHeight: 22,
  },
});
