/**
 * <CustomerLink> — tappable customer name that navigates to the
 * customer detail screen (`/customer/[id]`).
 *
 * Empty `customerId` → plain <Text>.
 */
import React, { useCallback } from "react";
import { Pressable, Text, StyleSheet, type TextStyle } from "react-native";
import { useRouter } from "expo-router";
import { colors } from "@/src/theme";

export interface CustomerLinkProps {
  customerId: string | null | undefined;
  name?: string | null;
  style?: TextStyle;
  children?: React.ReactNode;
  testID?: string;
}

export default function CustomerLink({ customerId, name, style, children, testID }: CustomerLinkProps) {
  const router = useRouter();
  const display = children || name || "Customer";

  const handlePress = useCallback(() => {
    if (!customerId) return;
    router.push(`/customer/${customerId}`);
  }, [customerId, router]);

  if (!customerId) {
    return <Text style={style} testID={testID}>{display}</Text>;
  }

  return (
    <Pressable
      onPress={handlePress}
      hitSlop={8}
      accessibilityLabel={typeof name === "string" ? name : "View customer"}
      accessibilityRole="link"
      testID={testID}
    >
      <Text style={[s.linkText, style]}>{display}</Text>
    </Pressable>
  );
}

const s = StyleSheet.create({
  linkText: { textDecorationLine: "underline", textDecorationColor: colors.brand, color: colors.brand },
});
