/**
 * Phase P17.M · Interactive-Link Parity — ClickableName.
 *
 * Tappable entity name that navigates to the canonical detail route.
 * Mirrors web P14 `ClickableName.jsx`.
 *
 * Supported entityType routes:
 *   customer   → /customer/{id}
 *   technician → /technician/{id}
 *   user       → no route (plain text fallback)
 */
import React, { useCallback } from "react";
import { Pressable, Text, StyleSheet, type TextStyle } from "react-native";
import { useRouter } from "expo-router";
import { colors } from "@/src/theme";

const ROUTE_PREFIX: Record<string, string | null> = {
  customer: "/customer",
  technician: "/technician",
  user: null,
};

export interface ClickableNameProps {
  id?: string | null;
  name?: string | null;
  entityType?: "customer" | "technician" | "user";
  style?: TextStyle;
  testID?: string;
}

export default function ClickableName({
  id,
  name,
  entityType = "customer",
  style,
  testID,
}: ClickableNameProps) {
  const router = useRouter();
  const label = (name == null ? "" : String(name)).trim();
  const prefix = ROUTE_PREFIX[entityType] ?? null;

  const handlePress = useCallback(() => {
    if (!id || !prefix) return;
    router.push(`${prefix}/${id}` as any);
  }, [id, prefix, router]);

  if (!id || !label || !prefix) {
    return (
      <Text style={style} testID={testID}>
        {label || "—"}
      </Text>
    );
  }

  return (
    <Pressable
      onPress={handlePress}
      hitSlop={8}
      accessibilityLabel={`View ${label}`}
      accessibilityRole="link"
      testID={testID}
    >
      <Text style={[s.linkText, style]}>{label}</Text>
    </Pressable>
  );
}

const s = StyleSheet.create({
  linkText: {
    textDecorationLine: "underline",
    textDecorationColor: colors.brand,
    color: colors.brand,
  },
});
