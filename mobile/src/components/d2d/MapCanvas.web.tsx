import React from "react";
import { View, Text, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { colors, spacing, font, fontSize } from "@/src/theme";

// react-native-maps is native-only; web shows a placeholder.
export default function MapCanvas(_props: any) {
  return (
    <View style={styles.wrap}>
      <Ionicons name="map-outline" size={28} color={colors.muted} />
      <Text style={styles.text}>Interactive map opens in the mobile app.{"\n"}Log doors below — they&apos;ll appear as pins on your device.</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1, alignItems: "center", justifyContent: "center", padding: spacing.lg, gap: spacing.sm },
  text: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, textAlign: "center", lineHeight: 20 },
});
