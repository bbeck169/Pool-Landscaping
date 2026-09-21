/**
 * Phase P17.M · Interactive-Link Parity — ClickableAddress.
 *
 * Tappable address that opens the OS maps app.
 * Thin re-export of the existing AddressLink with P14-compatible API.
 * Mirrors web P14 `ClickableAddress.jsx`.
 */
import React from "react";
import type { TextStyle } from "react-native";
import AddressLink from "@/src/components/customer/AddressLink";
import type { AddressObject } from "@/src/components/customer/AddressLink";

export interface ClickableAddressProps {
  address?: string | AddressObject | null;
  style?: TextStyle;
  showIcon?: boolean;
  testID?: string;
}

export default function ClickableAddress({
  address,
  style,
  showIcon = true,
  testID,
}: ClickableAddressProps) {
  return (
    <AddressLink
      address={address}
      style={style}
      showIcon={showIcon}
      testID={testID}
    />
  );
}
