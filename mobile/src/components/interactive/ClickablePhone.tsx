/**
 * Phase P17.M · Interactive-Link Parity — ClickablePhone.
 *
 * Tappable phone number that opens the device dialer.
 * Thin re-export of the existing PhoneLink with P14-compatible API.
 * Mirrors web P14 `ClickablePhone.jsx`.
 */
import React from "react";
import type { TextStyle } from "react-native";
import PhoneLink from "@/src/components/customer/PhoneLink";

export interface ClickablePhoneProps {
  phone?: string | null;
  style?: TextStyle;
  showIcon?: boolean;
  testID?: string;
}

export default function ClickablePhone({
  phone,
  style,
  showIcon = true,
  testID,
}: ClickablePhoneProps) {
  return (
    <PhoneLink
      phone={phone}
      style={style}
      showIcon={showIcon}
      testID={testID}
    />
  );
}
