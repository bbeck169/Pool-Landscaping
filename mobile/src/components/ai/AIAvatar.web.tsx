/**
 * Phase Lottie-web · Feb-2026 — Web fallback for the animated AI avatar.
 *
 * The native ``AIAvatar.tsx`` renders a ``LottieView`` from
 * ``lottie-react-native``. That package's ``LottieView/index.web.tsx``
 * variant unconditionally imports ``@dotlottie/react-player`` — a
 * PEER dep that isn't installed here (adding it drags in wasm +
 * lottie-web + several MB of web bundle just to render an idle-loop
 * animation on the Expo web preview).
 *
 * Metro auto-resolves platform variants (``foo.web.tsx`` → web builds,
 * ``foo.tsx`` → native builds), so this file transparently replaces
 * the Lottie animation with a lightweight CSS-pulse fallback on web
 * WITHOUT touching the native mobile behavior. Phase 50's iOS/Android
 * Lottie avatars are unaffected.
 *
 * The rendered shape mirrors the native component so any parent that
 * measures the avatar's box size (Phase 50 chat header, admin bar)
 * doesn't reflow on the web preview.
 */
import React from "react";
import { Image, StyleSheet, View } from "react-native";

export default function AIAvatar({
  src,
  size = 64,
  testID,
}: {
  src?: string;
  size?: number;
  testID?: string;
}) {
  return (
    <View
      style={[
        styles.wrap,
        {
          width: size,
          height: size,
          borderRadius: size / 2,
          backgroundColor: "#E4E4E7",
        },
      ]}
      testID={testID || "ai-lottie-avatar"}
    >
      {src ? (
        <Image
          source={{ uri: src }}
          style={[
            styles.img,
            {
              width: size * 0.64,
              height: size * 0.64,
              borderRadius: (size * 0.64) / 2,
            },
          ]}
        />
      ) : (
        // Ambient pulse — no animation library, just a soft solid
        // dot so the avatar box isn't empty on the web preview.
        <View
          style={{
            width: size * 0.48,
            height: size * 0.48,
            borderRadius: (size * 0.48) / 2,
            backgroundColor: "#71717A",
            opacity: 0.7,
          }}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    overflow: "hidden",
    position: "relative",
    alignItems: "center",
    justifyContent: "center",
  },
  img: { position: "absolute" },
});
