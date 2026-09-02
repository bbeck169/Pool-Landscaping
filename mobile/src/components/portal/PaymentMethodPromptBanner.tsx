/**
 * PaymentMethodPromptBanner.tsx — Phase K24
 *
 * Persistent light-blue banner on portal pages (except home + payment-method).
 * Reads ``original_prompt_kind`` so it renders even during an active snooze.
 * Inline dismiss ``×`` is session-scoped (module-level flag).
 * Impersonation JWT hides it entirely (K13 interlock).
 */
import React, { useEffect, useState } from "react";
import { Text, StyleSheet, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { spacing, font, fontSize } from "@/src/theme";
import type { PromptStatus, ExpiringCard } from "./PaymentMethodPromptModal";

/* ── session-scoped dismiss ──────────────────────────── */

let _bannerDismissed = false;

/** Reset for testing. */
export function _resetBannerDismissed() { _bannerDismissed = false; }

/* ── component ───────────────────────────────────────── */

export default function PaymentMethodPromptBanner() {
  const router = useRouter();
  const { isImpersonating } = useAuth();

  const [status, setStatus] = useState<PromptStatus | null>(null);
  const [dismissed, setDismissed] = useState(_bannerDismissed);

  useEffect(() => {
    if (isImpersonating) return;
    let cancelled = false;
    (async () => {
      try {
        const res: PromptStatus = await api.get(
          "/portal/payment-method/prompt-status",
        );
        if (!cancelled) setStatus(res);
      } catch {
        // Fail silently.
      }
    })();
    return () => { cancelled = true; };
  }, [isImpersonating]);

  // K13 interlock.
  if (isImpersonating) return null;
  if (dismissed) return null;
  if (!status) return null;

  const kind = status.original_prompt_kind;
  if (kind === "none") return null;

  const firstCard: ExpiringCard | undefined = status.expiring_cards?.[0];

  const handleDismiss = () => {
    _bannerDismissed = true;
    setDismissed(true);
  };

  const handleTap = () => {
    router.push("/portal/payment-method");
  };

  return (
    <Pressable
      style={s.banner}
      onPress={handleTap}
      testID="pm-prompt-banner"
    >
      <Ionicons name="alert-circle-outline" size={16} color="#1E40AF" />
      <Text style={s.text} numberOfLines={1} testID="pm-prompt-banner-text">
        {kind === "missing"
          ? "⚠ Add a payment method to keep your account active."
          : firstCard
            ? `⚠ Your ${firstCard.brand} ending ${firstCard.last4} expires soon.`
            : "⚠ Your card expires soon."}
      </Text>
      <Pressable
        style={s.closeBtn}
        onPress={handleDismiss}
        hitSlop={{ top: 12, bottom: 12, left: 12, right: 12 }}
        testID="pm-prompt-banner-dismiss"
      >
        <Ionicons name="close" size={16} color="#1E40AF" />
      </Pressable>
    </Pressable>
  );
}

/* ── styles ──────────────────────────────────────────── */

const s = StyleSheet.create({
  banner: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    backgroundColor: "#DBEAFE",
    borderBottomWidth: 1,
    borderBottomColor: "#BFDBFE",
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm + 2,
  },
  text: {
    flex: 1,
    fontFamily: font.medium,
    fontSize: fontSize.sm,
    color: "#1E40AF",
    lineHeight: 18,
  },
  closeBtn: {
    width: 28,
    height: 28,
    borderRadius: 14,
    alignItems: "center",
    justifyContent: "center",
  },
});
