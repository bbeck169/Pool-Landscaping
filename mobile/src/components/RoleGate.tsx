// Phase 16 · Feb-2026 — shared role-gate helper for mobile screens.
//
// The backend actually issues roles from a broader set than the local
// User type (`admin` | `technician` | `customer`) advertises. This
// helper accepts the raw role string and returns a normalized flag set
// so screens can gate consistently without duplicating the string list.
//
// Nav-visibility helpers should use `isDispatcherPlus()` / `isAdminPlus()`
// to hide entry points; a full screen guard should use the `<RoleGate>`
// component so a deep-link request lands on a friendly "Not authorized"
// state instead of a crash.
import React from "react";
import { View, Text, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { useAuth } from "@/src/auth";

const DISPATCHER_PLUS = new Set([
  "admin",
  "super_admin",
  "manager",
  "dispatcher",
]);
const ADMIN_PLUS = new Set(["admin", "super_admin", "manager"]);
const STRICT_ADMIN = new Set(["admin", "super_admin"]);

function _role(user: any): string {
  return String(user?.role || "").toLowerCase();
}

export function isDispatcherPlus(user: any): boolean {
  return DISPATCHER_PLUS.has(_role(user));
}

export function isAdminPlus(user: any): boolean {
  return ADMIN_PLUS.has(_role(user));
}

export function isStrictAdmin(user: any): boolean {
  return STRICT_ADMIN.has(_role(user));
}

export function isCustomer(user: any): boolean {
  return _role(user) === "customer";
}

export function isTech(user: any): boolean {
  return _role(user) === "technician" || _role(user) === "tech";
}

export type GateLevel = "dispatcher_plus" | "admin_plus" | "strict_admin";

export function RoleGate({
  level,
  children,
  testID,
}: {
  level: GateLevel;
  children: React.ReactNode;
  testID?: string;
}) {
  const { user } = useAuth();
  let ok = false;
  if (level === "dispatcher_plus") ok = isDispatcherPlus(user);
  else if (level === "admin_plus") ok = isAdminPlus(user);
  else if (level === "strict_admin") ok = isStrictAdmin(user);

  if (ok) return <>{children}</>;

  return (
    <View style={styles.wrap} testID={testID || "role-gate-blocked"}>
      <Ionicons name="lock-closed-outline" size={44} color={colors.muted} />
      <Text style={styles.title}>Not authorized</Text>
      <Text style={styles.sub}>
        This section is available only to{" "}
        {level === "strict_admin"
          ? "administrators"
          : level === "admin_plus"
          ? "managers and administrators"
          : "dispatchers and above"}
        . Please contact your account owner if you believe you should have
        access.
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    padding: spacing.xl,
    gap: spacing.md,
  },
  title: {
    fontFamily: font.bold,
    fontSize: fontSize.xl,
    color: colors.onSurface,
  },
  sub: {
    fontFamily: font.regular,
    fontSize: fontSize.base,
    color: colors.muted,
    textAlign: "center",
    lineHeight: 20,
  },
});
