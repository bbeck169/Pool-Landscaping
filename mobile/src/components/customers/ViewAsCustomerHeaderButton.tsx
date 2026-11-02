/**
 * A2 · customer-profile header "View as customer" — opens the customer
 * portal in the in-app browser AS this customer; the admin's own mobile
 * session stays signed in. Reuses the shared TD-91 handler
 * (src/lib/portalViewAsCustomer.ts) — same endpoint, URL, fallback, toasts
 * as PortalAccessPanel's button.
 *
 * Gates mirror PortalAccessPanel exactly:
 *   - visible: role admin | super_admin AND has login        (panel :398 + :408)
 *   - disabled: in flight OR portal login inactive (revoked) (panel `!!busy || !active`)
 * Distinct from the neighbouring "Switch to customer view" (in-app session
 * swap), which is untouched.
 */
import React, { useState } from "react";
import { TouchableOpacity, Text, StyleProp, ViewStyle, TextStyle } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { useToast } from "@/src/components/ToastProvider";
import { viewAsCustomer } from "@/src/lib/portalViewAsCustomer";

type Props = {
  customerId: string;
  role?: string | null;
  hasLogin: boolean;
  active: boolean;
  style?: StyleProp<ViewStyle>;
  textStyle?: StyleProp<TextStyle>;
};

export default function ViewAsCustomerHeaderButton({ customerId, role, hasLogin, active, style, textStyle }: Props) {
  const { showToast } = useToast();
  const [busy, setBusy] = useState(false);
  if (!(role === "admin" || role === "super_admin") || !hasLogin) return null;
  const disabled = busy || !active;
  return (
    <TouchableOpacity
      style={[style, disabled && { opacity: 0.5 }]}
      onPress={() => viewAsCustomer(customerId, { setBusy, showToast })}
      disabled={disabled}
      testID="customer-action-view-as-customer"
      accessibilityRole="button"
      accessibilityLabel="View as customer"
      accessibilityHint="Opens the customer portal in the in-app browser. You stay signed in as yourself."
      accessibilityState={{ disabled, busy }}
    >
      <Ionicons name="eye-outline" size={16} color="#FFFFFF" />
      <Text style={[textStyle, { color: "#FFFFFF" }]}>{busy ? "Opening…" : "View as customer"}</Text>
    </TouchableOpacity>
  );
}
