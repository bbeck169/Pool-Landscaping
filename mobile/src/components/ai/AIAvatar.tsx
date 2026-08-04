/**
 * Phase 50 · Feb-2026 — Animated AI-employee avatar (mobile).
 * Uses ``lottie-react-native`` — Expo SDK 54 bundles the native module,
 * no dev-client rebuild required.
 */
import React from "react";
import { View, Image, StyleSheet } from "react-native";
import LottieView from "lottie-react-native";
import idle from "@/../assets/lottie/ai/idle.json";

export default function AIAvatar({ src, size = 64, testID }) {
  return (
    <View
      style={[styles.wrap, { width: size, height: size, borderRadius: size / 2 }]}
      testID={testID || "ai-lottie-avatar"}
    >
      <LottieView source={idle} autoPlay loop style={StyleSheet.absoluteFill} />
      {src ? (
        <Image
          source={{ uri: src }}
          style={[
            styles.img,
            { width: size * 0.64, height: size * 0.64, borderRadius: (size * 0.64) / 2 },
          ]}
        />
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { overflow: "hidden", position: "relative", alignItems: "center", justifyContent: "center" },
  img: { position: "absolute" },
});
