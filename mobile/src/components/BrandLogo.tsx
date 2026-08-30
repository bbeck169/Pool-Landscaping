/**
 * BrandLogo — renders the tenant logo or the bundled default.
 *
 * Props:
 *   size?: "sm" | "md" | "lg" (default "md")
 *   variant?: "full" | "icon" (default "full")
 *   onPress?: () => void
 *
 * Falls back to the bundled asset on error / while loading / when
 * the tenant has no custom logo.
 */
import React, { useState, useCallback } from "react";
import { Image, Pressable, StyleSheet } from "react-native";
import { useRouter } from "expo-router";
import { useTenantBrand } from "@/src/hooks/useTenantBrand";

const DEFAULT_FULL = require("@/assets/brand/logo.png");
const DEFAULT_ICON = require("@/assets/brand/logo-icon.png");

const SIZES = {
  sm: { full: { width: 100, height: 24 }, icon: { width: 24, height: 24 } },
  md: { full: { width: 140, height: 36 }, icon: { width: 36, height: 36 } },
  lg: { full: { width: 200, height: 48 }, icon: { width: 48, height: 48 } },
};

type Props = {
  size?: "sm" | "md" | "lg";
  variant?: "full" | "icon";
  /** Tap handler. Pass explicitly to enable tap; omit to render non-interactive. */
  onPress?: (() => void) | null;
  testID?: string;
};

export default function BrandLogo({ size = "md", variant = "full", onPress, testID }: Props) {
  const { logoUrl } = useTenantBrand();
  const router = useRouter();
  const [errored, setErrored] = useState(false);

  const dims = SIZES[size][variant];
  const defaultAsset = variant === "icon" ? DEFAULT_ICON : DEFAULT_FULL;

  const handleError = useCallback(() => {
    setErrored(true);
  }, []);

  // Use tenant URL when available, valid, and not errored.
  const useTenantUrl = !!logoUrl && !errored;

  const img = (
    <Image
      source={useTenantUrl ? { uri: logoUrl } : defaultAsset}
      style={[s.image, dims]}
      resizeMode="contain"
      onError={handleError}
      testID={testID || "brand-logo-img"}
      accessibilityLabel="Brand logo"
    />
  );

  // When onPress is explicitly null, render non-interactive.
  if (onPress === null) return img;

  const handlePress = onPress || (() => router.push("/(app)"));

  return (
    <Pressable
      onPress={handlePress}
      hitSlop={8}
      style={s.pressable}
      accessibilityRole="button"
      accessibilityLabel="Home"
      testID="brand-logo-pressable"
    >
      {img}
    </Pressable>
  );
}

const s = StyleSheet.create({
  pressable: {
    alignItems: "center",
    justifyContent: "center",
  },
  image: {
    // Dimensions set inline via the size prop.
  },
});
