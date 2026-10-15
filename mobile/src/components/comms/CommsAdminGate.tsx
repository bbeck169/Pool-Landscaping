/**
 * Comms admin gate — P2 #11 mobile parity (web 965fb3c69 / d34aec4e5).
 *
 * Every /api/comms/* template route is behind backend `_require_admin`
 * (role ∈ {admin, super_admin}); web wraps the same pages in
 * `<AdminOnly>` with the identical pair. Owner / manager / techs would
 * only ever get 403s, so the whole surface is hidden for them.
 *
 * NOTE: the 4-role set admin/super_admin/owner/manager is the backend's
 * test-send RECIPIENT allow-list — not the caller gate. Don't widen this.
 */
import React from "react";
import { View, Text, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { useAuth } from "@/src/auth";
import { Header } from "@/src/components/widgets";
import { colors, font, fontSize, spacing } from "@/src/theme";

export const COMMS_ADMIN_ROLES = ["admin", "super_admin"] as const;

// Marketing Forms + submissions inbox ONLY (backend `require_admin` admits
// owner). Email Builder / comms templates keep the default COMMS_ADMIN_ROLES.
export const MARKETING_FORMS_ROLES = ["admin", "super_admin", "owner"] as const;

export function isCommsAdmin(role?: string | null, roles: readonly string[] = COMMS_ADMIN_ROLES): boolean {
  return roles.includes(String(role || ""));
}

export default function CommsAdminGate({
  title,
  roles,
  children,
}: {
  title: string;
  roles?: readonly string[];
  children: React.ReactNode;
}) {
  const { user } = useAuth();
  if (isCommsAdmin(user?.role, roles)) return <>{children}</>;
  return (
    <View style={s.root} testID="comms-admin-gate-denied">
      <Header title={title} back />
      <View style={s.body}>
        <Ionicons name="lock-closed-outline" size={32} color={colors.muted} />
        <Text style={s.text}>Admin access required</Text>
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  body: { alignItems: "center", paddingTop: 60, gap: spacing.sm },
  text: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.muted },
});
