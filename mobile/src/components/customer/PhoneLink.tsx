/**
 * <PhoneLink> — tappable phone number that opens the device dialer.
 *
 * Normalizes input to `tel:+1XXXXXXXXXX` for US 10-digit numbers;
 * passes through E.164 with `+` for others.  Empty / invalid input
 * renders plain <Text> with no press handler.
 */
import React, { useCallback, useMemo } from "react";
import { Pressable, Text, Linking, StyleSheet, type TextStyle } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { colors } from "@/src/theme";

export interface PhoneLinkProps {
  phone: string | null | undefined;
  style?: TextStyle;
  children?: React.ReactNode;
  showIcon?: boolean;
  testID?: string;
}

function normalize(raw: string): string | null {
  if (!raw) return null;
  const digits = raw.replace(/\D/g, "");
  if (!digits) return null;
  // US 10-digit → +1XXXXXXXXXX
  if (digits.length === 10) return `+1${digits}`;
  // Already has country code (11+ digits starting with 1)
  if (digits.length === 11 && digits.startsWith("1")) return `+${digits}`;
  // Pass through with +
  return `+${digits}`;
}

export default function PhoneLink({ phone, style, children, showIcon = true, testID }: PhoneLinkProps) {
  const normalized = useMemo(() => normalize(phone || ""), [phone]);
  const formatted = phone?.trim() || "";

  const handlePress = useCallback(async () => {
    if (!normalized) return;
    try {
      await Linking.openURL(`tel:${normalized}`);
    } catch (e) {
      // eslint-disable-next-line no-console
      console.warn("[PhoneLink] Could not open dialer:", e);
    }
  }, [normalized]);

  if (!formatted) {
    return <Text style={style} testID={testID}>{children || "—"}</Text>;
  }

  if (!normalized) {
    return <Text style={style} testID={testID}>{children || formatted}</Text>;
  }

  return (
    <Pressable
      onPress={handlePress}
      hitSlop={8}
      accessibilityLabel={`Call ${formatted}`}
      accessibilityRole="link"
      style={s.row}
      testID={testID}
    >
      {showIcon ? <Ionicons name="call-outline" size={14} color={colors.brand} /> : null}
      <Text style={[s.linkText, style]}>{children || formatted}</Text>
    </Pressable>
  );
}

const s = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "center", gap: 4 },
  linkText: { textDecorationLine: "underline", textDecorationColor: colors.brand, color: colors.brand },
});
