/**
 * On My Way — SMS notification button (mobile parity).
 *
 * Two variants:
 *   • ``primary``  — prominent green CTA for "next job" at the header level.
 *   • ``compact``  — small inline button on each job card.
 *
 * Behaviour mirrors ``frontend/src/components/schedule/OnMyWayButton.jsx``:
 *   1. 4s geolocation timeout (expo-location). POST proceeds regardless.
 *   2. Success → Alert with ETA when present.
 *   3. Guard-hit → humanized Alert.
 *   4. Error → red Alert.
 *   5. 10s local disable after any request completes.
 */
import React, { useState, useCallback, useRef, useEffect } from "react";
import { Pressable, Text, StyleSheet, Alert, ActivityIndicator } from "react-native";
import * as Location from "expo-location";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api";
import { font, fontSize, spacing, radius } from "@/src/theme";

/* M2 hotfix — navy fill for "On my way" (was mint-green). */
const NAVY = "#1B1F5C";

const ALLOWED_ROLES = new Set(["technician", "manager", "admin", "super_admin"]);
const COOLDOWN_MS = 10_000;
const GEO_TIMEOUT_MS = 4_000;

function humanizeReason(reason: string): string {
  switch (reason) {
    case "already_sent_today":  return "Already notified this customer today";
    case "sms_opt_in_false":    return "Customer has opted out of SMS";
    case "customer_blocked":    return "Customer is blocked from communications";
    case "no_phone":            return "Customer has no phone on file";
    case "send_failed":         return "SMS send failed — try again in a moment";
    case "outbound_disabled":   return "SMS sending disabled for this environment";
    default:                    return "Could not send 'on my way' message";
  }
}

/** Best-effort 4s geolocation. Returns coords or null. */
async function geolocate(): Promise<{ origin_lat: number; origin_lng: number } | null> {
  try {
    const { status } = await Location.getForegroundPermissionsAsync();
    if (status === "undetermined") {
      const { status: newStatus } = await Location.requestForegroundPermissionsAsync();
      if (newStatus !== "granted") return null;
    } else if (status !== "granted") {
      return null;
    }

    const loc = await Promise.race<Location.LocationObject | null>([
      Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced }),
      new Promise<null>((resolve) => setTimeout(() => resolve(null), GEO_TIMEOUT_MS)),
    ]);
    if (!loc) return null;
    return { origin_lat: loc.coords.latitude, origin_lng: loc.coords.longitude };
  } catch {
    return null;
  }
}

interface Props {
  jobId: string;
  customerName?: string;
  variant?: "primary" | "compact";
  role?: string;
  disabled?: boolean;
  testID?: string;
}

export default function OnMyWayButton({
  jobId,
  customerName = "",
  variant = "compact",
  role = "",
  disabled: disabledProp = false,
  testID,
}: Props) {
  const [busy, setBusy] = useState(false);
  const [cooldown, setCooldown] = useState(false);
  const cooldownRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (cooldownRef.current) clearTimeout(cooldownRef.current);
    };
  }, []);

  const firstName = (customerName || "").split(" ")[0] || "customer";

  const send = useCallback(async () => {
    if (busy || cooldown || disabledProp || !jobId) return;
    setBusy(true);

    try {
      const coords = await geolocate();
      const body = coords || {};

      let resp: any;
      try {
        resp = await api.post(`/jobs/${jobId}/on-my-way`, body);
      } catch (e: any) {
        Alert.alert("Send failed", e?.message || "Couldn't reach the server — try again.");
        return;
      }

      if (resp?.sent) {
        const eta = resp.eta_minutes ? ` — ETA ${resp.eta_minutes} min` : "";
        Alert.alert("On my way", `Sent 'on my way' to ${firstName}${eta}`);
      } else {
        Alert.alert("Not sent", humanizeReason(resp?.reason));
      }
    } finally {
      setBusy(false);
      setCooldown(true);
      if (cooldownRef.current) clearTimeout(cooldownRef.current);
      cooldownRef.current = setTimeout(() => setCooldown(false), COOLDOWN_MS);
    }
  }, [busy, cooldown, disabledProp, jobId, firstName]);

  if (!ALLOWED_ROLES.has(role)) return null;

  const isDisabled = busy || cooldown || disabledProp;

  if (variant === "primary") {
    return (
      <Pressable
        onPress={send}
        disabled={isDisabled}
        style={[s.primaryBtn, isDisabled && s.btnDisabled]}
        testID={testID || "on-my-way-next-btn"}
      >
        {busy ? (
          <ActivityIndicator size="small" color="#fff" />
        ) : (
          <Ionicons name="send" size={16} color="#fff" />
        )}
        <Text style={s.primaryLabel}>
          {busy ? "Sending…" : cooldown ? "Sent · wait 10s" : "On my way — next job"}
        </Text>
      </Pressable>
    );
  }

  return (
    <Pressable
      onPress={(e: any) => { e?.stopPropagation?.(); send(); }}
      disabled={isDisabled}
      style={[s.compactBtn, isDisabled && s.compactBtnDisabled]}
      testID={testID || `on-my-way-btn-${jobId}`}
      hitSlop={6}
    >
      {busy ? (
        <ActivityIndicator size={10} color="#FFFFFF" />
      ) : (
        <Ionicons name="send" size={10} color="#FFFFFF" />
      )}
      <Text style={s.compactLabel}>
        {busy ? "Sending" : cooldown ? "Sent" : "On my way"}
      </Text>
    </Pressable>
  );
}

const s = StyleSheet.create({
  primaryBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.sm,
    height: 44,
    borderRadius: radius.md,
    backgroundColor: NAVY,
    marginBottom: spacing.sm,
  },
  primaryLabel: {
    fontFamily: font.bold,
    fontSize: fontSize.base,
    color: "#fff",
  },
  btnDisabled: {
    opacity: 0.55,
  },
  compactBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: radius.sm,
    backgroundColor: NAVY,
  },
  compactBtnDisabled: {
    opacity: 0.55,
  },
  compactLabel: {
    fontFamily: font.bold,
    fontSize: 10,
    color: "#FFFFFF",
  },
});
