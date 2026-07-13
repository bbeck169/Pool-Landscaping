import React from "react";
import { View, Text, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { colors, spacing, font, fontSize } from "@/src/theme";

// react-native-maps (satellite) is native-only; web shows a placeholder.
export default function MeasureMap(_props: any) {
  return (
    <View style={styles.wrap}>
      <Ionicons name="earth-outline" size={30} color={colors.muted} />
      <Text style={styles.text}>
        The satellite measuring map opens in the mobile app.{"\n"}
        Open this screen on your device to tap points and measure distance & area.
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1, alignItems: "center", justifyContent: "center", padding: spacing.xl, gap: spacing.md, backgroundColor: "#0B1220" },
  text: { fontFamily: font.regular, fontSize: fontSize.base, color: "#94A3B8", textAlign: "center", lineHeight: 22 },
});
