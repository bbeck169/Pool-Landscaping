import React from "react";
import { Image } from "expo-image";

const SIZES = {
  sm: { height: 40 },
  md: { height: 80 },
  lg: { height: 140 },
} as const;

type BrandLogoProps = {
  size?: "sm" | "md" | "lg";
  testID?: string;
};

export default function BrandLogo({ size = "md", testID }: BrandLogoProps) {
  return (
    <Image
      source={require("../../assets/logo-full.png")}
      style={{ height: SIZES[size].height, width: "100%" }}
      contentFit="contain"
      accessibilityLabel="Pool & Landscaping of Vistancia"
      testID={testID || `brand-logo-${size}`}
    />
  );
}
