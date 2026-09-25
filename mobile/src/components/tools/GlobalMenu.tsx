/**
 * Phase 43 · Global dropdown menu.
 *
 * A hamburger trigger pinned to the top-left of every `(app)` screen
 * plus a full-width sheet that slides down from below the header when
 * the trigger is tapped. Inside the sheet: the same
 * SearchBar/PinnedRow/RecentRow/CategoryChips/sections composition
 * the Tools tab renders (via `<ToolsMenuBody variant="sheet" />`).
 *
 * Suppressed for the customer role — they're already redirected to
 * `/portal/home` in the layout, but we double-guard here so future
 * refactors can't accidentally expose the staff menu.
 *
 * Close paths:
 *   - backdrop tap                       (`mobile-menu-backdrop`)
 *   - top-right X                        (`mobile-menu-close`)
 *   - hardware back                      (`Modal onRequestClose`)
 *   - picking a tool                     (`onNavigate` closes then
 *                                          `setTimeout(push, 0)`)
 *
 * The trigger is absolutely-positioned so no existing screen's Header
 * layout needs to change — this ships without touching any of the
 * ~30 `(app)/*.tsx` files.
 */
import React, { useState, useEffect } from "react";
import {
  View, Modal, Pressable, StyleSheet, Text, Alert, Platform,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { useAuth } from "@/src/auth";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { ToolsMenuBody } from "./ToolsMenuBody";
import type { ToolCardTile } from "./ToolCard";

/* ── Module-level open trigger ──────────────────────────────────────
 * The hamburger button now lives inside the shared Header (widgets.tsx).
 * It calls `openGlobalMenu()` which sets the open state via the
 * setter registered by the mounted GlobalMenu component.
 */
let _openSetter: ((v: boolean) => void) | null = null;
export function openGlobalMenu() {
  _openSetter?.(true);
}

export const GlobalMenu: React.FC = () => {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const [open, setOpen] = useState(false);

  // Register the setter so the module-level `openGlobalMenu` can reach it.
  useEffect(() => {
    _openSetter = setOpen;
    return () => { _openSetter = null; };
  }, []);
  // Phase 44 · Fix 2 — cross-platform logout confirmation state. On
  // native we lean on `Alert.alert()`; on RN-Web `Alert.alert()` is a
  // no-op, so we surface an in-sheet inline confirm banner using the
  // same visual language as the rest of the sheet.
  const [confirmingLogout, setConfirmingLogout] = useState(false);
  const { user, logout } = useAuth();
  const role = (user?.role as string) || "";
  // Staff-only surface. Customers keep their portal nav; not-yet-loaded
  // users don't need a menu either.
  const allowed = role === "admin" || role === "super_admin" || role === "technician";
  if (!allowed) return null;

  const handleNavigate = (t: ToolCardTile) => {
    setOpen(false);
    // Wait a tick so the slide-down animation gets to start unwinding
    // before the router unmounts the current screen — otherwise the
    // sheet snaps out abruptly on Android.
    setTimeout(() => { router.push(t.route as any); }, 60);
  };

  /**
   * Phase 44 · Fix 2 — cross-platform logout confirmation.
   *
   * `react-native`'s `Alert.alert` doesn't render on RN-Web (verified
   * in the e1_tester report — button tap did nothing because the
   * Alert never appeared). Solution: on web we flip an inline
   * in-sheet confirm banner; on native we keep the native
   * `Alert.alert` prompt (better platform integration + haptics).
   * Both paths converge on the same `performLogout()` action.
   */
  const performLogout = async () => {
    setConfirmingLogout(false);
    setOpen(false);
    try { await logout(); }
    catch { /* best-effort — clearing local session is what matters */ }
  };

  const doLogout = () => {
    // Phase 30.4 · Feb-2026 — always use the inline in-sheet confirm.
    // Previously the native branch used ``Alert.alert(...)`` which
    // silently no-ops on some Android/Expo Go builds (root cause of
    // the Phase 30.3 portal sign-out P0). The inline UI below
    // renders unconditionally, so this control is now guaranteed to
    // show a confirmation regardless of platform.
    setConfirmingLogout(true);
  };

  return (
    <>
      {/* Trigger removed — now rendered inside Header (widgets.tsx).
          The module-level openGlobalMenu() bridges the two. */}

      <Modal
        visible={open}
        animationType="slide"
        transparent
        onRequestClose={() => setOpen(false)}
      >
        <Pressable
          style={styles.backdrop}
          testID="mobile-menu-backdrop"
          onPress={() => setOpen(false)}
          accessibilityLabel="Close menu"
        />
        <View
          style={[styles.sheet, { paddingTop: insets.top }]}
          testID="mobile-menu-sheet"
        >
          <View style={styles.sheetHeader}>
            <Text style={styles.sheetTitle}>Menu</Text>
            <Pressable
              onPress={() => setOpen(false)}
              testID="mobile-menu-close"
              hitSlop={10}
              accessibilityLabel="Close menu"
            >
              <Ionicons name="close" size={24} color={colors.onSurface} />
            </Pressable>
          </View>
          <ToolsMenuBody variant="sheet" onNavigate={handleNavigate} quickAccessRole={role} />
          {/* Phase 44 · logout entry — divider above + destructive tint.
              Sits pinned at the bottom of the sheet so techs always find
              it after search + tools regardless of scroll position. On
              web the confirm is inline (Alert.alert is a no-op on
              RN-Web); on native we surface the native Alert. */}
          <View style={styles.logoutWrap}>
            {confirmingLogout ? (
              <View testID="mobile-menu-logout-confirm-inline" style={styles.logoutConfirmWrap}>
                <Text style={styles.logoutConfirmTitle}>Log out?</Text>
                <Text style={styles.logoutConfirmDesc}>You&apos;ll need to sign in again.</Text>
                <View style={styles.logoutConfirmRow}>
                  <Pressable
                    onPress={() => setConfirmingLogout(false)}
                    style={styles.logoutCancelBtn}
                    testID="mobile-menu-logout-cancel"
                    accessibilityRole="button"
                    accessibilityLabel="Cancel logout"
                  >
                    <Text style={styles.logoutCancelText}>Cancel</Text>
                  </Pressable>
                  <Pressable
                    onPress={performLogout}
                    style={styles.logoutConfirmBtn}
                    testID="mobile-menu-logout-confirm"
                    accessibilityRole="button"
                    accessibilityLabel="Confirm logout"
                  >
                    <Ionicons name="log-out-outline" size={16} color="#FFFFFF" />
                    <Text style={styles.logoutConfirmText}>Log out</Text>
                  </Pressable>
                </View>
              </View>
            ) : (
              <Pressable
                onPress={doLogout}
                style={styles.logoutBtn}
                testID="mobile-menu-logout"
                accessibilityRole="button"
                accessibilityLabel="Log out"
              >
                <Ionicons name="log-out-outline" size={18} color={colors.error} />
                <Text style={styles.logoutText}>Log out</Text>
              </Pressable>
            )}
          </View>
        </View>
      </Modal>
    </>
  );
};

const styles = StyleSheet.create({
  backdrop: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: "rgba(0,0,0,0.45)",
  },
  sheet: {
    position: "absolute",
    top: 0, left: 0, right: 0,
    // Cover ~92% of the screen from the top so tapping the exposed
    // strip at the bottom triggers the backdrop close.
    bottom: "8%",
    backgroundColor: colors.surface,
    borderBottomLeftRadius: radius.lg,
    borderBottomRightRadius: radius.lg,
    ...(Platform.OS === "web"
      ? { boxShadow: "0 8px 24px rgba(0,0,0,0.18)" as any }
      : { elevation: 12 }),
  },
  sheetHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  sheetTitle: {
    fontFamily: font.semibold,
    fontSize: fontSize.lg,
    color: colors.onSurface,
  },
  logoutWrap: {
    borderTopWidth: 1,
    borderTopColor: colors.border,
    padding: spacing.md,
    backgroundColor: colors.surface,
  },
  logoutBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.sm,
    paddingVertical: 12,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.error,
    backgroundColor: "#FEF2F2",
  },
  logoutText: {
    fontFamily: font.semibold,
    fontSize: fontSize.base,
    color: colors.error,
  },
  logoutConfirmWrap: {
    borderWidth: 1,
    borderColor: colors.error,
    backgroundColor: "#FEF2F2",
    borderRadius: radius.md,
    padding: spacing.md,
    gap: spacing.sm,
  },
  logoutConfirmTitle: {
    fontFamily: font.semibold,
    fontSize: fontSize.base,
    color: colors.onSurface,
  },
  logoutConfirmDesc: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
  },
  logoutConfirmRow: {
    flexDirection: "row",
    gap: spacing.sm,
    marginTop: spacing.sm,
  },
  logoutCancelBtn: {
    flex: 1,
    paddingVertical: 10,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: "center",
    justifyContent: "center",
  },
  logoutCancelText: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.onSurface,
  },
  logoutConfirmBtn: {
    flex: 1,
    flexDirection: "row",
    gap: 6,
    paddingVertical: 10,
    borderRadius: radius.md,
    backgroundColor: colors.error,
    alignItems: "center",
    justifyContent: "center",
  },
  logoutConfirmText: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: "#FFFFFF",
  },
});
