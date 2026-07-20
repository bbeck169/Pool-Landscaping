import React from "react";
import { View } from "react-native";
import { Ionicons } from "@expo/vector-icons";

const ICONS: Record<string, { name: any; color: string }> = {
  google: { name: "globe-outline", color: "#4285F4" },
  facebook: { name: "logo-facebook", color: "#1877F2" },
  yelp: { name: "star", color: "#D32323" },
  bbb: { name: "shield-outline", color: "#005B9A" },
  custom: { name: "link-outline", color: "#6B7280" },
  private: { name: "lock-closed-outline", color: "#6B7280" },
};

/** Coloured platform icon for review lists / detail rows. */
export function PlatformIconNative({
  code,
  size = 14,
}: {
  code?: string;
  size?: number;
}) {
  const entry = ICONS[(code || "").toLowerCase()] || ICONS.custom;
  return (
    <View
      style={{ alignItems: "center", justifyContent: "center", width: size + 2 }}
    >
      <Ionicons name={entry.name} size={size} color={entry.color} />
    </View>
  );
}

export default PlatformIconNative;
