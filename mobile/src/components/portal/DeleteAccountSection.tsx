/**
 * Feb-2026 · P11b — Mobile delete-account danger section.
 *
 * App Store consumer-account guideline blocker item 3.  Mirrors the
 * web ``DeleteAccountDangerCard``:
 *
 *   1. Danger button at the bottom of the customer portal profile.
 *   2. Modal opens on tap with single-click Confirm (typed-confirm
 *      friction removed app-wide per Feb-2026 UX simplification).
 *   3. On confirm the component fires
 *      ``DELETE /api/customer-portal/account``, clears
 *      AsyncStorage, and navigates back to the public landing
 *      screen.
 *
 * Uses a bottom-sheet-style ``Modal`` instead of ``Alert.alert``
 * because Android's Alert has no inline ``TextInput`` support.
 */
import React, { useState } from "react";
import {
  View, Text, StyleSheet, Pressable, Modal,
  ActivityIndicator, Alert,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { router } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";

type Props = {
  onDeleted?: () => void;
};


export default function DeleteAccountSection({ onDeleted }: Props) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string>("");

  const close = () => {
    if (busy) return;
    setOpen(false);
    setErr("");
  };

  const onConfirm = async () => {
    if (busy) return;
    setBusy(true);
    setErr("");
    try {
      await api.delete("/customer-portal/account");
      try { await AsyncStorage.clear(); } catch (_e) { /* best effort */ }
      try { onDeleted && onDeleted(); } catch (_e) { /* best effort */ }
      Alert.alert("Account deleted",
        "Your account has been deleted. Your service history stays on file with your provider, but your personal details have been removed.");
      try { router.replace("/"); } catch (_e) { /* best effort */ }
    } catch (e: any) {
      setErr(e?.message || "Something went wrong. Please try again.");
      setBusy(false);
    }
  };

  return (
    <View style={styles.section} testID="portal-profile-delete-account-section">
      <View style={styles.headerRow}>
        <Ionicons name="warning-outline" size={16} color={colors.error} />
        <Text style={styles.header}>Delete my account</Text>
      </View>
      <Text style={styles.body}>
        Deleting your account will anonymize your profile. Your service
        history stays on file for your provider, but your name, email,
        phone, and address will be permanently removed. This cannot be
        undone.
      </Text>
      <Pressable
        style={styles.openBtn}
        onPress={() => setOpen(true)}
        testID="portal-profile-delete-account-open-btn"
      >
        <Text style={styles.openBtnText}>Delete My Account</Text>
      </Pressable>

      <Modal
        visible={open}
        transparent
        animationType="fade"
        onRequestClose={close}
      >
        <View style={styles.backdrop}>
          <View
            style={styles.card}
            testID="portal-profile-delete-account-modal"
          >
            <Text style={styles.modalTitle}>Confirm deletion</Text>
            <Text style={styles.modalBody}>
              This will permanently delete your account. Are you sure?
            </Text>
            {err ? (
              <Text
                style={styles.error}
                testID="portal-profile-delete-account-error"
              >
                {err}
              </Text>
            ) : null}
            <View style={styles.actions}>
              <Pressable
                style={styles.cancelBtn}
                onPress={close}
                testID="portal-profile-delete-account-cancel-btn"
              >
                <Text style={styles.cancelText}>Cancel</Text>
              </Pressable>
              <Pressable
                style={[styles.confirmBtn, busy && styles.confirmBtnDisabled]}
                disabled={busy}
                onPress={onConfirm}
                testID="portal-profile-delete-account-confirm-btn"
              >
                {busy ? (
                  <ActivityIndicator color="#fff" />
                ) : (
                  <Text style={styles.confirmText}>Delete forever</Text>
                )}
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>
    </View>
  );
}


const styles = StyleSheet.create({
  section: {
    marginTop: spacing.xl,
    padding: spacing.lg,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.error,
    backgroundColor: colors.surface,
  },
  headerRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
  },
  header: {
    fontFamily: font.bold,
    fontSize: fontSize.base,
    color: colors.error,
  },
  body: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.onSurface,
    marginTop: spacing.sm,
    lineHeight: 20,
  },
  openBtn: {
    marginTop: spacing.md,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    borderRadius: radius.md,
    backgroundColor: colors.error,
    alignSelf: "flex-start",
  },
  openBtnText: {
    fontFamily: font.bold,
    fontSize: fontSize.base,
    color: "#fff",
  },
  backdrop: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.5)",
    justifyContent: "center",
    alignItems: "center",
    padding: spacing.lg,
  },
  card: {
    width: "100%",
    maxWidth: 400,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
    padding: spacing.lg,
  },
  modalTitle: {
    fontFamily: font.bold,
    fontSize: fontSize.lg,
    color: colors.error,
  },
  modalBody: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.onSurface,
    marginTop: spacing.sm,
    lineHeight: 20,
  },
  error: {
    marginTop: spacing.sm,
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.error,
  },
  actions: {
    marginTop: spacing.lg,
    flexDirection: "row",
    justifyContent: "flex-end",
    gap: spacing.md,
  },
  cancelBtn: {
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    borderRadius: radius.md,
  },
  cancelText: {
    fontFamily: font.semibold,
    fontSize: fontSize.base,
    color: colors.muted,
  },
  confirmBtn: {
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    borderRadius: radius.md,
    backgroundColor: colors.error,
  },
  confirmBtnDisabled: {
    opacity: 0.4,
  },
  confirmText: {
    fontFamily: font.bold,
    fontSize: fontSize.base,
    color: "#fff",
  },
});
