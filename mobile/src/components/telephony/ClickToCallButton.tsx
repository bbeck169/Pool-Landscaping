/**
 * ClickToCallButton — Mobile parity for Phase 6B telephony.
 *
 * On mobile: primary action uses Linking.openURL('tel:…') for native dialer.
 * Also attempts POST /api/rc/call for RingCentral ring-out if the user has an RC seat.
 * Logs outbound via POST /api/rc/log-outbound for admin timeline.
 *
 * Props:
 *   - phoneNumber (string, required): E.164-preferred destination
 *   - entityKind (string, optional): "customer" | "lead" | "job" | "property" | "workstream"
 *   - entityId (string, optional): id of the parent record
 *   - label (string, optional): button label override
 *   - size ("sm" | "md", optional): visual density
 *   - showFallback (bool, optional): show secondary "Dial from device" link (default true)
 *   - testIdPrefix (string, optional): base for testID attrs
 */
import React, { useState } from "react";
import { View, Text, StyleSheet, TouchableOpacity, Linking, Alert } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { useAuth } from "@/src/auth";
import { api } from "@/src/api";
import { colors, font, fontSize, radius } from "@/src/theme";

type Props = {
  phoneNumber: string;
  entityKind?: string;
  entityId?: string;
  label?: string;
  size?: "sm" | "md";
  showFallback?: boolean;
  testIdPrefix?: string;
};

export default function ClickToCallButton({
  phoneNumber,
  entityKind,
  entityId,
  label = "Call",
  size = "md",
  showFallback = true,
  testIdPrefix = "click-to-call",
}: Props) {
  const { user } = useAuth();
  const [busy, setBusy] = useState(false);

  if (!phoneNumber) return null;

  const cleaned = String(phoneNumber).trim();
  const telUri = `tel:${cleaned.replace(/[^0-9+]/g, "")}`;

  const openDialer = () => {
    Linking.openURL(telUri).catch(() => {
      Alert.alert("Cannot dial", "Phone dialer is not available on this device.");
    });
  };

  const onCall = async () => {
    if (busy) return;
    setBusy(true);
    try {
      // Log outbound intent for admin timeline
      if (entityKind && entityId) {
        try {
          await api.post("/rc/log-outbound", {
            to_number: cleaned,
            from_number: (user as any)?.phone || "",
            entity_kind: entityKind,
            entity_id: entityId,
          });
        } catch {
          // Intent log failures are non-blocking
        }
      }

      // Attempt RC ring-out
      try {
        await api.post("/rc/call", { to_number: cleaned });
        // RC ring-out succeeded — call is placed via RingCentral
      } catch {
        // RC failed — fall back to native dialer
        openDialer();
      }
    } catch {
      openDialer();
    } finally {
      setBusy(false);
    }
  };

  const isSmall = size === "sm";

  return (
    <View style={s.wrap} testID={`${testIdPrefix}-wrap`}>
      <TouchableOpacity
        style={[s.btn, isSmall && s.btnSm]}
        onPress={onCall}
        disabled={busy}
        activeOpacity={0.7}
        testID={`${testIdPrefix}-button`}
      >
        <Ionicons
          name="call-outline"
          size={isSmall ? 12 : 14}
          color="#fff"
        />
        <Text style={[s.btnText, isSmall && s.btnTextSm]}>
          {busy ? "Calling…" : label}
        </Text>
      </TouchableOpacity>

      {showFallback && (
        <TouchableOpacity
          onPress={openDialer}
          style={s.fallback}
          testID={`${testIdPrefix}-tel-fallback`}
        >
          <Ionicons name="phone-portrait-outline" size={10} color={colors.muted} />
          <Text style={s.fallbackText}>Dial from this device</Text>
        </TouchableOpacity>
      )}
    </View>
  );
}

const s = StyleSheet.create({
  wrap: { gap: 4 },
  btn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: "#059669",
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: radius.md,
  },
  btnSm: {
    paddingHorizontal: 10,
    paddingVertical: 5,
  },
  btnText: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: "#fff",
  },
  btnTextSm: {
    fontSize: 11,
  },
  fallback: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
  },
  fallbackText: {
    fontFamily: font.regular,
    fontSize: 11,
    color: colors.muted,
    textDecorationLine: "underline",
  },
});
