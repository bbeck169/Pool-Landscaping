/**
 * Phase 3b · Feb-2026 — orange "Navigate" (Google Maps) button for the
 * schedule card action row. Mobile mirror of web
 * `frontend/src/components/schedule/NavigateMapsButton.jsx` (dba72cd1a).
 *
 * Address priority: `service_address` → `address` → disabled.
 * Mobile tap behaviour (differs from web's new-tab):
 *   1. Native Google Maps turn-by-turn: `google.navigation:q=<addr>`
 *      (Android; iOS only if the scheme is resolvable).
 *   2. Fallback: universal web URL
 *      `https://www.google.com/maps/dir/?api=1&destination=<addr>`
 *      (opens Google Maps app via universal link if installed, else browser).
 */
import React from "react";
import { Pressable, Text, StyleSheet, Linking, Platform } from "react-native";
import { Ionicons } from "@expo/vector-icons";

export const NAVIGATE_BG = "#F97316";         // orange-500
export const NAVIGATE_BG_PRESSED = "#EA580C"; // orange-600

export function resolveNavigateAddress(job: any): string {
  if (!job || typeof job !== "object") return "";
  const svc = typeof job.service_address === "string" ? job.service_address.trim() : "";
  if (svc) return svc;
  const addr = typeof job.address === "string" ? job.address.trim() : "";
  return addr || "";
}

export const nativeNavUrl = (address: string) => `google.navigation:q=${encodeURIComponent(address)}`;
export const webDirectionsUrl = (address: string) =>
  `https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(address)}`;

export async function openNavigation(address: string): Promise<"native" | "web" | "failed"> {
  if (!address) return "failed";
  const native = nativeNavUrl(address);
  try {
    // Android 11+ package visibility makes canOpenURL() report false for
    // custom schemes without a <queries> manifest entry — so just try it
    // and fall back on throw. iOS: probe (no handler → universal link).
    if (Platform.OS === "android" || (await Linking.canOpenURL(native))) {
      await Linking.openURL(native);
      return "native";
    }
  } catch {
    // fall through to web URL
  }
  try {
    await Linking.openURL(webDirectionsUrl(address));
    return "web";
  } catch {
    return "failed";
  }
}

export default function NavigateMapsButton({ job }: { job: any }) {
  const address = resolveNavigateAddress(job);
  const disabled = !address;
  const label = disabled ? "No address on file" : `Navigate to ${job?.customer_name || "customer"}`;
  return (
    <Pressable
      onPress={disabled ? undefined : () => { openNavigation(address); }}
      disabled={disabled}
      hitSlop={4}
      style={({ pressed }) => [s.btn, pressed && !disabled && s.btnPressed, disabled && s.btnDisabled]}
      testID={`schedule-card-navigate-${job?.id ?? "unknown"}`}
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityState={{ disabled }}
    >
      <Ionicons name="navigate" size={12} color="#FFFFFF" />
      <Text style={s.text}>Navigate</Text>
    </Pressable>
  );
}

const s = StyleSheet.create({
  btn: {
    flexDirection: "row", alignItems: "center", alignSelf: "flex-start", gap: 4,
    backgroundColor: NAVIGATE_BG, borderColor: NAVIGATE_BG_PRESSED, borderWidth: 1,
    paddingHorizontal: 10, paddingVertical: 6, borderRadius: 6, marginTop: 6, minHeight: 32,
  },
  btnPressed: { backgroundColor: NAVIGATE_BG_PRESSED },
  btnDisabled: { opacity: 0.5 },
  text: { color: "#FFFFFF", fontSize: 12, fontWeight: "700" },
});
